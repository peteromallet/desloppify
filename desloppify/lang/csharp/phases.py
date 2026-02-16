"""C# detector phase runners."""

from __future__ import annotations

import re
from pathlib import Path

from ..base import (
    LangConfig,
    add_structural_signal,
    merge_structural_signals,
    make_cycle_findings,
    make_orphaned_findings,
    make_single_use_findings,
)
from ...detectors.base import ComplexitySignal, GodRule
from ...state import make_finding
from ...utils import log, rel
from ...zones import adjust_potential, filter_entries


def _compute_max_nesting(content: str, _lines: list[str]):
    depth = 0
    max_depth = 0
    for ch in content:
        if ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth = max(0, depth - 1)
    if max_depth > 8:
        return max_depth, f"nesting depth {max_depth}"
    return None


def _compute_method_count(content: str, _lines: list[str]):
    count = len(
        re.findall(
            r"(?m)^[ \t]*(?:(?:public|private|protected|internal|static|virtual|override|abstract|"
            r"sealed|partial|async|extern|unsafe|new|required)\s+)+"
            r"(?:[\w<>\[\],\.\?]+\s+)+[A-Za-z_]\w*\s*\(",
            content,
        )
    )
    if count > 20:
        return count, f"{count} methods"
    return None


def _compute_long_methods(content: str, _lines: list[str]):
    # Heuristic: count methods with >= 60 logical lines.
    blocks = re.findall(
        r"(?ms)^[ \t]*(?:(?:public|private|protected|internal|static|virtual|override|abstract|"
        r"sealed|partial|async|extern|unsafe|new|required)\s+)+"
        r"(?:[\w<>\[\],\.\?]+\s+)+[A-Za-z_]\w*\s*\([^)]*\)\s*\{(.*?)^\s*\}",
        content,
    )
    long_count = 0
    for body in blocks:
        logical = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("//")]
        if len(logical) >= 60:
            long_count += 1
    if long_count > 0:
        return long_count, f"{long_count} long methods"
    return None


CSHARP_COMPLEXITY_SIGNALS = [
    ComplexitySignal("imports", r"(?m)^\s*(?:global\s+)?using\s+", weight=1, threshold=20),
    ComplexitySignal("TODOs", r"(?m)//\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
    ComplexitySignal("many classes", r"(?m)^\s*(?:public\s+)?(?:class|record|struct)\s+\w+", weight=2, threshold=5),
    ComplexitySignal("deep nesting", None, weight=2, threshold=0, compute=_compute_max_nesting),
    ComplexitySignal("many methods", None, weight=2, threshold=0, compute=_compute_method_count),
    ComplexitySignal("long methods", None, weight=2, threshold=0, compute=_compute_long_methods),
]

CSHARP_GOD_RULES = [
    GodRule("methods", "methods", lambda c: len(c.methods), 15),
    GodRule("attributes", "attributes", lambda c: len(c.attributes), 10),
    GodRule("base_classes", "base classes/interfaces", lambda c: len(c.base_classes), 4),
    GodRule("long_methods", "long methods (>50 LOC)", lambda c: sum(1 for m in c.methods if m.loc > 50), 2),
]


def _runtime_setting(lang: LangConfig, key: str, default: int) -> int:
    """Read language setting from runtime context."""
    getter = getattr(lang, "runtime_setting", None)
    if callable(getter):
        try:
            return int(getter(key, default))
        except (TypeError, ValueError):
            return default
    return default


def _corroboration_signals_for_csharp(entry: dict, lang: LangConfig) -> tuple[list[str], int, int]:
    """Return corroboration signals plus complexity/import counts for confidence gating."""
    filepath = entry.get("file", "")
    loc = entry.get("loc", 0)
    import_count = entry.get("import_count", 0)
    fanout_threshold = max(1, _runtime_setting(lang, "high_fanout_threshold", 5))
    complexity_score = lang._complexity_map.get(filepath, 0)
    if complexity_score == 0 and filepath:
        complexity_score = lang._complexity_map.get(rel(filepath), 0)

    signals: list[str] = []
    if loc >= lang.large_threshold:
        signals.append(f"large ({loc} LOC)")
    if complexity_score >= lang.complexity_threshold:
        signals.append(f"complexity ({complexity_score})")
    if import_count >= fanout_threshold:
        signals.append(f"high fan-out ({import_count} imports)")
    return signals, complexity_score, import_count


def _apply_csharp_actionability_gates(findings: list[dict], entries: list[dict], lang: LangConfig) -> None:
    """Downgrade actionability unless multiple independent signals corroborate."""
    min_signals = max(1, _runtime_setting(lang, "corroboration_min_signals", 2))
    entries_by_file = {rel(e["file"]): e for e in entries}
    for finding in findings:
        entry = entries_by_file.get(finding.get("file", ""))
        if not entry:
            continue
        signals, complexity_score, import_count = _corroboration_signals_for_csharp(entry, lang)
        corroboration_count = len(signals)
        finding["confidence"] = "medium" if corroboration_count >= min_signals else "low"
        detail = finding.setdefault("detail", {})
        detail["corroboration_signals"] = signals
        detail["corroboration_count"] = corroboration_count
        detail["corroboration_min_required"] = min_signals
        detail["complexity_score"] = complexity_score
        detail["import_count"] = import_count


def _phase_structural(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    """Merge large + complexity + god classes into structural findings."""
    from ...detectors.complexity import detect_complexity
    from ...detectors.flat_dirs import detect_flat_dirs
    from ...detectors.gods import detect_gods
    from ...detectors.large import detect_large_files
    from .extractors import extract_csharp_classes

    structural: dict[str, dict] = {}

    large_entries, file_count = detect_large_files(
        path, file_finder=lang.file_finder, threshold=lang.large_threshold
    )
    for e in large_entries:
        add_structural_signal(structural, e["file"], f"large ({e['loc']} LOC)", {"loc": e["loc"]})

    complexity_entries, _ = detect_complexity(
        path,
        signals=CSHARP_COMPLEXITY_SIGNALS,
        file_finder=lang.file_finder,
        threshold=lang.complexity_threshold,
        min_loc=40,
    )
    for e in complexity_entries:
        add_structural_signal(
            structural,
            e["file"],
            f"complexity score {e['score']}",
            {"complexity_score": e["score"], "complexity_signals": e["signals"]},
        )
        lang._complexity_map[e["file"]] = e["score"]

    god_entries, _ = detect_gods(extract_csharp_classes(path), CSHARP_GOD_RULES, min_reasons=2)
    for e in god_entries:
        add_structural_signal(structural, e["file"], e["signal_text"], e["detail"])

    results = merge_structural_signals(structural, log)

    flat_entries, dir_count = detect_flat_dirs(path, file_finder=lang.file_finder)
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

    potentials = {
        "structural": adjust_potential(lang._zone_map, file_count),
        "flat_dirs": dir_count,
    }
    return results, potentials


def _phase_coupling(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    """Run coupling-oriented detectors on the C# dependency graph."""
    from ...detectors.graph import detect_cycles
    from ...detectors.orphaned import detect_orphaned_files
    from ...detectors.single_use import detect_single_use_abstractions
    from .detectors.deps import build_dep_graph

    runtime_option = getattr(lang, "runtime_option", None)
    roslyn_cmd = runtime_option("roslyn_cmd", "") if callable(runtime_option) else ""
    graph = build_dep_graph(path, roslyn_cmd=(roslyn_cmd or None))
    lang._dep_graph = graph
    zm = lang._zone_map

    results: list[dict] = []

    single_entries, single_candidates = detect_single_use_abstractions(
        path, graph, barrel_names=lang.barrel_names
    )
    single_entries = filter_entries(zm, single_entries, "single_use")
    single_findings = make_single_use_findings(single_entries, lang.get_area, stderr_fn=log)
    _apply_csharp_actionability_gates(single_findings, single_entries, lang)
    results.extend(single_findings)

    cycle_entries, _ = detect_cycles(graph)
    cycle_entries = filter_entries(zm, cycle_entries, "cycles", file_key="files")
    results.extend(make_cycle_findings(cycle_entries, log))

    orphan_entries, total_graph_files = detect_orphaned_files(
        path,
        graph,
        extensions=lang.extensions,
        extra_entry_patterns=lang.entry_patterns,
        extra_barrel_names=lang.barrel_names,
    )
    orphan_entries = filter_entries(zm, orphan_entries, "orphaned")
    orphan_findings = make_orphaned_findings(orphan_entries, log)
    _apply_csharp_actionability_gates(orphan_findings, orphan_entries, lang)
    results.extend(orphan_findings)

    log(f"         -> {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": adjust_potential(zm, single_candidates),
        "cycles": adjust_potential(zm, total_graph_files),
        "orphaned": adjust_potential(zm, total_graph_files),
    }
    return results, potentials
