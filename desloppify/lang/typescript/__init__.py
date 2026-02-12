"""TypeScript/React language configuration for desloppify."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .. import register_lang
from ..base import (BoundaryRule, DetectorPhase, FixerConfig, LangConfig,
                    add_structural_signal, merge_structural_signals,
                    make_single_use_findings, make_cycle_findings,
                    make_orphaned_findings, make_smell_findings,
                    make_facade_findings, phase_dupes)
from ...detectors.base import ComplexitySignal, GodRule
from ...state import make_finding
from ...utils import find_ts_files, get_area, log, rel


def _compute_ts_destructure_props(content, lines):
    long_destructures = re.findall(r"\{\s*(\w+(?:\s*,\s*\w+){8,})\s*\}", content)
    if not long_destructures:
        return None
    max_props = max(len(d.split(",")) for d in long_destructures)
    return max_props, f"destructure w/{max_props} props"


def _compute_ts_inline_types(content, lines):
    inline_types = len(re.findall(
        r"^(?:export\s+)?(?:type|interface)\s+\w+", content, re.MULTILINE))
    if inline_types > 3:
        return inline_types, f"{inline_types} inline types"
    return None


# ── Config data (single source of truth) ──────────────────


TS_COMPLEXITY_SIGNALS = [
    ComplexitySignal("imports", r"^import\s", weight=1, threshold=15),
    ComplexitySignal("destructured props", None, weight=1, threshold=8,
                     compute=_compute_ts_destructure_props),
    ComplexitySignal("useEffects", r"useEffect\s*\(", weight=3, threshold=3),
    ComplexitySignal("inline types", None, weight=1, threshold=3,
                     compute=_compute_ts_inline_types),
    ComplexitySignal("TODOs", r"//\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
    ComplexitySignal("nested ternaries", r"[^?]\?[^?.:\n][^:\n]*[^?]\?[^?.]",
                     weight=3, threshold=2),
]

TS_GOD_RULES = [
    GodRule("context_hooks", "context hooks", lambda c: c.metrics.get("context_hooks", 0), 3),
    GodRule("use_effects", "useEffects", lambda c: c.metrics.get("use_effects", 0), 4),
    GodRule("use_states", "useStates", lambda c: c.metrics.get("use_states", 0), 5),
    GodRule("custom_hooks", "custom hooks", lambda c: c.metrics.get("custom_hooks", 0), 8),
    GodRule("hook_total", "total hooks", lambda c: c.metrics.get("hook_total", 0), 10),
]

TS_SKIP_NAMES = {
    "index.ts", "index.tsx", "types.ts", "types.tsx",
    "constants.ts", "constants.tsx", "utils.ts", "utils.tsx",
    "helpers.ts", "helpers.tsx", "settings.ts", "settings.tsx",
    "main.ts", "main.tsx", "App.tsx", "vite-env.d.ts",
}

TS_SKIP_DIRS = {"src/shared/components/ui"}


# ── Phase runners ──────────────────────────────────────────


def _phase_logs(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.logs import detect_logs
    log_entries, total_files = detect_logs(path)
    log_groups: dict[tuple, list] = defaultdict(list)
    for e in log_entries:
        log_groups[(e["file"], e["tag"])].append(e)
    results = []
    for (file, tag), entries in log_groups.items():
        results.append(make_finding(
            "logs", file, tag,
            tier=1, confidence="high",
            summary=f"{len(entries)} tagged logs [{tag}]",
            detail={"count": len(entries), "lines": [e["line"] for e in entries[:20]]},
        ))
    log(f"         {len(log_entries)} instances → {len(results)} findings")
    return results, {"logs": total_files}


def _phase_unused(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.unused import detect_unused
    from ..base import make_unused_findings
    entries, total_files = detect_unused(path)
    return make_unused_findings(entries, log), {"unused": total_files}


def _phase_exports(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.exports import detect_dead_exports
    export_entries, total_exports = detect_dead_exports(path)
    results = []
    for e in export_entries:
        results.append(make_finding(
            "exports", e["file"], e["name"],
            tier=2, confidence="high",
            summary=f"Dead export: {e['name']}",
            detail={"line": e.get("line"), "kind": e.get("kind")},
        ))
    log(f"         {len(export_entries)} instances → {len(results)} findings")
    return results, {"exports": total_exports}


def _phase_deprecated(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.deprecated import detect_deprecated
    dep_entries, total_deprecated = detect_deprecated(path)
    results = []
    for e in dep_entries:
        if e["kind"] == "property":
            continue
        tier = 1 if e["importers"] == 0 else 3
        results.append(make_finding(
            "deprecated", e["file"], e["symbol"],
            tier=tier, confidence="high",
            summary=f"Deprecated: {e['symbol']} ({e['importers']} importers)"
                    + (" → safe to delete" if e["importers"] == 0 else ""),
            detail={"importers": e["importers"], "line": e["line"]},
        ))
    log(f"         {len(dep_entries)} instances → {len(results)} findings (properties suppressed)")
    return results, {"deprecated": total_deprecated}


def _phase_structural(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from ...detectors.large import detect_large_files
    from ...detectors.complexity import detect_complexity
    from ...detectors.gods import detect_gods
    from ...detectors.flat_dirs import detect_flat_dirs
    from .extractors import extract_ts_components, detect_passthrough_components
    from .detectors.concerns import detect_mixed_concerns
    from .detectors.props import detect_prop_interface_bloat

    structural: dict[str, dict] = {}

    large_entries, file_count = detect_large_files(path, file_finder=lang.file_finder)
    for e in large_entries:
        add_structural_signal(structural, e["file"], f"large ({e['loc']} LOC)",
                              {"loc": e["loc"]})

    complexity_entries, _ = detect_complexity(path, signals=TS_COMPLEXITY_SIGNALS,
                                              file_finder=lang.file_finder)
    for e in complexity_entries:
        add_structural_signal(structural, e["file"], f"complexity score {e['score']}",
                              {"complexity_score": e["score"], "complexity_signals": e["signals"]})

    god_entries, _ = detect_gods(extract_ts_components(path), TS_GOD_RULES, min_reasons=2)
    for e in god_entries:
        add_structural_signal(structural, e["file"],
                              f"{e['detail'].get('hook_total', 0)} hooks ({', '.join(e['reasons'][:2])})",
                              {"hook_total": e["detail"].get("hook_total", 0), "hook_reasons": e["reasons"]})

    concern_entries, _ = detect_mixed_concerns(path)
    for e in concern_entries:
        add_structural_signal(structural, e["file"],
                              f"mixed: {', '.join(e['concerns'][:3])}",
                              {"concerns": e["concerns"]})

    results = merge_structural_signals(structural, log)

    # Flat directories (too many files → missing sub-organization)
    flat_entries, dir_count = detect_flat_dirs(path, file_finder=lang.file_finder)
    for e in flat_entries:
        results.append(make_finding(
            "flat_dirs", e["directory"], "",
            tier=3, confidence="medium",
            summary=f"Flat directory: {e['file_count']} files — consider grouping by domain",
            detail={"file_count": e["file_count"]},
        ))
    if flat_entries:
        log(f"         flat dirs: {len(flat_entries)} directories with 20+ files")

    # TS-specific: props bloat
    prop_entries, prop_count = detect_prop_interface_bloat(path)
    for e in prop_entries:
        results.append(make_finding(
            "props", e["file"], e["interface"],
            tier=3, confidence="medium",
            summary=f"Bloated props: {e['interface']} ({e['prop_count']} props)",
            detail={"prop_count": e["prop_count"], "line": e["line"]},
        ))

    # TS-specific: passthrough components
    pt_entries = detect_passthrough_components(path)
    for e in pt_entries:
        results.append(make_finding(
            "props", e["file"], f"passthrough::{e['component']}",
            tier=e["tier"], confidence=e["confidence"],
            summary=f"Passthrough component: {e['component']} "
                    f"({e['passthrough']}/{e['total_props']} props forwarded, {e['ratio']:.0%})",
            detail={
                "passthrough": e["passthrough"], "total_props": e["total_props"],
                "ratio": e["ratio"], "line": e["line"],
                "passthrough_props": e["passthrough_props"],
                "direct_props": e["direct_props"],
            },
        ))
    potentials = {
        "structural": file_count,
        "flat_dirs": dir_count,
        "props": max(prop_count, len(pt_entries)) if prop_count else len(pt_entries),
    }
    return results, potentials


def _make_boundary_findings(
    single_entries: list[dict], path: Path, graph: dict,
    lang: LangConfig, shared_prefix: str, tools_prefix: str,
) -> tuple[list[dict], int]:
    """Create boundary-candidate findings, deduplicated against single-use."""
    from ...detectors.coupling import detect_boundary_candidates

    single_use_emitted = set()
    for e in single_entries:
        is_size_ok = 50 <= e["loc"] <= 200
        is_colocated = lang.get_area and (
            lang.get_area(rel(e["file"])) == lang.get_area(e["sole_importer"]))
        if not is_size_ok and not is_colocated:
            single_use_emitted.add(rel(e["file"]))

    results = []
    deduped = 0
    boundary_entries, total_shared = detect_boundary_candidates(
        path, graph, shared_prefix=shared_prefix, tools_prefix=tools_prefix)
    for e in boundary_entries:
        if rel(e["file"]) in single_use_emitted:
            deduped += 1
            continue
        results.append(make_finding(
            "coupling", e["file"], f"boundary::{e['sole_tool']}",
            tier=3, confidence="medium",
            summary=f"Boundary candidate ({e['loc']} LOC): only used by {e['sole_tool']} "
                    f"({e['importer_count']} importers)",
            detail={"sole_tool": e["sole_tool"], "importer_count": e["importer_count"],
                    "loc": e["loc"]},
        ))
    if deduped:
        log(f"         ({deduped} boundary candidates skipped — covered by single_use)")
    return results, total_shared


def _phase_coupling(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from ...detectors.single_use import detect_single_use_abstractions
    from ...detectors.graph import detect_cycles
    from ...detectors.coupling import detect_coupling_violations, detect_cross_tool_imports
    from ...detectors.orphaned import detect_orphaned_files
    from ...detectors.naming import detect_naming_inconsistencies
    from ...utils import SRC_PATH
    from .detectors.deps import build_dep_graph, build_dynamic_import_targets, ts_alias_resolver
    from .detectors.patterns import detect_pattern_anomalies

    results = []
    graph = build_dep_graph(path)

    # Single-use (shared helper)
    single_entries, single_candidates = detect_single_use_abstractions(
        path, graph, barrel_names=lang.barrel_names)
    results.extend(make_single_use_findings(single_entries, lang.get_area,
                                             skip_dir_names={"commands"}, stderr_fn=log))
    shared_prefix = f"{SRC_PATH}/shared/"
    tools_prefix = f"{SRC_PATH}/tools/"
    coupling_entries, coupling_edges = detect_coupling_violations(
        path, graph, shared_prefix=shared_prefix, tools_prefix=tools_prefix)
    for e in coupling_entries:
        results.append(make_finding(
            "coupling", e["file"], e["target"],
            tier=2, confidence="high",
            summary=f"Backwards coupling: shared imports {e['target']} (tool: {e['tool']})",
            detail={"target": e["target"], "tool": e["tool"], "direction": e["direction"]},
        ))

    # TS-specific: boundary candidates (deduplicated against single-use)
    boundary_findings, _ = _make_boundary_findings(
        single_entries, path, graph, lang, shared_prefix, tools_prefix)
    results.extend(boundary_findings)

    # TS-specific: cross-tool imports
    cross_tool, cross_edges = detect_cross_tool_imports(
        path, graph, tools_prefix=tools_prefix)
    for e in cross_tool:
        results.append(make_finding(
            "coupling", e["file"], e["target"],
            tier=2, confidence="high",
            summary=f"Cross-tool import: {e['source_tool']}→{e['target_tool']} ({e['target']})",
            detail={"target": e["target"], "source_tool": e["source_tool"],
                    "target_tool": e["target_tool"], "direction": e["direction"]},
        ))
    if cross_tool:
        log(f"         cross-tool: {len(cross_tool)} imports")

    # Cycles + orphaned (shared helpers)
    cycle_entries, _ = detect_cycles(graph)
    results.extend(make_cycle_findings(cycle_entries, log))
    orphan_entries, total_graph_files = detect_orphaned_files(
        path, graph, extensions=lang.extensions,
        extra_entry_patterns=lang.entry_patterns,
        extra_barrel_names=lang.barrel_names,
        dynamic_import_finder=build_dynamic_import_targets,
        alias_resolver=ts_alias_resolver)
    results.extend(make_orphaned_findings(orphan_entries, log))

    # Re-export facades (shared detector)
    from ...detectors.facade import detect_reexport_facades
    facade_entries, _ = detect_reexport_facades(graph, lang="typescript")
    results.extend(make_facade_findings(facade_entries, log))

    # TS-specific: pattern consistency
    pattern_entries, total_areas = detect_pattern_anomalies(path)
    for e in pattern_entries:
        results.append(make_finding(
            "patterns", e["area"], e["family"],
            tier=3, confidence=e.get("confidence", "low"),
            summary=f"Competing patterns ({e['family']}): {e['review'][:120]}",
            detail={"family": e["family"], "patterns_used": e["patterns_used"],
                    "pattern_count": e["pattern_count"], "review": e["review"]},
        ))

    # TS-specific: naming consistency
    naming_entries, total_dirs = detect_naming_inconsistencies(
            path, file_finder=lang.file_finder,
            skip_names=TS_SKIP_NAMES, skip_dirs=TS_SKIP_DIRS)
    for e in naming_entries:
        results.append(make_finding(
            "naming", e["directory"], e["minority"],
            tier=3, confidence="low",
            summary=f"Naming inconsistency: {e['minority_count']} {e['minority']} files "
                    f"in {e['majority']}-majority dir ({e['total_files']} total)",
            detail={"majority": e["majority"], "majority_count": e["majority_count"],
                    "minority": e["minority"], "minority_count": e["minority_count"],
                    "outliers": e["outliers"]},
        ))
    log(f"         → {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": single_candidates,
        "coupling": coupling_edges + cross_edges,
        "cycles": total_graph_files,
        "orphaned": total_graph_files,
        "patterns": total_areas,
        "naming": total_dirs,
        "facade": total_graph_files,
    }
    return results, potentials


def _phase_smells(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.smells import detect_smells
    smell_entries, total_smell_files = detect_smells(path)
    results = make_smell_findings(smell_entries, log)

    # TS-specific: React state sync anti-patterns
    from .detectors.react import detect_state_sync
    react_entries, total_effects = detect_state_sync(path)
    for e in react_entries:
        setter_str = ", ".join(e["setters"])
        results.append(make_finding(
            "react", e["file"], setter_str,
            tier=3, confidence="medium",
            summary=f"State sync anti-pattern: useEffect only calls {setter_str}",
            detail={"line": e["line"], "setters": e["setters"]},
        ))
    if react_entries:
        log(f"         react: {len(react_entries)} state sync anti-patterns")
    return results, {"smells": total_smell_files, "react": total_effects}


def _get_ts_fixers() -> dict[str, FixerConfig]:
    """Build the TypeScript fixer registry (lazy-loaded)."""
    return {
        "unused-imports": FixerConfig(
            label="unused imports",
            detect=lambda path: __import__("desloppify.lang.typescript.detectors.unused", fromlist=["detect_unused"]).detect_unused(path, category="imports")[0],
            fix=lambda entries, **kw: __import__("desloppify.lang.typescript.fixers", fromlist=["fix_unused_imports"]).fix_unused_imports(entries, **kw),
            detector="unused",
            verb="Removed", dry_verb="Would remove",
        ),
    }


# ── Build the config ──────────────────────────────────────


def _ts_build_dep_graph(path: Path) -> dict:
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _ts_extract_functions(path: Path) -> list:
    """Extract all TS functions for duplicate detection."""
    from .extractors import extract_ts_functions
    functions = []
    for filepath in find_ts_files(path):
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        functions.extend(extract_ts_functions(filepath))
    return functions


@register_lang("typescript")
class TypeScriptConfig(LangConfig):
    def __init__(self):
        from .commands import get_detect_commands
        super().__init__(
            name="typescript",
            extensions=[".ts", ".tsx"],
            exclusions=["node_modules", ".d.ts"],
            default_src="src",
            build_dep_graph=_ts_build_dep_graph,
            entry_patterns=[
                "/pages/", "/main.tsx", "/main.ts", "/App.tsx",
                "vite.config", "tailwind.config", "postcss.config",
                ".d.ts", "/settings.ts", "/__tests__/", ".test.", ".spec.", ".stories.",
            ],
            barrel_names={"index.ts", "index.tsx"},
            phases=[
                DetectorPhase("Logs", _phase_logs),
                DetectorPhase("Unused (tsc)", _phase_unused),
                DetectorPhase("Dead exports", _phase_exports),
                DetectorPhase("Deprecated", _phase_deprecated),
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Coupling + single-use + patterns + naming", _phase_coupling),
                DetectorPhase("Code smells", _phase_smells),
                DetectorPhase("Duplicates", phase_dupes, slow=True),
            ],
            fixers=_get_ts_fixers(),
            get_area=get_area,
            detect_commands=get_detect_commands(),
            boundaries=[
                BoundaryRule("shared/", "tools/", "shared→tools"),
            ],
            typecheck_cmd="npx tsc --noEmit",
            file_finder=find_ts_files,
            large_threshold=500,
            complexity_threshold=15,
            extract_functions=_ts_extract_functions,
        )
