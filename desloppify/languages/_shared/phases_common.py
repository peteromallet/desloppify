"""Shared phase runners for scaffold language plugins."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine.detectors.complexity import detect_complexity
from desloppify.engine.detectors.flat_dirs import detect_flat_dirs
from desloppify.engine.detectors.graph import detect_cycles
from desloppify.engine.detectors.large import detect_large_files
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.engine.detectors.single_use import detect_single_use_abstractions
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages.framework.base.structural import (
    add_structural_signal,
    merge_structural_signals,
)
from desloppify.languages.framework.base.types import LangConfig
from desloppify.languages.framework.finding_factories import (
    make_cycle_findings,
    make_orphaned_findings,
    make_single_use_findings,
)
from desloppify.state import make_finding


def run_structural_phase(
    path: Path,
    lang: LangConfig,
    *,
    complexity_signals: list[ComplexitySignal],
    log_fn,
    min_loc: int = 40,
) -> tuple[list[dict], dict[str, int]]:
    """Run large/complexity/flat directory detectors for a language."""
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
    lang: LangConfig,
    *,
    build_dep_graph_fn,
    log_fn,
) -> tuple[list[dict], dict[str, int]]:
    """Run single-use/cycles/orphaned detectors against a language dep graph."""
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
    results.extend(make_single_use_findings(single_entries, lang.get_area, stderr_fn=log_fn))

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
    results.extend(make_orphaned_findings(orphan_entries, log_fn))

    log_fn(f"         -> {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": adjust_potential(zone_map, single_candidates),
        "cycles": adjust_potential(zone_map, total_graph_files),
        "orphaned": adjust_potential(zone_map, total_graph_files),
    }
    return results, potentials


__all__ = ["run_coupling_phase", "run_structural_phase"]
