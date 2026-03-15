"""Review-oriented shared detector phases (dupes, security, coverage, etc.)."""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import log
from desloppify.engine.detectors.dupes import detect_duplicates
from desloppify.engine.detectors.jscpd_adapter import detect_with_jscpd
from desloppify.engine.detectors.security.detector import (
    detect_security_issues as _detect_security_issues_default,
)
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import EXCLUDED_ZONES, filter_entries
from desloppify.languages._framework.base.types import (
    DetectorCoverageStatus,
    DetectorEntry,
    LangRuntimeContract,
    LangSecurityResult,
)
from desloppify.languages._framework.issue_factories import make_dupe_issues
from desloppify.state_io import Issue

from .shared_phases_helpers import (
    _coverage_to_dict,
    _entries_to_issues,
    _filter_boilerplate_entries_by_zone,
    _find_external_test_files,
    _log_phase_summary,
    _record_detector_coverage,
)

# Compatibility export for language phase modules that still import the raw
# security detector symbol from this module.
detect_security_issues = _detect_security_issues_default

_DETECTOR_CACHE_VERSION = 1
_PREFETCH_ATTR = "_shared_review_prefetch_futures"
_FUNCTION_CACHE_ATTR = "_shared_review_function_cache"
_PREFETCH_BOILERPLATE_KEY = "boilerplate"
_PREFETCH_SECURITY_KEY = "security_lang"
_PREFETCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _detector_cache(review_cache: object, detector: str) -> dict[str, object] | None:
    """Return mutable detector cache payload from review cache."""
    if not isinstance(review_cache, dict):
        return None
    detectors = review_cache.get("detectors")
    if not isinstance(detectors, dict):
        detectors = {}
        review_cache["detectors"] = detectors
    payload = detectors.get(detector)
    if not isinstance(payload, dict):
        payload = {}
        detectors[detector] = payload
    return payload


def _dupes_cache(review_cache: object) -> dict[str, object] | None:
    return _detector_cache(review_cache, "dupes")


def _boilerplate_cache(review_cache: object) -> dict[str, object] | None:
    return _detector_cache(review_cache, "boilerplate")


def _security_cache(review_cache: object) -> dict[str, object] | None:
    return _detector_cache(review_cache, "security")


def _get_prefetch_futures(
    lang: object,
    *,
    create: bool,
) -> dict[str, concurrent.futures.Future[Any]]:
    """Read/write in-memory review prefetch futures attached to LangRun."""
    payload = getattr(lang, _PREFETCH_ATTR, None)
    if isinstance(payload, dict):
        normalized: dict[str, concurrent.futures.Future[Any]] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, concurrent.futures.Future):
                normalized[key] = value
        if normalized is not payload:
            setattr(lang, _PREFETCH_ATTR, normalized)
        return normalized
    if not create:
        return {}
    initialized: dict[str, concurrent.futures.Future[Any]] = {}
    setattr(lang, _PREFETCH_ATTR, initialized)
    return initialized


def _pop_prefetch_future(
    lang: object,
    key: str,
) -> concurrent.futures.Future[Any] | None:
    """Detach and return one prefetch future."""
    futures = _get_prefetch_futures(lang, create=False)
    future = futures.pop(key, None)
    if not futures:
        try:
            delattr(lang, _PREFETCH_ATTR)
        except AttributeError:
            pass
    if isinstance(future, concurrent.futures.Future):
        return future
    return None


def _consume_prefetch_result(
    lang: object,
    key: str,
) -> object | None:
    """Return completed prefetch result, swallowing async failures."""
    future = _pop_prefetch_future(lang, key)
    if future is None:
        return None
    try:
        return future.result()
    except Exception:
        return None


def _has_phase(
    phases: list[object],
    *,
    labels: set[str],
    run_names: set[str],
) -> bool:
    for phase in phases:
        label = str(getattr(phase, "label", "")).strip().lower()
        run = getattr(phase, "run", None)
        run_name = str(getattr(run, "__name__", "")).strip().lower()
        run_func = getattr(run, "func", None)
        run_func_name = str(getattr(run_func, "__name__", "")).strip().lower()
        if label in labels or run_name in run_names or run_func_name in run_names:
            return True
    return False


def _resolve_review_functions(path: Path, lang: LangRuntimeContract):
    """Resolve language function extraction once per scan path."""
    cache = getattr(lang, _FUNCTION_CACHE_ATTR, None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(lang, _FUNCTION_CACHE_ATTR, cache)
    cache_key = str(path.resolve())
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        return cached
    extracted = lang.extract_functions(path)
    cache[cache_key] = extracted
    return extracted


def _resolve_detector_files(path: Path, lang: LangRuntimeContract) -> list[str]:
    """Resolve a detector file list for cache fingerprinting."""
    zone_map = getattr(lang, "zone_map", None)
    if zone_map is not None and hasattr(zone_map, "all_files"):
        zone_files = zone_map.all_files()
        if isinstance(zone_files, list):
            return zone_files
    file_finder = getattr(lang, "file_finder", None)
    if file_finder:
        return file_finder(path)
    return []


def _resolve_detector_file_path(scan_root: Path, filepath: str) -> Path:
    """Resolve a detector file path against the active scan root."""
    file_path = Path(filepath)
    if file_path.is_absolute():
        return file_path
    return (scan_root / file_path).resolve()


def _file_fingerprint(
    *,
    scan_root: Path,
    files: list[str],
    zone_map=None,
    include_zone: bool = False,
    salt: str = "",
) -> str:
    """Build a stable file-signature hash from path + mtime + size + zone."""
    hasher = hashlib.blake2b(digest_size=20)
    hasher.update(str(scan_root.resolve()).encode("utf-8", errors="replace"))
    hasher.update(b"\0")
    hasher.update(salt.encode("utf-8", errors="replace"))
    hasher.update(b"\0")
    for filepath in sorted({str(item) for item in files}):
        resolved = _resolve_detector_file_path(scan_root, filepath)
        normalized = filepath.replace("\\", "/")
        hasher.update(normalized.encode("utf-8", errors="replace"))
        hasher.update(b"\0")
        try:
            stats = os.stat(resolved)
            hasher.update(str(stats.st_size).encode("ascii", errors="ignore"))
            hasher.update(b"\0")
            hasher.update(str(stats.st_mtime_ns).encode("ascii", errors="ignore"))
            hasher.update(b"\0")
        except OSError:
            hasher.update(b"-1\0-1\0")
        if include_zone and zone_map is not None:
            zone = zone_map.get(filepath)
            zone_value = getattr(zone, "value", zone)
            hasher.update(str(zone_value or "").encode("utf-8", errors="replace"))
            hasher.update(b"\0")
    return hasher.hexdigest()


def _load_cached_boilerplate_entries(
    cache: dict[str, object],
    *,
    fingerprint: str,
) -> list[dict] | None:
    """Load cached boilerplate entries when fingerprint is unchanged."""
    if cache.get("version") != _DETECTOR_CACHE_VERSION:
        return None
    if cache.get("fingerprint") != fingerprint:
        return None
    entries = cache.get("entries")
    if not isinstance(entries, list):
        return None
    return [entry for entry in entries if isinstance(entry, dict)]


def _store_cached_boilerplate_entries(
    cache: dict[str, object],
    *,
    fingerprint: str,
    entries: list[dict],
) -> None:
    """Persist boilerplate detector entries for unchanged scans."""
    cache.clear()
    cache.update(
        {
            "version": _DETECTOR_CACHE_VERSION,
            "fingerprint": fingerprint,
            "entries": [entry for entry in entries if isinstance(entry, dict)],
        }
    )


def _coverage_from_record(payload: object) -> DetectorCoverageStatus | None:
    """Rebuild coverage dataclass from serialized cache payload."""
    if not isinstance(payload, dict):
        return None
    detector = str(payload.get("detector", "")).strip()
    status = str(payload.get("status", "")).strip()
    if not detector or status not in {"full", "reduced"}:
        return None
    confidence_raw = payload.get("confidence", 1.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 1.0
    return DetectorCoverageStatus(
        detector=detector,
        status=status,
        confidence=confidence,
        summary=str(payload.get("summary", "") or ""),
        impact=str(payload.get("impact", "") or ""),
        remediation=str(payload.get("remediation", "") or ""),
        tool=str(payload.get("tool", "") or ""),
        reason=str(payload.get("reason", "") or ""),
    )


def _load_cached_security_result(
    cache: dict[str, object],
    *,
    fingerprint: str,
) -> LangSecurityResult | None:
    """Load cached language-specific security result when unchanged."""
    if cache.get("version") != _DETECTOR_CACHE_VERSION:
        return None
    if cache.get("fingerprint") != fingerprint:
        return None
    entries = cache.get("entries")
    files_scanned = cache.get("files_scanned")
    if not isinstance(entries, list) or not isinstance(files_scanned, int):
        return None
    normalized_entries = [entry for entry in entries if isinstance(entry, dict)]
    return LangSecurityResult(
        entries=normalized_entries,
        files_scanned=max(0, files_scanned),
        coverage=_coverage_from_record(cache.get("coverage")),
    )


def _store_cached_security_result(
    cache: dict[str, object],
    *,
    fingerprint: str,
    result: LangSecurityResult,
) -> None:
    """Persist language-specific security results for unchanged scans."""
    cache.clear()
    cache.update(
        {
            "version": _DETECTOR_CACHE_VERSION,
            "fingerprint": fingerprint,
            "entries": [entry for entry in result.entries if isinstance(entry, dict)],
            "files_scanned": max(0, int(result.files_scanned)),
            "coverage": (
                _coverage_to_dict(result.coverage) if result.coverage is not None else None
            ),
        }
    )


def prewarm_review_phase_detectors(
    path: Path,
    lang: LangRuntimeContract,
    phases: list[object],
) -> None:
    """Start expensive shared review detectors in background for overlap."""
    futures = _get_prefetch_futures(lang, create=True)

    if _has_phase(
        phases,
        labels={"boilerplate duplication"},
        run_names={"phase_boilerplate_duplication"},
    ):
        boilerplate_cache = _boilerplate_cache(getattr(lang, "review_cache", None))
        detector_files = _resolve_detector_files(path, lang)
        fingerprint = _file_fingerprint(
            scan_root=path,
            files=detector_files,
            salt=f"boilerplate:{getattr(lang, 'name', '')}",
        )
        cached_entries = (
            _load_cached_boilerplate_entries(boilerplate_cache, fingerprint=fingerprint)
            if isinstance(boilerplate_cache, dict)
            else None
        )
        if cached_entries is None and _PREFETCH_BOILERPLATE_KEY not in futures:
            futures[_PREFETCH_BOILERPLATE_KEY] = _PREFETCH_EXECUTOR.submit(
                detect_with_jscpd,
                path,
            )

    if _has_phase(
        phases,
        labels={"security"},
        run_names={"phase_security"},
    ):
        file_finder = getattr(lang, "file_finder", None)
        files = file_finder(path) if file_finder else []
        zone_map = getattr(lang, "zone_map", None)
        security_cache = _security_cache(getattr(lang, "review_cache", None))
        fingerprint = _file_fingerprint(
            scan_root=path,
            files=files,
            zone_map=zone_map,
            include_zone=True,
            salt=f"security:{getattr(lang, 'name', '')}",
        )
        cached_result = (
            _load_cached_security_result(security_cache, fingerprint=fingerprint)
            if isinstance(security_cache, dict)
            else None
        )
        if cached_result is None and _PREFETCH_SECURITY_KEY not in futures:
            futures[_PREFETCH_SECURITY_KEY] = _PREFETCH_EXECUTOR.submit(
                lang.detect_lang_security_detailed,
                files,
                zone_map,
            )


def clear_review_phase_prefetch(lang: object) -> None:
    """Drop in-memory prefetch futures and function caches after scan run."""
    futures = _get_prefetch_futures(lang, create=False)
    for future in futures.values():
        if isinstance(future, concurrent.futures.Future) and not future.done():
            future.cancel()
    if hasattr(lang, _PREFETCH_ATTR):
        try:
            delattr(lang, _PREFETCH_ATTR)
        except AttributeError:
            pass
    if hasattr(lang, _FUNCTION_CACHE_ATTR):
        try:
            delattr(lang, _FUNCTION_CACHE_ATTR)
        except AttributeError:
            pass


def phase_dupes(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase runner: detect duplicate functions via lang.extract_functions."""
    functions = _resolve_review_functions(path, lang)

    if lang.zone_map is not None:
        before = len(functions)
        functions = [
            function
            for function in functions
            if lang.zone_map.get(getattr(function, "file", "")) not in EXCLUDED_ZONES
        ]
        excluded = before - len(functions)
        if excluded:
            log(f"         zones: {excluded} functions excluded (non-production)")

    entries, total_functions = detect_duplicates(
        functions,
        cache=_dupes_cache(getattr(lang, "review_cache", None)),
    )
    issues = make_dupe_issues(entries, log)
    return issues, {"dupes": total_functions}


def phase_boilerplate_duplication(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase runner: detect repeated boilerplate code via jscpd."""
    cache = _boilerplate_cache(getattr(lang, "review_cache", None))
    detector_files = _resolve_detector_files(path, lang)
    fingerprint = _file_fingerprint(
        scan_root=path,
        files=detector_files,
        salt=f"boilerplate:{getattr(lang, 'name', '')}",
    )
    entries = (
        _load_cached_boilerplate_entries(cache, fingerprint=fingerprint)
        if isinstance(cache, dict)
        else None
    )
    if entries is None:
        prefetched = _consume_prefetch_result(lang, _PREFETCH_BOILERPLATE_KEY)
        entries = prefetched if isinstance(prefetched, list) else None
        if entries is None:
            entries = detect_with_jscpd(path)
        if isinstance(cache, dict) and entries is not None:
            _store_cached_boilerplate_entries(
                cache,
                fingerprint=fingerprint,
                entries=entries,
            )
    if entries is None:
        return [], {}
    entries = _filter_boilerplate_entries_by_zone(entries, lang.zone_map)

    issues: list[Issue] = []
    for entry in entries:
        locations = entry["locations"]
        first = locations[0]
        loc_preview = ", ".join(
            f"{rel(item['file'])}:{item['line']}" for item in locations[:4]
        )
        if len(locations) > 4:
            loc_preview += f", +{len(locations) - 4} more"
        issues.append(
            make_issue(
                "boilerplate_duplication",
                first["file"],
                entry["id"],
                tier=3,
                confidence="medium",
                summary=(
                    f"Boilerplate block repeated across {entry['distinct_files']} files "
                    f"(window {entry['window_size']} lines): {loc_preview}"
                ),
                detail={
                    "distinct_files": entry["distinct_files"],
                    "window_size": entry["window_size"],
                    "locations": locations,
                    "sample": entry["sample"],
                },
            )
        )

    if issues:
        log(f"         boilerplate duplication: {len(issues)} clusters")
    distinct_files = len({loc["file"] for entry in entries for loc in entry["locations"]})
    return issues, {"boilerplate_duplication": distinct_files}


def phase_security(
    path: Path,
    lang: LangRuntimeContract,
    *,
    detect_security_issues: Callable[..., tuple[list[DetectorEntry], int]] = (
        _detect_security_issues_default
    ),
) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase: detect security issues (cross-language + lang-specific)."""
    zone_map = lang.zone_map
    files = lang.file_finder(path) if lang.file_finder else []
    entries, cross_lang_scanned = detect_security_issues(
        files,
        zone_map,
        lang.name,
        scan_root=path,
    )
    lang_scanned = 0

    security_cache = _security_cache(getattr(lang, "review_cache", None))
    security_fingerprint = _file_fingerprint(
        scan_root=path,
        files=files,
        zone_map=zone_map,
        include_zone=True,
        salt=f"security:{getattr(lang, 'name', '')}",
    )
    lang_result = (
        _load_cached_security_result(
            security_cache,
            fingerprint=security_fingerprint,
        )
        if isinstance(security_cache, dict)
        else None
    )
    if lang_result is None:
        prefetched = _consume_prefetch_result(lang, _PREFETCH_SECURITY_KEY)
        lang_result = prefetched if isinstance(prefetched, LangSecurityResult) else None
        if lang_result is None:
            lang_result = lang.detect_lang_security_detailed(files, zone_map)
        if isinstance(security_cache, dict):
            _store_cached_security_result(
                security_cache,
                fingerprint=security_fingerprint,
                result=lang_result,
            )
    lang_entries = lang_result.entries
    lang_scanned = max(0, int(lang_result.files_scanned))
    _record_detector_coverage(lang, lang_result.coverage)
    entries.extend(lang_entries)

    entries = filter_entries(zone_map, entries, "security")
    potential = max(cross_lang_scanned, lang_scanned)

    results = _entries_to_issues(
        "security",
        entries,
        include_zone=True,
        zone_map=zone_map,
    )
    _log_phase_summary("security", results, potential, "files scanned")

    if "security" not in lang.detector_coverage:
        lang.detector_coverage["security"] = {
            "detector": "security",
            "status": "full",
            "confidence": 1.0,
            "summary": "Security coverage complete for enabled detectors.",
            "impact": "",
            "remediation": "",
            "tool": "",
            "reason": "",
        }

    return results, {"security": potential}


def phase_test_coverage(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase: detect test coverage gaps."""
    zone_map = lang.zone_map
    if zone_map is None:
        return [], {}

    graph = lang.dep_graph or lang.build_dep_graph(path)
    extra = _find_external_test_files(path, lang)
    entries, potential = detect_test_coverage(
        graph,
        zone_map,
        lang.name,
        extra_test_files=extra or None,
        complexity_map=lang.complexity_map or None,
    )
    entries = filter_entries(zone_map, entries, "test_coverage")

    results = _entries_to_issues("test_coverage", entries, default_name="")
    _log_phase_summary("test coverage", results, potential, "production files")

    return results, {"test_coverage": potential}


def phase_private_imports(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase: detect cross-module private imports."""
    zone_map = lang.zone_map
    graph = lang.dep_graph or lang.build_dep_graph(path)

    entries, potential = lang.detect_private_imports(graph, zone_map)
    entries = filter_entries(zone_map, entries, "private_imports")

    results = _entries_to_issues("private_imports", entries)
    _log_phase_summary("private imports", results, potential, "files scanned")

    return results, {"private_imports": potential}


def phase_subjective_review(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase: detect subjective dimensions needing review.

    Creates one issue per unassessed/stale subjective dimension instead of
    per-file coverage markers.  The per-file review cache is still used by
    ``review --prepare`` to know which files to queue, but does not generate
    individual issues.
    """
    from desloppify.base.subjective_dimensions import (
        default_dimension_keys_for_lang,
        dimension_display_name,
    )

    assessments = lang.subjective_assessments if isinstance(lang.subjective_assessments, dict) else {}
    default_dims = default_dimension_keys_for_lang(lang.name)
    potential = len(default_dims)

    results: list[Issue] = []
    for dim_key in default_dims:
        assessment = assessments.get(dim_key)
        if isinstance(assessment, dict):
            is_placeholder = (
                assessment.get("placeholder") is True
                or assessment.get("source") == "scan_reset_subjective"
                or assessment.get("reset_by") == "scan_reset_subjective"
            )
            if not is_placeholder:
                continue  # assessed and not stale — skip
            reason = "stale"
            summary = (
                f"{dimension_display_name(dim_key, lang_name=lang.name)} — "
                "assessment reset by scan, re-review recommended"
            )
        else:
            reason = "unassessed"
            summary = (
                f"{dimension_display_name(dim_key, lang_name=lang.name)} — "
                "no assessment on record, run `desloppify review --prepare`"
            )

        results.append(
            make_issue(
                "subjective_review",
                ".",
                dim_key,
                tier=4,
                confidence="low",
                summary=summary,
                detail={"reason": reason, "dimension": dim_key},
            )
        )

    _log_phase_summary("subjective review", results, potential, "dimensions")

    return results, {"subjective_review": potential}


def phase_signature(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Shared phase runner: detect signature variance via lang.extract_functions."""
    from desloppify.engine.detectors.signature import detect_signature_variance

    functions = _resolve_review_functions(path, lang)

    issues: list[Issue] = []
    potentials: dict[str, int] = {}

    if not functions:
        return issues, potentials

    entries, _total = detect_signature_variance(functions, min_occurrences=3)
    for entry in entries:
        issues.append(
            make_issue(
                "signature",
                entry["files"][0],
                f"signature_variance::{entry['name']}",
                tier=3,
                confidence="medium",
                summary=(
                    f"'{entry['name']}' has {entry['signature_count']} different signatures "
                    f"across {entry['file_count']} files"
                ),
            )
        )
    if entries:
        potentials["signature"] = len(entries)
        log(f"         signature variance: {len(entries)}")

    return issues, potentials


__all__ = [
    "clear_review_phase_prefetch",
    "phase_boilerplate_duplication",
    "phase_dupes",
    "phase_private_imports",
    "prewarm_review_phase_detectors",
    "phase_security",
    "phase_signature",
    "phase_subjective_review",
    "phase_test_coverage",
]
