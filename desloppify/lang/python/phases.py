"""Python detector phase runners and config constants."""

from __future__ import annotations

from pathlib import Path

from ..base import (
    LangConfig,
    add_structural_signal,
    merge_structural_signals,
    make_cycle_findings,
    make_facade_findings,
    make_orphaned_findings,
    make_passthrough_findings,
    make_single_use_findings,
    make_smell_findings,
)
from ...detectors.base import ComplexitySignal, GodRule
from ...utils import log
from ...zones import adjust_potential, filter_entries

from .detectors.complexity import (
    compute_long_functions,
    compute_max_params,
    compute_nesting_depth,
)


# ── Config data (single source of truth) ──────────────────


PY_COMPLEXITY_SIGNALS = [
    ComplexitySignal("imports", r"^(?:import |from )", weight=1, threshold=20),
    ComplexitySignal("many_params", None, weight=2, threshold=7, compute=compute_max_params),
    ComplexitySignal("deep_nesting", None, weight=3, threshold=4, compute=compute_nesting_depth),
    ComplexitySignal("long_functions", None, weight=1, threshold=80, compute=compute_long_functions),
    ComplexitySignal("many_classes", r"^class\s+\w+", weight=3, threshold=3),
    ComplexitySignal(
        "nested_comprehensions",
        r"\[[^\]]*\bfor\b[^\]]*\bfor\b[^\]]*\]|\{[^}]*\bfor\b[^}]*\bfor\b[^}]*\}",
        weight=2,
        threshold=2,
    ),
    ComplexitySignal("TODOs", r"#\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
]

PY_GOD_RULES = [
    GodRule("methods", "methods", lambda c: len(c.methods), 15),
    GodRule("attributes", "attributes", lambda c: len(c.attributes), 10),
    GodRule("base_classes", "base classes", lambda c: len(c.base_classes), 3),
    GodRule(
        "long_methods",
        "long methods (>50 LOC)",
        lambda c: sum(1 for m in c.methods if m.loc > 50),
        1,
    ),
]

PY_SKIP_NAMES = {
    "__init__.py",
    "conftest.py",
    "setup.py",
    "manage.py",
    "__main__.py",
    "wsgi.py",
    "asgi.py",
}

PY_ENTRY_PATTERNS = [
    "__main__.py",
    "conftest.py",
    "manage.py",
    "setup.py",
    "setup.cfg",
    "test_",
    "_test.py",
    ".test.",
    "/tests/",
    "/test/",
    "/migrations/",
    "settings.py",
    "config.py",
    "wsgi.py",
    "asgi.py",
    "cli.py",  # CLI entry points (loaded via framework/importlib)
    "/commands/",  # CLI subcommands (loaded dynamically)
    "/fixers/",  # Fixer modules (loaded dynamically)
    "/lang/",  # Language modules (loaded dynamically)
    "/extractors/",  # Extractor modules (loaded dynamically)
    "__init__.py",  # Package init files (barrels, not orphans)
]


# ── Phase runners ──────────────────────────────────────────


def _phase_unused(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.unused import detect_unused
    from ..base import make_unused_findings

    entries, total_files = detect_unused(path)
    return make_unused_findings(entries, log), {
        "unused": adjust_potential(lang._zone_map, total_files),
    }


def _phase_structural(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    """Merge large + complexity + god classes into structural findings."""
    from ...detectors.complexity import detect_complexity
    from ...detectors.flat_dirs import detect_flat_dirs
    from ...detectors.gods import detect_gods
    from ...detectors.large import detect_large_files
    from ...state import make_finding
    from .extractors import detect_passthrough_functions, extract_py_classes

    structural: dict[str, dict] = {}

    large_entries, file_count = detect_large_files(
        path, file_finder=lang.file_finder, threshold=lang.large_threshold
    )
    for e in large_entries:
        add_structural_signal(structural, e["file"], f"large ({e['loc']} LOC)", {"loc": e["loc"]})

    complexity_entries, _ = detect_complexity(
        path,
        signals=PY_COMPLEXITY_SIGNALS,
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
        lang._complexity_map[e["file"]] = e["score"]

    god_entries, _ = detect_gods(extract_py_classes(path), PY_GOD_RULES)
    for e in god_entries:
        add_structural_signal(structural, e["file"], e["signal_text"], e["detail"])

    results = merge_structural_signals(structural, log)

    # Flat directories
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

    # Passthrough functions
    pt_entries = detect_passthrough_functions(path)
    results.extend(make_passthrough_findings(pt_entries, "function", "total_params", log))

    potentials = {
        "structural": adjust_potential(lang._zone_map, file_count),
        "flat_dirs": dir_count,
        "props": len(pt_entries) if pt_entries else 0,
    }
    return results, potentials


def _phase_coupling(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.deps import build_dep_graph
    from .detectors.facade import detect_reexport_facades
    from ...detectors.graph import detect_cycles
    from ...detectors.orphaned import detect_orphaned_files
    from ...detectors.single_use import detect_single_use_abstractions

    graph = build_dep_graph(path)
    lang._dep_graph = graph
    zm = lang._zone_map

    single_entries, single_candidates = detect_single_use_abstractions(
        path, graph, barrel_names=lang.barrel_names
    )
    single_entries = filter_entries(zm, single_entries, "single_use")
    results = make_single_use_findings(
        single_entries, lang.get_area, skip_dir_names={"commands"}, stderr_fn=log
    )

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
    results.extend(make_orphaned_findings(orphan_entries, log))

    facade_entries, _ = detect_reexport_facades(graph)
    facade_entries = filter_entries(zm, facade_entries, "facade")
    results.extend(make_facade_findings(facade_entries, log))

    log(f"         -> {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": adjust_potential(zm, single_candidates),
        "cycles": adjust_potential(zm, total_graph_files),
        "orphaned": adjust_potential(zm, total_graph_files),
        "facade": adjust_potential(zm, total_graph_files),
    }
    return results, potentials


def _phase_smells(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.smells import detect_smells
    from ...detectors.signature import detect_signature_variance
    from ...state import make_finding

    entries, total_files = detect_smells(path)
    results = make_smell_findings(entries, log)

    # Cross-file: signature variance
    functions = lang.extract_functions(path) if lang.extract_functions else []
    sig_entries, _ = detect_signature_variance(functions)
    for e in sig_entries:
        results.append(
            make_finding(
                "smells",
                e["files"][0],
                f"sig_variance::{e['name']}",
                tier=3,
                confidence="medium",
                summary=(
                    f"Signature variance: {e['name']}() has {e['signature_count']} "
                    f"different signatures across {e['file_count']} files"
                ),
                detail={
                    "function": e["name"],
                    "file_count": e["file_count"],
                    "signature_count": e["signature_count"],
                    "variants": e["variants"][:5],
                },
            )
        )
    if sig_entries:
        log(f"         signature variance: {len(sig_entries)} functions with inconsistent signatures")

    return results, {
        "smells": adjust_potential(lang._zone_map, total_files),
    }


def _phase_mutable_state(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.mutable_state import detect_global_mutable_config
    from ...state import make_finding

    entries, total_files = detect_global_mutable_config(path)
    results = []
    for e in entries:
        results.append(
            make_finding(
                "global_mutable_config",
                e["file"],
                e["name"],
                tier=3,
                confidence=e["confidence"],
                summary=e["summary"],
                detail={"mutation_count": e["mutation_count"], "mutation_lines": e["mutation_lines"]},
            )
        )
    if results:
        log(f"         global mutable config: {len(results)} findings")
    return results, {
        "global_mutable_config": adjust_potential(lang._zone_map, total_files),
    }


def _phase_layer_violation(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.layer_violation import detect_layer_violations
    from ...state import make_finding

    entries, total_files = detect_layer_violations(path, lang.file_finder)
    results = []
    for e in entries:
        results.append(
            make_finding(
                "layer_violation",
                e["file"],
                f"{e['source_pkg']}::{e['target_pkg']}",
                tier=2,
                confidence=e["confidence"],
                summary=e["summary"],
                detail={
                    "source_pkg": e["source_pkg"],
                    "target_pkg": e["target_pkg"],
                    "line": e["line"],
                    "description": e["description"],
                },
            )
        )
    if results:
        log(f"         layer violations: {len(results)} findings")
    return results, {"layer_violation": total_files}


def _phase_dict_keys(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.dict_keys import detect_dict_key_flow, detect_schema_drift
    from ...state import make_finding

    flow_entries, files_checked = detect_dict_key_flow(path)
    flow_entries = filter_entries(lang._zone_map, flow_entries, "dict_keys")

    results = []
    for e in flow_entries:
        results.append(
            make_finding(
                "dict_keys",
                e["file"],
                f"{e['kind']}::{e['variable']}::{e['key']}"
                if "variable" in e
                else f"{e['kind']}::{e['key']}::{e['line']}",
                tier=e["tier"],
                confidence=e["confidence"],
                summary=e["summary"],
                detail={
                    "kind": e["kind"],
                    "key": e.get("key", ""),
                    "line": e.get("line"),
                    "info": e.get("detail", ""),
                },
            )
        )

    drift_entries, _ = detect_schema_drift(path)
    drift_entries = filter_entries(lang._zone_map, drift_entries, "dict_keys")

    for e in drift_entries:
        results.append(
            make_finding(
                "dict_keys",
                e["file"],
                f"schema_drift::{e['key']}::{e['line']}",
                tier=e["tier"],
                confidence=e["confidence"],
                summary=e["summary"],
                detail={
                    "kind": "schema_drift",
                    "key": e["key"],
                    "line": e["line"],
                    "info": e.get("detail", ""),
                },
            )
        )

    log(f"         -> {len(results)} dict key findings")
    return results, {
        "dict_keys": adjust_potential(lang._zone_map, files_checked),
    }

