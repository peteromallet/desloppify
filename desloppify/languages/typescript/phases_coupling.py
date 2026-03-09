"""Coupling and dependency-oriented TypeScript phase helpers."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.discovery.file_paths import rel
from desloppify.base.discovery.paths import get_src_path
from desloppify.base.output.terminal import log
from desloppify.engine.detectors import coupling as coupling_detector_mod
from desloppify.engine.detectors import graph as graph_detector_mod
from desloppify.engine.detectors import naming as naming_detector_mod
from desloppify.engine.detectors import orphaned as orphaned_detector_mod
from desloppify.engine.detectors import single_use as single_use_detector_mod
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages._framework.issue_factories import (
    make_cycle_issues,
    make_facade_issues,
    make_orphaned_issues,
    make_single_use_issues,
)
from desloppify.languages.typescript.detectors import deps as deps_detector_mod
from desloppify.languages.typescript.detectors import facade as facade_detector_mod
from desloppify.languages.typescript.detectors import patterns_analysis as patterns_detector_mod
from desloppify.languages.typescript.phases_config import TS_SKIP_DIRS, TS_SKIP_NAMES
from desloppify.state import Issue, make_issue


def detect_single_use(
    path: Path, graph: dict, lang: LangRuntimeContract
) -> tuple[list[Issue], list[dict], int]:
    """Detect single-use abstractions."""
    single_entries, single_candidates = single_use_detector_mod.detect_single_use_abstractions(
        path, graph, barrel_names=lang.barrel_names
    )
    single_entries = filter_entries(lang.zone_map, single_entries, "single_use")
    issues = make_single_use_issues(
        single_entries, lang.get_area, skip_dir_names={"commands"}, stderr_fn=log
    )
    return issues, single_entries, single_candidates


def detect_coupling_violations(
    path: Path,
    graph: dict,
    lang: LangRuntimeContract,
    shared_prefix: str,
    tools_prefix: str,
) -> tuple[list[Issue], int]:
    """Detect backwards coupling violations."""
    coupling_entries, coupling_edge_counts = coupling_detector_mod.detect_coupling_violations(
        path, graph, shared_prefix=shared_prefix, tools_prefix=tools_prefix
    )
    coupling_entries = filter_entries(lang.zone_map, coupling_entries, "coupling")
    results: list[Issue] = []
    for entry in coupling_entries:
        results.append(
            make_issue(
                "coupling",
                entry["file"],
                entry["target"],
                tier=2,
                confidence="high",
                summary=f"Backwards coupling: shared imports {entry['target']} (tool: {entry['tool']})",
                detail={
                    "target": entry["target"],
                    "tool": entry["tool"],
                    "direction": entry["direction"],
                },
            )
        )
    return results, coupling_edge_counts.eligible_edges


def detect_cross_tool_imports(
    path: Path,
    graph: dict,
    lang: LangRuntimeContract,
    tools_prefix: str,
) -> tuple[list[Issue], int]:
    """Detect cross-tool import violations."""
    cross_tool, cross_edge_counts = coupling_detector_mod.detect_cross_tool_imports(
        path, graph, tools_prefix=tools_prefix
    )
    cross_tool = filter_entries(lang.zone_map, cross_tool, "coupling")
    results: list[Issue] = []
    for entry in cross_tool:
        results.append(
            make_issue(
                "coupling",
                entry["file"],
                entry["target"],
                tier=2,
                confidence="high",
                summary=(
                    f"Cross-tool import: {entry['source_tool']}→{entry['target_tool']} "
                    f"({entry['target']})"
                ),
                detail={
                    "target": entry["target"],
                    "source_tool": entry["source_tool"],
                    "target_tool": entry["target_tool"],
                    "direction": entry["direction"],
                },
            )
        )
    if cross_tool:
        log(f"         cross-tool: {len(cross_tool)} imports")
    return results, cross_edge_counts.eligible_edges


def detect_cycles_and_orphans(
    path: Path, graph: dict, lang: LangRuntimeContract
) -> tuple[list[Issue], int]:
    """Detect import cycles and orphaned files."""
    results: list[Issue] = []
    cycle_entries, _ = graph_detector_mod.detect_cycles(graph)
    cycle_entries = filter_entries(lang.zone_map, cycle_entries, "cycles", file_key="files")
    results.extend(make_cycle_issues(cycle_entries, log))

    orphan_entries, total_graph_files = orphaned_detector_mod.detect_orphaned_files(
        path,
        graph,
        extensions=lang.extensions,
        options=orphaned_detector_mod.OrphanedDetectionOptions(
            extra_entry_patterns=lang.entry_patterns,
            extra_barrel_names=lang.barrel_names,
            dynamic_import_finder=deps_detector_mod.build_dynamic_import_targets,
            alias_resolver=deps_detector_mod.ts_alias_resolver,
        ),
    )
    orphan_entries = filter_entries(lang.zone_map, orphan_entries, "orphaned")
    results.extend(make_orphaned_issues(orphan_entries, log))
    return results, total_graph_files


def detect_facades(graph: dict, lang: LangRuntimeContract) -> list[Issue]:
    """Detect re-export facade files."""
    facade_entries, _ = facade_detector_mod.detect_reexport_facades(graph)
    facade_entries = filter_entries(lang.zone_map, facade_entries, "facade")
    return make_facade_issues(facade_entries, log)


def detect_pattern_anomalies(path: Path) -> tuple[list[Issue], int]:
    """Detect pattern consistency anomalies across areas."""
    pattern_result = patterns_detector_mod.detect_pattern_anomalies_result(path)
    pattern_entries = pattern_result.entries
    total_areas = pattern_result.population_size
    results: list[Issue] = []
    for entry in pattern_entries:
        results.append(
            make_issue(
                "patterns",
                entry["area"],
                entry["family"],
                tier=3,
                confidence=entry.get("confidence", "low"),
                summary=f"Competing patterns ({entry['family']}): {entry['review'][:120]}",
                detail={
                    "family": entry["family"],
                    "patterns_used": entry["patterns_used"],
                    "pattern_count": entry["pattern_count"],
                    "review": entry["review"],
                },
            )
        )
    return results, total_areas


def detect_naming_inconsistencies(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], int]:
    """Detect naming convention inconsistencies within directories."""
    naming_entries, total_dirs = naming_detector_mod.detect_naming_inconsistencies(
        path,
        file_finder=lang.file_finder,
        skip_names=TS_SKIP_NAMES,
        skip_dirs=TS_SKIP_DIRS,
    )
    results: list[Issue] = []
    for entry in naming_entries:
        results.append(
            make_issue(
                "naming",
                entry["directory"],
                entry["minority"],
                tier=3,
                confidence="low",
                summary=(
                    f"Naming inconsistency: {entry['minority_count']} {entry['minority']} files "
                    f"in {entry['majority']}-majority dir ({entry['total_files']} total)"
                ),
                detail={
                    "majority": entry["majority"],
                    "majority_count": entry["majority_count"],
                    "minority": entry["minority"],
                    "minority_count": entry["minority_count"],
                    "outliers": entry["outliers"],
                },
            )
        )
    return results, total_dirs


def make_boundary_issues(
    single_entries: list[dict],
    path: Path,
    graph: dict,
    lang: LangRuntimeContract,
    shared_prefix: str,
    tools_prefix: str,
) -> tuple[list[Issue], int]:
    """Create boundary-candidate issues, deduplicated against single-use."""
    single_use_emitted = set()
    for entry in single_entries:
        is_size_ok = 50 <= entry["loc"] <= 200
        is_colocated = lang.get_area and (
            lang.get_area(rel(entry["file"])) == lang.get_area(entry["sole_importer"])
        )
        if not is_size_ok and not is_colocated:
            single_use_emitted.add(rel(entry["file"]))

    results: list[Issue] = []
    deduped = 0
    boundary_entries, total_shared = coupling_detector_mod.detect_boundary_candidates(
        path,
        graph,
        shared_prefix=shared_prefix,
        tools_prefix=tools_prefix,
        skip_basenames={"index.ts", "index.tsx"},
    )
    for entry in boundary_entries:
        if rel(entry["file"]) in single_use_emitted:
            deduped += 1
            continue
        results.append(
            make_issue(
                "coupling",
                entry["file"],
                f"boundary::{entry['sole_tool']}",
                tier=3,
                confidence="medium",
                summary=(
                    f"Boundary candidate ({entry['loc']} LOC): only used by {entry['sole_tool']} "
                    f"({entry['importer_count']} importers)"
                ),
                detail={
                    "sole_tool": entry["sole_tool"],
                    "importer_count": entry["importer_count"],
                    "loc": entry["loc"],
                },
            )
        )
    if deduped:
        log(
            f"         ({deduped} boundary candidates skipped — covered by single_use)"
        )
    return results, total_shared


def phase_coupling(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Run the coupling phase."""
    results: list[Issue] = []
    graph = deps_detector_mod.build_dep_graph(path)
    lang.dep_graph = graph
    zone_map = lang.zone_map

    single_use_issues, single_entries, single_candidates = detect_single_use(
        path, graph, lang
    )
    results.extend(single_use_issues)

    src_path = get_src_path()
    shared_prefix = f"{src_path}/shared/"
    tools_prefix = f"{src_path}/tools/"

    coupling_issues, coupling_edges = detect_coupling_violations(
        path, graph, lang, shared_prefix, tools_prefix
    )
    results.extend(coupling_issues)

    boundary_issues, _ = make_boundary_issues(
        single_entries, path, graph, lang, shared_prefix, tools_prefix
    )
    results.extend(boundary_issues)

    cross_tool_issues, cross_edges = detect_cross_tool_imports(
        path, graph, lang, tools_prefix
    )
    results.extend(cross_tool_issues)

    cycle_orphan_issues, total_graph_files = detect_cycles_and_orphans(path, graph, lang)
    results.extend(cycle_orphan_issues)

    results.extend(detect_facades(graph, lang))

    pattern_issues, total_areas = detect_pattern_anomalies(path)
    results.extend(pattern_issues)

    naming_issues, total_dirs = detect_naming_inconsistencies(path, lang)
    results.extend(naming_issues)

    log(f"         → {len(results)} coupling/structural issues total")
    potentials = {
        "single_use": adjust_potential(zone_map, single_candidates),
        "coupling": coupling_edges + cross_edges,
        "cycles": adjust_potential(zone_map, total_graph_files),
        "orphaned": adjust_potential(zone_map, total_graph_files),
        "patterns": total_areas,
        "naming": total_dirs,
        "facade": adjust_potential(zone_map, total_graph_files),
    }
    return results, potentials


__all__ = [
    "coupling_detector_mod",
    "detect_coupling_violations",
    "detect_cross_tool_imports",
    "detect_cycles_and_orphans",
    "detect_facades",
    "detect_naming_inconsistencies",
    "detect_pattern_anomalies",
    "detect_single_use",
    "make_boundary_issues",
    "orphaned_detector_mod",
    "phase_coupling",
]
