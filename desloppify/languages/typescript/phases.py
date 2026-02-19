"""TypeScript detector phase runners."""

from __future__ import annotations

# NOTE: This module intentionally remains high-LOC; it keeps TypeScript plugin
# orchestration centralized to preserve language-plugin simplicity.
import re
from collections import defaultdict
from pathlib import Path

from desloppify.engine.detectors import complexity as complexity_detector_mod
from desloppify.engine.detectors import coupling as coupling_detector_mod
from desloppify.engine.detectors import flat_dirs as flat_dirs_detector_mod
from desloppify.engine.detectors import gods as gods_detector_mod
from desloppify.engine.detectors import graph as graph_detector_mod
from desloppify.engine.detectors import large as large_detector_mod
from desloppify.engine.detectors import naming as naming_detector_mod
from desloppify.engine.detectors import orphaned as orphaned_detector_mod
from desloppify.engine.detectors import signature as signature_detector_mod
from desloppify.engine.detectors import single_use as single_use_detector_mod
from desloppify.engine.detectors.base import ComplexitySignal, GodRule
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages.framework.base.structural import (
    add_structural_signal,
    merge_structural_signals,
)
from desloppify.languages.framework.base.types import LangConfig
from desloppify.languages.framework.finding_factories import (
    make_cycle_findings,
    make_facade_findings,
    make_orphaned_findings,
    make_single_use_findings,
    make_smell_findings,
    make_unused_findings,
)
from desloppify.languages.typescript.detectors import concerns as concerns_detector_mod
from desloppify.languages.typescript.detectors import (
    deprecated as deprecated_detector_mod,
)
from desloppify.languages.typescript.detectors import deps as deps_detector_mod
from desloppify.languages.typescript.detectors import exports as exports_detector_mod
from desloppify.languages.typescript.detectors import facade as facade_detector_mod
from desloppify.languages.typescript.detectors import logs as logs_detector_mod
from desloppify.languages.typescript.detectors import patterns as patterns_detector_mod
from desloppify.languages.typescript.detectors import props as props_detector_mod
from desloppify.languages.typescript.detectors import react as react_detector_mod
from desloppify.languages.typescript.detectors import smells as smells_detector_mod
from desloppify.languages.typescript.detectors import unused as unused_detector_mod
from desloppify.languages.typescript.extractors_components import (
    detect_passthrough_components,
    extract_ts_components,
)
from desloppify.state import make_finding
from desloppify.utils import SRC_PATH, log, rel

# ── Helper computations for complexity signals ─────────────


def _compute_ts_destructure_props(content, lines):
    long_destructures = re.findall(r"\{\s*(\w+(?:\s*,\s*\w+){8,})\s*\}", content)
    if not long_destructures:
        return None
    max_props = max(len(d.split(",")) for d in long_destructures)
    return max_props, f"destructure w/{max_props} props"


def _compute_ts_inline_types(content, lines):
    inline_types = len(
        re.findall(r"^(?:export\s+)?(?:type|interface)\s+\w+", content, re.MULTILINE)
    )
    if inline_types > 3:
        return inline_types, f"{inline_types} inline types"
    return None


# ── Config data (single source of truth) ──────────────────


TS_COMPLEXITY_SIGNALS = [
    ComplexitySignal("imports", r"^import\s", weight=1, threshold=15),
    ComplexitySignal(
        "destructured props",
        None,
        weight=1,
        threshold=8,
        compute=_compute_ts_destructure_props,
    ),
    ComplexitySignal("useEffects", r"useEffect\s*\(", weight=3, threshold=3),
    ComplexitySignal(
        "inline types", None, weight=1, threshold=3, compute=_compute_ts_inline_types
    ),
    ComplexitySignal("TODOs", r"//\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
    ComplexitySignal(
        "nested ternaries", r"[^?]\?[^?.:\n][^:\n]*[^?]\?[^?.]", weight=3, threshold=2
    ),
    ComplexitySignal("useRefs", r"\buseRef\s*[<(]", weight=2, threshold=6),
]

TS_GOD_RULES = [
    GodRule(
        "context_hooks", "context hooks", lambda c: c.metrics.get("context_hooks", 0), 3
    ),
    GodRule("use_effects", "useEffects", lambda c: c.metrics.get("use_effects", 0), 4),
    GodRule("use_states", "useStates", lambda c: c.metrics.get("use_states", 0), 5),
    GodRule(
        "custom_hooks", "custom hooks", lambda c: c.metrics.get("custom_hooks", 0), 8
    ),
    GodRule("hook_total", "total hooks", lambda c: c.metrics.get("hook_total", 0), 10),
]

TS_SKIP_NAMES = {
    "index.ts",
    "index.tsx",
    "types.ts",
    "types.tsx",
    "constants.ts",
    "constants.tsx",
    "utils.ts",
    "utils.tsx",
    "helpers.ts",
    "helpers.tsx",
    "settings.ts",
    "settings.tsx",
    "main.ts",
    "main.tsx",
    "App.tsx",
    "vite-env.d.ts",
}

TS_SKIP_DIRS = {"src/shared/components/ui"}


# ── Phase runners ──────────────────────────────────────────


def _phase_logs(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    log_result = logs_detector_mod.detect_logs_result(path)
    log_entries = log_result.entries
    total_files = log_result.population_size
    log_groups: dict[tuple, list] = defaultdict(list)
    for e in log_entries:
        log_groups[(e["file"], e["tag"])].append(e)
    results = []
    for (file, tag), entries in log_groups.items():
        results.append(
            make_finding(
                "logs",
                file,
                tag,
                tier=1,
                confidence="high",
                summary=f"{len(entries)} tagged logs [{tag}]",
                detail={
                    "count": len(entries),
                    "lines": [e["line"] for e in entries[:20]],
                },
            )
        )
    log(f"         {len(log_entries)} instances → {len(results)} findings")
    return results, {"logs": adjust_potential(lang.zone_map, total_files)}


def _phase_unused(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    entries, total_files = unused_detector_mod.detect_unused(path)
    return make_unused_findings(entries, log), {
        "unused": adjust_potential(lang.zone_map, total_files),
    }


def _phase_exports(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    export_entries, total_exports = exports_detector_mod.detect_dead_exports(path)
    results = []
    for e in export_entries:
        results.append(
            make_finding(
                "exports",
                e["file"],
                e["name"],
                tier=2,
                confidence="high",
                summary=f"Dead export: {e['name']}",
                detail={"line": e.get("line"), "kind": e.get("kind")},
            )
        )
    log(f"         {len(export_entries)} instances → {len(results)} findings")
    return results, {"exports": total_exports}


def _phase_deprecated(
    path: Path, lang: LangConfig
) -> tuple[list[dict], dict[str, int]]:
    dep_result = deprecated_detector_mod.detect_deprecated_result(path)
    dep_entries = dep_result.entries
    total_deprecated = dep_result.population_size
    results = []
    for e in dep_entries:
        if e["kind"] == "property":
            continue
        tier = 1 if e["importers"] == 0 else 3
        results.append(
            make_finding(
                "deprecated",
                e["file"],
                e["symbol"],
                tier=tier,
                confidence="high",
                summary=f"Deprecated: {e['symbol']} ({e['importers']} importers)"
                + (" → safe to delete" if e["importers"] == 0 else ""),
                detail={"importers": e["importers"], "line": e["line"]},
            )
        )
    log(
        f"         {len(dep_entries)} instances → {len(results)} findings (properties suppressed)"
    )
    return results, {"deprecated": total_deprecated}


def _phase_structural(
    path: Path, lang: LangConfig
) -> tuple[list[dict], dict[str, int]]:
    structural: dict[str, dict] = {}

    large_entries, file_count = large_detector_mod.detect_large_files(
        path,
        file_finder=lang.file_finder,
        threshold=lang.large_threshold,
    )
    for e in large_entries:
        add_structural_signal(
            structural, e["file"], f"large ({e['loc']} LOC)", {"loc": e["loc"]}
        )

    complexity_entries, _ = complexity_detector_mod.detect_complexity(
        path,
        signals=TS_COMPLEXITY_SIGNALS,
        file_finder=lang.file_finder,
        threshold=lang.complexity_threshold,
    )
    for e in complexity_entries:
        add_structural_signal(
            structural,
            e["file"],
            f"complexity score {e['score']}",
            {"complexity_score": e["score"], "complexity_signals": e["signals"]},
        )
        lang.complexity_map[e["file"]] = e["score"]

    god_entries, _ = gods_detector_mod.detect_gods(
        extract_ts_components(path), TS_GOD_RULES, min_reasons=2
    )
    for e in god_entries:
        add_structural_signal(
            structural,
            e["file"],
            f"{e['detail'].get('hook_total', 0)} hooks ({', '.join(e['reasons'][:2])})",
            {
                "hook_total": e["detail"].get("hook_total", 0),
                "hook_reasons": e["reasons"],
            },
        )

    concern_entries, _ = concerns_detector_mod.detect_mixed_concerns(path)
    for e in concern_entries:
        add_structural_signal(
            structural,
            e["file"],
            f"mixed: {', '.join(e['concerns'][:3])}",
            {"concerns": e["concerns"]},
        )

    results = merge_structural_signals(structural, log)

    # Flat directories (too many files → missing sub-organization)
    flat_entries, dir_count = flat_dirs_detector_mod.detect_flat_dirs(
        path, file_finder=lang.file_finder
    )
    for e in flat_entries:
        results.append(
            make_finding(
                "flat_dirs",
                e["directory"],
                "",
                tier=3,
                confidence="medium",
                summary=f"Flat directory: {e['file_count']} files — consider grouping by domain",
                detail={"file_count": e["file_count"]},
            )
        )
    if flat_entries:
        log(f"         flat dirs: {len(flat_entries)} directories with 20+ files")

    # TS-specific: props bloat
    props_thresh = lang.props_threshold
    prop_entries, prop_count = props_detector_mod.detect_prop_interface_bloat(
        path, threshold=props_thresh
    )
    for e in prop_entries:
        pc = e["prop_count"]
        # Tiered severity: 15-29=low, 30-49=medium, 50+=high
        if pc >= 50:
            conf, tier = "high", 4
        elif pc >= 30:
            conf, tier = "medium", 3
        else:
            conf, tier = "low", 3
        results.append(
            make_finding(
                "props",
                e["file"],
                e["interface"],
                tier=tier,
                confidence=conf,
                summary=f"Bloated {e.get('kind', 'props')}: {e['interface']} ({pc} fields)",
                detail={
                    "prop_count": pc,
                    "line": e["line"],
                    "kind": e.get("kind", "props"),
                },
            )
        )

    # TS-specific: passthrough components
    pt_entries = detect_passthrough_components(path)
    for e in pt_entries:
        results.append(
            make_finding(
                "props",
                e["file"],
                f"passthrough::{e['component']}",
                tier=e["tier"],
                confidence=e["confidence"],
                summary=f"Passthrough component: {e['component']} "
                f"({e['passthrough']}/{e['total_props']} props forwarded, {e['ratio']:.0%})",
                detail={
                    "passthrough": e["passthrough"],
                    "total_props": e["total_props"],
                    "ratio": e["ratio"],
                    "line": e["line"],
                    "passthrough_props": e["passthrough_props"],
                    "direct_props": e["direct_props"],
                },
            )
        )
    potentials = {
        "structural": adjust_potential(lang.zone_map, file_count),
        "flat_dirs": dir_count,
        "props": max(prop_count, len(pt_entries)) if prop_count else len(pt_entries),
    }
    return results, potentials


def _make_boundary_findings(
    single_entries: list[dict],
    path: Path,
    graph: dict,
    lang: LangConfig,
    shared_prefix: str,
    tools_prefix: str,
) -> tuple[list[dict], int]:
    """Create boundary-candidate findings, deduplicated against single-use."""
    single_use_emitted = set()
    for e in single_entries:
        is_size_ok = 50 <= e["loc"] <= 200
        is_colocated = lang.get_area and (
            lang.get_area(rel(e["file"])) == lang.get_area(e["sole_importer"])
        )
        if not is_size_ok and not is_colocated:
            single_use_emitted.add(rel(e["file"]))

    results = []
    deduped = 0
    boundary_entries, total_shared = coupling_detector_mod.detect_boundary_candidates(
        path,
        graph,
        shared_prefix=shared_prefix,
        tools_prefix=tools_prefix,
        skip_basenames={"index.ts", "index.tsx"},
    )
    for e in boundary_entries:
        if rel(e["file"]) in single_use_emitted:
            deduped += 1
            continue
        results.append(
            make_finding(
                "coupling",
                e["file"],
                f"boundary::{e['sole_tool']}",
                tier=3,
                confidence="medium",
                summary=f"Boundary candidate ({e['loc']} LOC): only used by {e['sole_tool']} "
                f"({e['importer_count']} importers)",
                detail={
                    "sole_tool": e["sole_tool"],
                    "importer_count": e["importer_count"],
                    "loc": e["loc"],
                },
            )
        )
    if deduped:
        log(f"         ({deduped} boundary candidates skipped — covered by single_use)")
    return results, total_shared


def _phase_coupling(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    results = []
    graph = deps_detector_mod.build_dep_graph(path)
    lang.dep_graph = graph
    zm = lang.zone_map

    # Single-use (shared helper)
    single_entries, single_candidates = (
        single_use_detector_mod.detect_single_use_abstractions(
            path, graph, barrel_names=lang.barrel_names
        )
    )
    single_entries = filter_entries(zm, single_entries, "single_use")
    results.extend(
        make_single_use_findings(
            single_entries, lang.get_area, skip_dir_names={"commands"}, stderr_fn=log
        )
    )
    shared_prefix = f"{SRC_PATH}/shared/"
    tools_prefix = f"{SRC_PATH}/tools/"
    coupling_entries, coupling_edges = coupling_detector_mod.detect_coupling_violations(
        path, graph, shared_prefix=shared_prefix, tools_prefix=tools_prefix
    )
    coupling_entries = filter_entries(zm, coupling_entries, "coupling")
    for e in coupling_entries:
        results.append(
            make_finding(
                "coupling",
                e["file"],
                e["target"],
                tier=2,
                confidence="high",
                summary=f"Backwards coupling: shared imports {e['target']} (tool: {e['tool']})",
                detail={
                    "target": e["target"],
                    "tool": e["tool"],
                    "direction": e["direction"],
                },
            )
        )

    # TS-specific: boundary candidates (deduplicated against single-use)
    boundary_findings, _ = _make_boundary_findings(
        single_entries, path, graph, lang, shared_prefix, tools_prefix
    )
    results.extend(boundary_findings)

    # TS-specific: cross-tool imports
    cross_tool, cross_edges = coupling_detector_mod.detect_cross_tool_imports(
        path, graph, tools_prefix=tools_prefix
    )
    cross_tool = filter_entries(zm, cross_tool, "coupling")
    for e in cross_tool:
        results.append(
            make_finding(
                "coupling",
                e["file"],
                e["target"],
                tier=2,
                confidence="high",
                summary=f"Cross-tool import: {e['source_tool']}→{e['target_tool']} ({e['target']})",
                detail={
                    "target": e["target"],
                    "source_tool": e["source_tool"],
                    "target_tool": e["target_tool"],
                    "direction": e["direction"],
                },
            )
        )
    if cross_tool:
        log(f"         cross-tool: {len(cross_tool)} imports")

    # Cycles + orphaned (shared helpers)
    cycle_entries, _ = graph_detector_mod.detect_cycles(graph)
    cycle_entries = filter_entries(zm, cycle_entries, "cycles", file_key="files")
    results.extend(make_cycle_findings(cycle_entries, log))
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
    orphan_entries = filter_entries(zm, orphan_entries, "orphaned")
    results.extend(make_orphaned_findings(orphan_entries, log))

    # Re-export facades (shared detector)
    facade_entries, _ = facade_detector_mod.detect_reexport_facades(graph)
    facade_entries = filter_entries(zm, facade_entries, "facade")
    results.extend(make_facade_findings(facade_entries, log))

    # TS-specific: pattern consistency
    pattern_result = patterns_detector_mod.detect_pattern_anomalies_result(path)
    pattern_entries = pattern_result.entries
    total_areas = pattern_result.population_size
    for e in pattern_entries:
        results.append(
            make_finding(
                "patterns",
                e["area"],
                e["family"],
                tier=3,
                confidence=e.get("confidence", "low"),
                summary=f"Competing patterns ({e['family']}): {e['review'][:120]}",
                detail={
                    "family": e["family"],
                    "patterns_used": e["patterns_used"],
                    "pattern_count": e["pattern_count"],
                    "review": e["review"],
                },
            )
        )

    # TS-specific: naming consistency
    naming_entries, total_dirs = naming_detector_mod.detect_naming_inconsistencies(
        path,
        file_finder=lang.file_finder,
        skip_names=TS_SKIP_NAMES,
        skip_dirs=TS_SKIP_DIRS,
    )
    for e in naming_entries:
        results.append(
            make_finding(
                "naming",
                e["directory"],
                e["minority"],
                tier=3,
                confidence="low",
                summary=f"Naming inconsistency: {e['minority_count']} {e['minority']} files "
                f"in {e['majority']}-majority dir ({e['total_files']} total)",
                detail={
                    "majority": e["majority"],
                    "majority_count": e["majority_count"],
                    "minority": e["minority"],
                    "minority_count": e["minority_count"],
                    "outliers": e["outliers"],
                },
            )
        )
    log(f"         → {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": adjust_potential(zm, single_candidates),
        "coupling": coupling_edges + cross_edges,
        "cycles": adjust_potential(zm, total_graph_files),
        "orphaned": adjust_potential(zm, total_graph_files),
        "patterns": total_areas,
        "naming": total_dirs,
        "facade": adjust_potential(zm, total_graph_files),
    }
    return results, potentials


def _phase_smells(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    smell_entries, total_smell_files = smells_detector_mod.detect_smells(path)
    results = make_smell_findings(smell_entries, log)

    # Cross-file: signature variance
    functions = lang.extract_functions(path) if lang.extract_functions else []
    sig_entries, _ = signature_detector_mod.detect_signature_variance(functions)
    for e in sig_entries:
        results.append(
            make_finding(
                "smells",
                e["files"][0],
                f"sig_variance::{e['name']}",
                tier=3,
                confidence="medium",
                summary=f"Signature variance: {e['name']}() has {e['signature_count']} "
                f"different signatures across {e['file_count']} files",
                detail={
                    "function": e["name"],
                    "file_count": e["file_count"],
                    "signature_count": e["signature_count"],
                    "variants": e["variants"][:5],
                },
            )
        )
    if sig_entries:
        log(
            f"         signature variance: {len(sig_entries)} functions with inconsistent signatures"
        )

    # TS-specific: React state sync anti-patterns
    react_entries, total_effects = react_detector_mod.detect_state_sync(path)
    for e in react_entries:
        setter_str = ", ".join(e["setters"])
        results.append(
            make_finding(
                "react",
                e["file"],
                setter_str,
                tier=3,
                confidence="medium",
                summary=f"State sync anti-pattern: useEffect only calls {setter_str}",
                detail={"line": e["line"], "setters": e["setters"]},
            )
        )
    if react_entries:
        log(f"         react: {len(react_entries)} state sync anti-patterns")

    # TS-specific: Context provider nesting depth
    nesting_entries, _ = react_detector_mod.detect_context_nesting(path)
    for e in nesting_entries:
        providers_str = " → ".join(e["providers"][:5])
        results.append(
            make_finding(
                "react",
                e["file"],
                f"nesting::{e['depth']}",
                tier=3,
                confidence="medium",
                summary=f"Deep provider nesting ({e['depth']} levels): {providers_str}",
                detail={"depth": e["depth"], "providers": e["providers"]},
            )
        )
    if nesting_entries:
        log(f"         react: {len(nesting_entries)} deep provider nesting")

    # TS-specific: Hook return bloat
    hook_entries, _ = react_detector_mod.detect_hook_return_bloat(path)
    for e in hook_entries:
        results.append(
            make_finding(
                "react",
                e["file"],
                f"hook_bloat::{e['hook']}",
                tier=3,
                confidence="medium",
                summary=f"Hook return bloat: {e['hook']} returns {e['field_count']} fields",
                detail={
                    "hook": e["hook"],
                    "field_count": e["field_count"],
                    "line": e["line"],
                },
            )
        )
    if hook_entries:
        log(f"         react: {len(hook_entries)} bloated hook returns")

    # TS-specific: Boolean state explosion
    bool_entries, _ = react_detector_mod.detect_boolean_state_explosion(path)
    for e in bool_entries:
        states_str = ", ".join(e["states"][:5])
        results.append(
            make_finding(
                "react",
                e["file"],
                f"bool_state::{e['prefix']}",
                tier=3,
                confidence="low",
                summary=f"Boolean state explosion: {e['count']} boolean useState hooks ({states_str})",
                detail={
                    "count": e["count"],
                    "setters": e["setters"],
                    "states": e["states"],
                    "line": e["line"],
                },
            )
        )
    if bool_entries:
        log(f"         react: {len(bool_entries)} boolean state explosions")

    return results, {
        "smells": adjust_potential(lang.zone_map, total_smell_files),
        "react": total_effects,
    }
