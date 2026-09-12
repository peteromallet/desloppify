"""Structural/coupling phase runners shared by language runtimes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine.detectors.complexity import detect_complexity
from desloppify.engine.detectors.flat_dirs import (
    FlatDirDetectionConfig,
    detect_flat_dirs,
    format_flat_dir_summary,
)
from desloppify.engine.detectors.graph import detect_cycles
from desloppify.engine.detectors.large import detect_large_files
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.engine.detectors.single_use import detect_single_use_abstractions
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages._framework.base.structural import (
    add_structural_signal,
    merge_structural_signals,
)
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages._framework.issue_factories import (
    make_cycle_issues,
    make_orphaned_issues,
    make_single_use_issues,
)
from desloppify.state_io import Issue

StructuralPhaseRunner = Callable[
    [Path, LangRuntimeContract],
    tuple[list[Issue], dict[str, int]],
]


def run_structural_phase(
    path: Path,
    lang: LangRuntimeContract,
    *,
    complexity_signals: list[ComplexitySignal],
    log_fn,
    min_loc: int = 40,
    god_rules=None,
    god_extractor_fn=None,
) -> tuple[list[Issue], dict[str, int]]:
    """Run large/complexity/flat-directory detectors for a language."""
    structural: dict[str, dict[str, Any]] = {}

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
            {
                "complexity_score": entry["score"],
                "complexity_signals": entry["signals"],
            },
        )
        lang.complexity_map[entry["file"]] = entry["score"]

    if god_rules and god_extractor_fn:
        from desloppify.engine.detectors.gods import detect_gods

        god_entries, _ = detect_gods(god_extractor_fn(path), god_rules, min_reasons=2)
        for entry in god_entries:
            add_structural_signal(
                structural,
                entry["file"],
                entry["signal_text"],
                entry["detail"],
            )
        if god_entries:
            log_fn(f"         god classes: {len(god_entries)}")

    results = merge_structural_signals(structural, log_fn)
    flat_entries, analyzed_dir_count = detect_flat_dirs(
        path,
        file_finder=lang.file_finder,
        config=FlatDirDetectionConfig(),
    )
    for entry in flat_entries:
        child_dir_count = int(entry.get("child_dir_count", 0))
        combined_score = int(entry.get("combined_score", entry.get("file_count", 0)))
        results.append(
            make_issue(
                "flat_dirs",
                entry["directory"],
                "",
                tier=3,
                confidence="medium",
                summary=format_flat_dir_summary(entry),
                detail={
                    "file_count": entry["file_count"],
                    "child_dir_count": child_dir_count,
                    "combined_score": combined_score,
                    "kind": entry.get("kind", "overload"),
                    "parent_sibling_count": int(entry.get("parent_sibling_count", 0)),
                    "wrapper_item_count": int(entry.get("wrapper_item_count", 0)),
                    "sparse_child_count": int(entry.get("sparse_child_count", 0)),
                    "sparse_child_ratio": float(entry.get("sparse_child_ratio", 0.0)),
                    "sparse_child_file_threshold": int(
                        entry.get("sparse_child_file_threshold", 0)
                    ),
                },
            )
        )
    if flat_entries:
        log_fn(
            f"         flat dirs: {len(flat_entries)} overloaded directories "
            "(files/subdirs/combined)"
        )

    potentials = {
        "structural": adjust_potential(lang.zone_map, file_count),
        "flat_dirs": analyzed_dir_count,
    }
    return results, potentials


def run_coupling_phase(
    path: Path,
    lang: LangRuntimeContract,
    *,
    build_dep_graph_fn,
    log_fn,
    post_process_fn=None,
    dynamic_import_finder=None,
) -> tuple[list[Issue], dict[str, int]]:
    """Run single-use/cycles/orphaned detectors against a language dep graph."""
    graph = build_dep_graph_fn(path)
    lang.dep_graph = graph
    zone_map = lang.zone_map
    results: list[Issue] = []

    single_entries, single_candidates = detect_single_use_abstractions(
        path,
        graph,
        barrel_names=lang.barrel_names,
    )
    single_entries = filter_entries(zone_map, single_entries, "single_use")
    single_issues = make_single_use_issues(single_entries, lang.get_area, stderr_fn=log_fn)
    if post_process_fn:
        post_process_fn(single_issues, single_entries, lang)
    results.extend(single_issues)

    cycle_entries, _ = detect_cycles(graph)
    cycle_entries = filter_entries(zone_map, cycle_entries, "cycles", file_key="files")
    results.extend(make_cycle_issues(cycle_entries, log_fn))

    orphan_entries, total_graph_files = detect_orphaned_files(
        path,
        graph,
        extensions=lang.extensions,
        options=OrphanedDetectionOptions(
            extra_entry_patterns=lang.entry_patterns,
            extra_barrel_names=lang.barrel_names,
            dynamic_import_finder=dynamic_import_finder,
        ),
    )
    orphan_entries = filter_entries(zone_map, orphan_entries, "orphaned")
    orphan_issues = make_orphaned_issues(orphan_entries, log_fn)
    if post_process_fn:
        post_process_fn(orphan_issues, orphan_entries, lang)
    results.extend(orphan_issues)

    log_fn(f"         -> {len(results)} coupling/structural issues total")
    potentials = {
        "single_use": adjust_potential(zone_map, single_candidates),
        "cycles": adjust_potential(zone_map, total_graph_files),
        "orphaned": adjust_potential(zone_map, total_graph_files),
    }
    return results, potentials


def make_structural_coupling_phase_pair(
    *,
    complexity_signals: list[ComplexitySignal],
    build_dep_graph_fn,
    log_fn,
) -> tuple[StructuralPhaseRunner, StructuralPhaseRunner]:
    """Create default structural/coupling phase callables for a language."""

    def phase_structural(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        return run_structural_phase(
            path,
            lang,
            complexity_signals=complexity_signals,
            log_fn=log_fn,
        )

    def phase_coupling(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        return run_coupling_phase(
            path,
            lang,
            build_dep_graph_fn=build_dep_graph_fn,
            log_fn=log_fn,
        )

    return phase_structural, phase_coupling


__all__ = [
    "make_structural_coupling_phase_pair",
    "run_coupling_phase",
    "run_structural_phase",
]
