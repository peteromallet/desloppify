"""Python detector phase runners and config constants."""

from __future__ import annotations

from pathlib import Path

from desloppify import state as state_mod
from desloppify.engine.detectors import complexity as complexity_detector_mod
from desloppify.engine.detectors import flat_dirs as flat_dirs_detector_mod
from desloppify.engine.detectors import gods as gods_detector_mod
from desloppify.engine.detectors import graph as graph_detector_mod
from desloppify.engine.detectors import large as large_detector_mod
from desloppify.engine.detectors import orphaned as orphaned_detector_mod
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
    make_passthrough_findings,
    make_single_use_findings,
    make_unused_findings,
)
from desloppify.languages.python.detectors import (
    coupling_contracts as coupling_contracts_detector_mod,
)
from desloppify.languages.python.detectors import deps as deps_detector_mod
from desloppify.languages.python.detectors import facade as facade_detector_mod
from desloppify.languages.python.detectors import (
    responsibility_cohesion as cohesion_detector_mod,
)
from desloppify.languages.python.detectors import unused as unused_detector_mod
from desloppify.languages.python.detectors.complexity import (
    compute_long_functions,
    compute_max_params,
    compute_nesting_depth,
)
from desloppify.languages.python.extractors import detect_passthrough_functions
from desloppify.languages.python.extractors_classes import extract_py_classes
from desloppify.languages.python.phases_quality import (
    phase_dict_keys as _phase_dict_keys,
)
from desloppify.languages.python.phases_quality import (
    phase_layer_violation as _phase_layer_violation,
)
from desloppify.languages.python.phases_quality import (
    phase_mutable_state as _phase_mutable_state,
)
from desloppify.languages.python.phases_quality import phase_smells as _phase_smells
from desloppify.utils import log

# ── Config data (single source of truth) ──────────────────


PY_COMPLEXITY_SIGNALS = [
    ComplexitySignal("imports", r"^(?:import |from )", weight=1, threshold=20),
    ComplexitySignal(
        "many_params", None, weight=2, threshold=7, compute=compute_max_params
    ),
    ComplexitySignal(
        "deep_nesting", None, weight=3, threshold=4, compute=compute_nesting_depth
    ),
    ComplexitySignal(
        "long_functions", None, weight=1, threshold=80, compute=compute_long_functions
    ),
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


def _phase_unused(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    entries, total_files = unused_detector_mod.detect_unused(path)
    return make_unused_findings(entries, log), {
        "unused": adjust_potential(lang.zone_map, total_files),
    }


def _phase_structural(
    path: Path, lang: LangConfig
) -> tuple[list[dict], dict[str, int]]:
    """Merge large + complexity + god classes into structural findings."""
    structural: dict[str, dict] = {}

    large_entries, file_count = large_detector_mod.detect_large_files(
        path, file_finder=lang.file_finder, threshold=lang.large_threshold
    )
    for e in large_entries:
        add_structural_signal(
            structural, e["file"], f"large ({e['loc']} LOC)", {"loc": e["loc"]}
        )

    complexity_entries, _ = complexity_detector_mod.detect_complexity(
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
        lang.complexity_map[e["file"]] = e["score"]

    god_entries, _ = gods_detector_mod.detect_gods(
        extract_py_classes(path), PY_GOD_RULES
    )
    for e in god_entries:
        add_structural_signal(structural, e["file"], e["signal_text"], e["detail"])

    results = merge_structural_signals(structural, log)

    # Flat directories
    flat_entries, dir_count = flat_dirs_detector_mod.detect_flat_dirs(
        path, file_finder=lang.file_finder
    )
    for e in flat_entries:
        results.append(
            state_mod.make_finding(
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
    results.extend(
        make_passthrough_findings(pt_entries, "function", "total_params", log)
    )

    potentials = {
        "structural": adjust_potential(lang.zone_map, file_count),
        "flat_dirs": dir_count,
        "props": len(pt_entries) if pt_entries else 0,
    }
    return results, potentials


def _phase_coupling(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    graph = deps_detector_mod.build_dep_graph(path)
    lang.dep_graph = graph
    zm = lang.zone_map

    single_entries, single_candidates = (
        single_use_detector_mod.detect_single_use_abstractions(
            path, graph, barrel_names=lang.barrel_names
        )
    )
    single_entries = filter_entries(zm, single_entries, "single_use")
    results = make_single_use_findings(
        single_entries, lang.get_area, skip_dir_names={"commands"}, stderr_fn=log
    )

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
        ),
    )
    orphan_entries = filter_entries(zm, orphan_entries, "orphaned")
    results.extend(make_orphaned_findings(orphan_entries, log))

    facade_entries, _ = facade_detector_mod.detect_reexport_facades(graph)
    facade_entries = filter_entries(zm, facade_entries, "facade")
    results.extend(make_facade_findings(facade_entries, log))

    mixin_entries, coupling_candidates = (
        coupling_contracts_detector_mod.detect_implicit_mixin_contracts(path)
    )
    mixin_entries = filter_entries(zm, mixin_entries, "coupling")
    for entry in mixin_entries:
        attr_preview = ", ".join(entry["required_attrs"][:4])
        if len(entry["required_attrs"]) > 4:
            attr_preview += f", +{len(entry['required_attrs']) - 4} more"
        req_count = entry["required_count"]
        tier = 4 if req_count >= 6 else 3
        confidence = "high" if req_count >= 6 else "medium"
        results.append(
            state_mod.make_finding(
                "coupling",
                entry["file"],
                entry["class"],
                tier=tier,
                confidence=confidence,
                summary=(
                    f"Implicit host contract: {entry['class']} depends on {req_count} "
                    f"undeclared self attrs ({attr_preview})"
                ),
                detail={
                    "subtype": "implicit_mixin_contract",
                    "required_attrs": entry["required_attrs"],
                    "required_count": req_count,
                    "line": entry.get("line"),
                },
            )
        )

    log(f"         -> {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": adjust_potential(zm, single_candidates),
        "cycles": adjust_potential(zm, total_graph_files),
        "orphaned": adjust_potential(zm, total_graph_files),
        "facade": adjust_potential(zm, total_graph_files),
        "coupling": adjust_potential(zm, coupling_candidates),
    }
    return results, potentials


def _phase_responsibility_cohesion(
    path: Path, lang: LangConfig
) -> tuple[list[dict], dict[str, int]]:
    entries, candidates = cohesion_detector_mod.detect_responsibility_cohesion(path)
    entries = filter_entries(lang.zone_map, entries, "responsibility_cohesion")

    results: list[dict] = []
    for entry in entries:
        comp_sizes = ", ".join(str(size) for size in entry["component_sizes"][:5])
        if len(entry["component_sizes"]) > 5:
            comp_sizes += f", +{len(entry['component_sizes']) - 5} more"
        results.append(
            state_mod.make_finding(
                "responsibility_cohesion",
                entry["file"],
                "",
                tier=3,
                confidence="medium",
                summary=(
                    f"Mixed responsibilities: {entry['function_count']} top-level funcs "
                    f"across {entry['component_count']} disconnected clusters "
                    f"({comp_sizes})"
                ),
                detail={
                    "loc": entry["loc"],
                    "function_count": entry["function_count"],
                    "component_count": entry["component_count"],
                    "component_sizes": entry["component_sizes"],
                    "family_count": entry["family_count"],
                    "import_cluster_count": entry["import_cluster_count"],
                    "families": entry["families"],
                },
            )
        )

    if results:
        log(f"         responsibility cohesion: {len(results)} modules")
    return results, {
        "responsibility_cohesion": adjust_potential(lang.zone_map, candidates)
    }

__all__ = [
    "PY_COMPLEXITY_SIGNALS",
    "PY_ENTRY_PATTERNS",
    "PY_GOD_RULES",
    "PY_SKIP_NAMES",
    "_phase_coupling",
    "_phase_dict_keys",
    "_phase_layer_violation",
    "_phase_mutable_state",
    "_phase_responsibility_cohesion",
    "_phase_smells",
    "_phase_structural",
    "_phase_unused",
]
