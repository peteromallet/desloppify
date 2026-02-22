"""Shared detector phase runners reused by language configs."""

from __future__ import annotations

import os
from pathlib import Path

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine.detectors.complexity import detect_complexity
from desloppify.engine.detectors.dupes import detect_duplicates
from desloppify.engine.detectors.flat_dirs import detect_flat_dirs
from desloppify.engine.detectors.graph import detect_cycles
from desloppify.engine.detectors.jscpd_adapter import detect_with_jscpd
from desloppify.engine.detectors.large import detect_large_files
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.engine.detectors.review_coverage import (
    detect_holistic_review_staleness,
    detect_review_coverage,
)
from desloppify.engine.detectors.security.detector import detect_security_issues
from desloppify.engine.detectors.single_use import detect_single_use_abstractions
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine.policy.zones import EXCLUDED_ZONES, adjust_potential, filter_entries
from desloppify.languages._framework.base.structural import (
    add_structural_signal,
    merge_structural_signals,
)
from desloppify.languages._framework.finding_factories import (
    make_cycle_findings,
    make_dupe_findings,
    make_orphaned_findings,
    make_single_use_findings,
)
from desloppify.languages._framework.runtime import LangRun
from desloppify.state import Finding, make_finding
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import rel
from desloppify.utils import log


def phase_dupes(path: Path, lang: LangRun) -> tuple[list[Finding], dict[str, int]]:
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
    lang: LangRun,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase runner: detect repeated boilerplate code via jscpd."""
    entries = detect_with_jscpd(path)
    if entries is None:
        return [], {}

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
        log(f"         boilerplate duplication: {len(findings)} clusters")
    distinct_files = len({loc["file"] for e in entries for loc in e["locations"]})
    return findings, {"boilerplate_duplication": distinct_files}


def find_external_test_files(path: Path, lang: LangRun) -> set[str]:
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


def phase_security(path: Path, lang: LangRun) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect security issues (cross-language + lang-specific)."""
    zone_map = lang.zone_map
    files = lang.file_finder(path) if lang.file_finder else []
    entries, potential = detect_security_issues(files, zone_map, lang.name)

    # Also call lang-specific security detectors.
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
    lang: LangRun,
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
    lang: LangRun,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect cross-module private imports."""
    zone_map = lang.zone_map
    graph = lang.dep_graph or lang.build_dep_graph(path)

    entries, potential = lang.detect_private_imports(graph, zone_map)
    entries = filter_entries(zone_map, entries, "private_imports")

    results = _entries_to_findings("private_imports", entries)
    _log_phase_summary("private imports", results, potential, "files scanned")

    return results, {"private_imports": potential}


def phase_subjective_review(
    path: Path,
    lang: LangRun,
) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect files missing subjective design review."""
    zone_map = lang.zone_map
    max_age = lang.review_max_age_days
    files = lang.file_finder(path) if lang.file_finder else []
    review_cache = lang.review_cache
    if isinstance(review_cache, dict) and "files" in review_cache:
        per_file_cache = review_cache.get("files", {})
    else:
        # Legacy format: flat dict of file entries with no "files" wrapper.
        # Filter out known top-level structural keys so they aren't treated as
        # file paths, then reconstruct the canonical shape preserving them.
        _TOP_LEVEL_KEYS = frozenset({"holistic"})
        raw = review_cache if isinstance(review_cache, dict) else {}
        per_file_cache = {k: v for k, v in raw.items() if k not in _TOP_LEVEL_KEYS}
        review_cache = {"files": per_file_cache}
        if "holistic" in raw:
            review_cache["holistic"] = raw["holistic"]

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


def phase_signature(path: Path, lang: LangRun) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase runner: detect signature variance via lang.extract_functions.

    Backend-agnostic — works with any extractor that returns FunctionInfo objects
    (tree-sitter, regex, AST, etc.).  Returns empty results when the lang has no
    function extractor.
    """
    from desloppify.engine.detectors.signature import detect_signature_variance

    functions = lang.extract_functions(path)

    findings: list[Finding] = []
    potentials: dict[str, int] = {}

    if not functions:
        return findings, potentials

    entries, _total = detect_signature_variance(functions, min_occurrences=3)
    for e in entries:
        findings.append(make_finding(
            "signature", e["files"][0],
            f"signature_variance::{e['name']}",
            tier=3, confidence="medium",
            summary=(
                f"'{e['name']}' has {e['signature_count']} different signatures "
                f"across {e['file_count']} files"
            ),
        ))
    if entries:
        potentials["signature"] = len(entries)
        log(f"         signature variance: {len(entries)}")

    return findings, potentials


def run_structural_phase(
    path: Path,
    lang: LangRun,
    *,
    complexity_signals: list[ComplexitySignal],
    log_fn,
    min_loc: int = 40,
    god_rules=None,
    god_extractor_fn=None,
) -> tuple[list[dict], dict[str, int]]:
    """Run large/complexity/flat directory detectors for a language.

    Optional ``god_rules`` + ``god_extractor_fn`` enable god-class detection:
    when both are provided, ``god_extractor_fn(path)`` is called to extract
    class info, then ``detect_gods()`` finds classes matching multiple rules.
    """
    structural: dict[str, dict] = {}

    large_entries, file_count = detect_large_files(
        path,
        file_finder=lang.file_finder,
        threshold=lang.large_threshold,
    )
    for entry in large_entries:
        add_structural_signal(
            structural,
            entry["file"],
            f"large ({entry['loc']} LOC)",
            {"loc": entry["loc"]},
        )

    complexity_entries, _ = detect_complexity(
        path,
        signals=complexity_signals,
        file_finder=lang.file_finder,
        threshold=lang.complexity_threshold,
        min_loc=min_loc,
    )
    for entry in complexity_entries:
        add_structural_signal(
            structural,
            entry["file"],
            f"complexity score {entry['score']}",
            {"complexity_score": entry["score"], "complexity_signals": entry["signals"]},
        )
        lang.complexity_map[entry["file"]] = entry["score"]

    if god_rules and god_extractor_fn:
        from desloppify.engine.detectors.gods import detect_gods

        god_entries, _ = detect_gods(god_extractor_fn(path), god_rules, min_reasons=2)
        for entry in god_entries:
            add_structural_signal(
                structural, entry["file"], entry["signal_text"], entry["detail"],
            )
        if god_entries:
            log_fn(f"         god classes: {len(god_entries)}")

    results = merge_structural_signals(structural, log_fn)
    flat_entries, dir_count = detect_flat_dirs(path, file_finder=lang.file_finder)
    for entry in flat_entries:
        results.append(
            make_finding(
                "flat_dirs",
                entry["directory"],
                "",
                tier=3,
                confidence="medium",
                summary=(
                    f"Flat directory: {entry['file_count']} files — consider grouping by domain"
                ),
                detail={"file_count": entry["file_count"]},
            )
        )
    if flat_entries:
        log_fn(f"         flat dirs: {len(flat_entries)} directories with 20+ files")

    potentials = {
        "structural": adjust_potential(lang.zone_map, file_count),
        "flat_dirs": dir_count,
    }
    return results, potentials


def run_coupling_phase(
    path: Path,
    lang: LangRun,
    *,
    build_dep_graph_fn,
    log_fn,
    post_process_fn=None,
) -> tuple[list[dict], dict[str, int]]:
    """Run single-use/cycles/orphaned detectors against a language dep graph.

    Optional ``post_process_fn(findings, entries, lang)`` is called after
    creating single-use and orphaned findings to allow per-language
    adjustments (e.g. confidence gating based on corroboration signals).
    """
    graph = build_dep_graph_fn(path)
    lang.dep_graph = graph
    zone_map = lang.zone_map
    results: list[dict] = []

    single_entries, single_candidates = detect_single_use_abstractions(
        path,
        graph,
        barrel_names=lang.barrel_names,
    )
    single_entries = filter_entries(zone_map, single_entries, "single_use")
    single_findings = make_single_use_findings(
        single_entries, lang.get_area, stderr_fn=log_fn,
    )
    if post_process_fn:
        post_process_fn(single_findings, single_entries, lang)
    results.extend(single_findings)

    cycle_entries, _ = detect_cycles(graph)
    cycle_entries = filter_entries(zone_map, cycle_entries, "cycles", file_key="files")
    results.extend(make_cycle_findings(cycle_entries, log_fn))

    orphan_entries, total_graph_files = detect_orphaned_files(
        path,
        graph,
        extensions=lang.extensions,
        options=OrphanedDetectionOptions(
            extra_entry_patterns=lang.entry_patterns,
            extra_barrel_names=lang.barrel_names,
        ),
    )
    orphan_entries = filter_entries(zone_map, orphan_entries, "orphaned")
    orphan_findings = make_orphaned_findings(orphan_entries, log_fn)
    if post_process_fn:
        post_process_fn(orphan_findings, orphan_entries, lang)
    results.extend(orphan_findings)

    log_fn(f"         -> {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": adjust_potential(zone_map, single_candidates),
        "cycles": adjust_potential(zone_map, total_graph_files),
        "orphaned": adjust_potential(zone_map, total_graph_files),
    }
    return results, potentials


__all__ = [
    "find_external_test_files",
    "phase_boilerplate_duplication",
    "phase_dupes",
    "phase_private_imports",
    "phase_security",
    "phase_signature",
    "phase_subjective_review",
    "phase_test_coverage",
    "run_coupling_phase",
    "run_structural_phase",
]
