"""Shared detector phase runners reused by language configs."""

from __future__ import annotations

import os
from pathlib import Path

from desloppify.engine.detectors.boilerplate_duplication import (
    detect_boilerplate_duplication,
)
from desloppify.engine.detectors.dupes import detect_duplicates
from desloppify.engine.detectors.review_coverage import (
    detect_holistic_review_staleness,
    detect_review_coverage,
)
from desloppify.engine.detectors.security.detector import detect_security_issues
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine.policy.zones import EXCLUDED_ZONES, filter_entries
from desloppify.engine.state_internal.schema import Finding
from desloppify.languages.framework.finding_factories import make_dupe_findings
from desloppify.state import make_finding
from desloppify.utils import PROJECT_ROOT, log, rel

from .types import LangConfig


def phase_dupes(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase runner: detect duplicate functions via lang.extract_functions.

    When a zone map is available, filters out functions from zone-excluded files
    before the O(n^2) comparison to avoid test/config/generated false positives.
    """
    functions = lang.extract_functions(path)

    # Filter out functions from zone-excluded files.
    if lang.zone_map is not None:
        before = len(functions)
        functions = [
            f
            for f in functions
            if lang.zone_map.get(getattr(f, "file", "")) not in EXCLUDED_ZONES
        ]
        excluded = before - len(functions)
        if excluded:
            log(f"         zones: {excluded} functions excluded (non-production)")

    entries, total_functions = detect_duplicates(functions)
    findings = make_dupe_findings(entries, log)
    return findings, {"dupes": total_functions}


def phase_boilerplate_duplication(
    path: Path,
    lang: LangConfig,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase runner: detect repeated boilerplate code windows across files."""
    file_finder = lang.file_finder
    if file_finder is None:
        return [], {}

    entries, total_files = detect_boilerplate_duplication(path, file_finder=file_finder)
    findings: list[Finding] = []
    for entry in entries:
        locations = entry["locations"]
        first = locations[0]
        loc_preview = ", ".join(
            f"{rel(item['file'])}:{item['line']}" for item in locations[:4]
        )
        if len(locations) > 4:
            loc_preview += f", +{len(locations) - 4} more"
        findings.append(
            make_finding(
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

    if findings:
        log(
            "         boilerplate duplication: "
            f"{len(findings)} clusters across {total_files} files"
        )
    return findings, {"boilerplate_duplication": total_files}


def find_external_test_files(path: Path, lang: LangConfig) -> set[str]:
    """Find test files in standard locations outside the scanned path."""
    extra = set()
    path_root = path.resolve()
    test_dirs = lang.external_test_dirs or ["tests", "test"]
    exts = tuple(lang.test_file_extensions or lang.extensions)
    for test_dir in test_dirs:
        d = PROJECT_ROOT / test_dir
        if not d.is_dir():
            continue
        if d.resolve().is_relative_to(path_root):
            continue  # test_dir is inside scanned path, zone_map already has it
        for root, _, files in os.walk(d):
            for filename in files:
                if any(filename.endswith(ext) for ext in exts):
                    extra.add(os.path.join(root, filename))
    return extra


def _entries_to_findings(
    detector: str,
    entries: list[dict],
    *,
    default_name: str = "",
    include_zone: bool = False,
    zone_map=None,
) -> list[Finding]:
    """Convert detector entries to normalized findings."""
    results: list[Finding] = []
    for entry in entries:
        finding = make_finding(
            detector,
            entry["file"],
            entry.get("name", default_name),
            tier=entry["tier"],
            confidence=entry["confidence"],
            summary=entry["summary"],
            detail=entry.get("detail", {}),
        )
        if include_zone and zone_map is not None:
            z = zone_map.get(entry["file"])
            if z is not None:
                finding["zone"] = z.value
        results.append(finding)
    return results


def _log_phase_summary(label: str, results: list[Finding], potential: int, unit: str) -> None:
    """Emit standardized shared-phase summary logging."""
    if results:
        log(f"         {label}: {len(results)} findings ({potential} {unit})")
    else:
        log(f"         {label}: clean ({potential} {unit})")


def phase_security(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect security issues (cross-language + lang-specific)."""
    zone_map = lang.zone_map
    files = lang.file_finder(path) if lang.file_finder else []
    entries, potential = detect_security_issues(files, zone_map, lang.name)

    # Also call lang-specific security detectors if available.
    if hasattr(lang, "detect_lang_security"):
        lang_entries, _ = lang.detect_lang_security(files, zone_map)
        entries.extend(lang_entries)

    entries = filter_entries(zone_map, entries, "security")

    results = _entries_to_findings(
        "security",
        entries,
        include_zone=True,
        zone_map=zone_map,
    )
    _log_phase_summary("security", results, potential, "files scanned")

    return results, {"security": potential}


def phase_test_coverage(
    path: Path,
    lang: LangConfig,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect test coverage gaps."""
    zone_map = lang.zone_map
    if zone_map is None:
        return [], {}

    graph = lang.dep_graph or lang.build_dep_graph(path)
    extra = find_external_test_files(path, lang)
    entries, potential = detect_test_coverage(
        graph,
        zone_map,
        lang.name,
        extra_test_files=extra or None,
        complexity_map=lang.complexity_map or None,
    )
    entries = filter_entries(zone_map, entries, "test_coverage")

    results = _entries_to_findings("test_coverage", entries, default_name="")
    _log_phase_summary("test coverage", results, potential, "production files")

    return results, {"test_coverage": potential}


def phase_private_imports(
    path: Path,
    lang: LangConfig,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect cross-module private imports."""
    if not hasattr(lang, "detect_private_imports"):
        return [], {}

    zone_map = lang.zone_map
    graph = lang.dep_graph or lang.build_dep_graph(path)

    entries, potential = lang.detect_private_imports(graph, zone_map)
    entries = filter_entries(zone_map, entries, "private_imports")

    results = _entries_to_findings("private_imports", entries)
    _log_phase_summary("private imports", results, potential, "files scanned")

    return results, {"private_imports": potential}


def phase_subjective_review(
    path: Path,
    lang: LangConfig,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect files missing subjective design review."""
    zone_map = lang.zone_map
    max_age = lang.review_max_age_days
    files = lang.file_finder(path) if lang.file_finder else []
    review_cache = lang.review_cache
    if isinstance(review_cache, dict) and "files" in review_cache:
        per_file_cache = review_cache.get("files", {})
    else:
        per_file_cache = review_cache if isinstance(review_cache, dict) else {}
        review_cache = {"files": per_file_cache}

    entries, potential = detect_review_coverage(
        files,
        zone_map,
        per_file_cache,
        lang.name,
        low_value_pattern=lang.review_low_value_pattern,
        max_age_days=max_age,
    )

    # Also check holistic review staleness.
    holistic_entries = detect_holistic_review_staleness(
        review_cache,
        total_files=len(files),
        max_age_days=max_age,
    )
    entries.extend(holistic_entries)

    results = _entries_to_findings("subjective_review", entries)
    _log_phase_summary("subjective review", results, potential, "reviewable files")

    return results, {"subjective_review": potential}


__all__ = [
    "find_external_test_files",
    "phase_boilerplate_duplication",
    "phase_dupes",
    "phase_private_imports",
    "phase_security",
    "phase_subjective_review",
    "phase_test_coverage",
]
