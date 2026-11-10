"""Helper utilities shared by detector phase runners."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from desloppify.base.coercions import coerce_confidence
from desloppify.base.discovery.source import SourceDiscoveryOptions, find_source_files
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.output.terminal import log
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import should_skip_issue
from desloppify.languages._framework.base.types import (
    DetectorCoverageStatus,
    DetectorEntry,
    LangRuntimeContract,
)
from desloppify.state_io import Issue


def _filter_boilerplate_entries_by_zone(
    entries: list[DetectorEntry],
    zone_map,
) -> list[DetectorEntry]:
    """Keep only in-scope, zone-allowed boilerplate clusters."""
    if zone_map is None:
        return entries

    known_files = set(zone_map.all_files())
    filtered: list[DetectorEntry] = []
    skipped = 0
    for entry in entries:
        locations = entry.get("locations", [])
        kept_locations = [
            loc
            for loc in locations
            if loc.get("file") in known_files
            and not should_skip_issue(
                zone_map,
                loc.get("file", ""),
                "boilerplate_duplication",
            )
        ]
        distinct_files = {loc["file"] for loc in kept_locations}
        if len(distinct_files) < 2:
            skipped += 1
            continue

        normalized = dict(entry)
        normalized["locations"] = sorted(
            kept_locations,
            key=lambda item: (item.get("file", ""), item.get("line", 0)),
        )
        normalized["distinct_files"] = len(distinct_files)
        filtered.append(normalized)

    if skipped:
        log(f"         zones: {skipped} boilerplate clusters excluded")
    return filtered


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a project-relative glob into a regex.

    ``*`` and ``?`` stay within one path segment; ``**`` spans segments.
    A pattern that names a directory also matches everything below it.
    """
    pattern = pattern.replace("\\", "/").removeprefix("./").rstrip("/")
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out) + "(?:/.*)?$")


def _find_test_root_files(
    path_root: Path,
    project_root: Path,
    patterns: list[str],
    exts: tuple[str, ...],
    lang: LangRuntimeContract,
) -> set[str]:
    """Find test files matching ``test_roots`` globs among the scan's own candidates.

    Candidates come from the same file discovery the scan uses (the language's
    ``file_finder``, else ``find_source_files`` with the language exclusions),
    so ``desloppify exclude`` entries and language file exclusions apply.
    """
    regexes = [_glob_to_regex(p) for p in patterns if isinstance(p, str) and p.strip()]
    if not regexes:
        return set()
    if lang.file_finder is not None:
        candidates = lang.file_finder(project_root)
    else:
        exclusions = getattr(lang, "exclusions", None) or []
        candidates = find_source_files(
            project_root,
            list(exts),
            SourceDiscoveryOptions(
                exclusions=tuple(exclusions), project_root=project_root
            ),
        )
    found: set[str] = set()
    for candidate in candidates:
        if not candidate.endswith(exts):
            continue
        full = Path(candidate)
        if not full.is_absolute():
            full = project_root / full
        if full.resolve().is_relative_to(path_root):
            continue
        try:
            rel_path = full.relative_to(project_root).as_posix()
        except ValueError:
            continue
        if any(rx.match(rel_path) for rx in regexes):
            found.add(str(full))
    return found


def _find_external_test_files(
    path: Path,
    lang: LangRuntimeContract,
    *,
    get_project_root_fn: Callable[[], Path] = get_project_root,
) -> set[str]:
    """Find test files outside the scanned path.

    Looks in ``lang.external_test_dirs`` under the project root and in any
    files matching the ``test_roots`` config globs.
    """
    extra = set()
    path_root = path.resolve()
    project_root = get_project_root_fn()
    test_dirs = lang.external_test_dirs or ["tests", "test"]
    exts = tuple(lang.test_file_extensions or lang.extensions)
    for test_dir in test_dirs:
        directory = project_root / test_dir
        if not directory.is_dir():
            continue
        if directory.resolve().is_relative_to(path_root):
            continue
        for root, _, files in os.walk(directory):
            for filename in files:
                if any(filename.endswith(ext) for ext in exts):
                    extra.add(os.path.join(root, filename))
    test_roots = getattr(lang, "test_roots", None)
    if isinstance(test_roots, list) and test_roots:
        extra |= _find_test_root_files(
            path_root, project_root, test_roots, exts, lang
        )
    return extra


def _entries_to_issues(
    detector: str,
    entries: list[DetectorEntry],
    *,
    default_name: str = "",
    include_zone: bool = False,
    zone_map=None,
) -> list[Issue]:
    """Convert detector entries to normalized issues."""
    results: list[Issue] = []
    for entry in entries:
        issue = make_issue(
            detector,
            entry["file"],
            entry.get("name", default_name),
            tier=entry["tier"],
            confidence=entry["confidence"],
            summary=entry["summary"],
            detail=entry.get("detail", {}),
        )
        if include_zone and zone_map is not None:
            zone = zone_map.get(entry["file"])
            if zone is not None:
                issue["zone"] = zone.value
        results.append(issue)
    return results


def _log_phase_summary(
    label: str,
    results: list[Issue],
    potential: int,
    unit: str,
    *,
    log_fn: Callable[[str], None] = log,
) -> None:
    """Emit standardized shared-phase summary logging."""
    if results:
        log_fn(f"         {label}: {len(results)} issues ({potential} {unit})")
    else:
        log_fn(f"         {label}: clean ({potential} {unit})")


def _coverage_to_dict(coverage: DetectorCoverageStatus) -> dict[str, Any]:
    return {
        "detector": coverage.detector,
        "status": coverage.status,
        "confidence": round(coerce_confidence(coverage.confidence), 2),
        "summary": coverage.summary,
        "impact": coverage.impact,
        "remediation": coverage.remediation,
        "tool": coverage.tool,
        "reason": coverage.reason,
    }


def _merge_detector_coverage(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing)
    merged["status"] = (
        "reduced"
        if str(existing.get("status", "full")) == "reduced"
        or str(incoming.get("status", "full")) == "reduced"
        else "full"
    )
    merged["confidence"] = round(
        min(
            coerce_confidence(existing.get("confidence")),
            coerce_confidence(incoming.get("confidence")),
        ),
        2,
    )

    for key in ("summary", "impact", "remediation", "tool", "reason"):
        current = str(merged.get(key, "") or "").strip()
        update = str(incoming.get(key, "") or "").strip()
        if update and not current:
            merged[key] = update
        elif update and current and update not in current:
            merged[key] = f"{current} | {update}"
    return merged


def _record_detector_coverage(
    lang: LangRuntimeContract,
    coverage: DetectorCoverageStatus | None,
) -> None:
    if coverage is None:
        return
    normalized = _coverage_to_dict(coverage)
    detector = str(normalized.get("detector", "")).strip()
    if not detector:
        return
    existing = lang.detector_coverage.get(detector)
    if isinstance(existing, dict):
        lang.detector_coverage[detector] = _merge_detector_coverage(existing, normalized)
    else:
        lang.detector_coverage[detector] = normalized


__all__ = [
    "_coverage_to_dict",
    "_entries_to_issues",
    "_filter_boilerplate_entries_by_zone",
    "_find_external_test_files",
    "_log_phase_summary",
    "_merge_detector_coverage",
    "_record_detector_coverage",
]
