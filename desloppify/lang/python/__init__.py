"""Python language configuration for desloppify."""

from __future__ import annotations

from pathlib import Path

from .. import register_lang
from ..base import (DetectorPhase, LangConfig,
                    add_structural_signal, merge_structural_signals,
                    make_single_use_findings, make_cycle_findings,
                    make_orphaned_findings, make_smell_findings,
                    make_passthrough_findings, phase_dupes)
from ...detectors.base import ComplexitySignal, GodRule
from ...utils import find_py_files, log
from .detectors.complexity import compute_max_params, compute_nesting_depth, compute_long_functions


# ── Config data (single source of truth) ──────────────────


PY_COMPLEXITY_SIGNALS = [
    ComplexitySignal("imports", r"^(?:import |from )", weight=1, threshold=20),
    ComplexitySignal("many_params", None, weight=2, threshold=7, compute=compute_max_params),
    ComplexitySignal("deep_nesting", None, weight=3, threshold=4, compute=compute_nesting_depth),
    ComplexitySignal("long_functions", None, weight=1, threshold=80, compute=compute_long_functions),
    ComplexitySignal("many_classes", r"^class\s+\w+", weight=3, threshold=3),
    ComplexitySignal("nested_comprehensions",
                     r"\[.*\bfor\b.*\bfor\b.*\]|\{.*\bfor\b.*\bfor\b.*\}",
                     weight=2, threshold=2),
    ComplexitySignal("TODOs", r"#\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
]

PY_GOD_RULES = [
    GodRule("methods", "methods", lambda c: len(c.methods), 15),
    GodRule("attributes", "attributes", lambda c: len(c.attributes), 10),
    GodRule("base_classes", "base classes", lambda c: len(c.base_classes), 3),
    GodRule("long_methods", "long methods (>50 LOC)",
            lambda c: sum(1 for m in c.methods if m.loc > 50), 1),
]

PY_SKIP_NAMES = {
    "__init__.py", "conftest.py", "setup.py", "manage.py",
    "__main__.py", "wsgi.py", "asgi.py",
}

PY_ENTRY_PATTERNS = [
    "__main__.py", "conftest.py", "manage.py", "setup.py", "setup.cfg",
    "test_", "_test.py", ".test.", "/tests/", "/test/", "/migrations/",
    "settings.py", "config.py", "wsgi.py", "asgi.py",
    "cli.py",           # CLI entry points (loaded via framework/importlib)
    "/commands/",       # CLI subcommands (loaded dynamically)
    "/fixers/",         # Fixer modules (loaded dynamically)
    "/lang/",           # Language modules (loaded dynamically)
    "/extractors/",     # Extractor modules (loaded dynamically)
    "__init__.py",      # Package init files (barrels, not orphans)
]


def _get_py_area(filepath: str) -> str:
    """Derive an area name from a Python file path for grouping."""
    parts = filepath.split("/")
    if len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if parts else filepath


# ── Phase runners ──────────────────────────────────────────


def _phase_unused(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.unused import detect_unused
    from ..base import make_unused_findings
    entries, total_files = detect_unused(path)
    return make_unused_findings(entries, log), {"unused": total_files}


def _phase_structural(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    """Merge large + complexity + god classes into structural findings."""
    from ...detectors.large import detect_large_files
    from ...detectors.complexity import detect_complexity
    from ...detectors.gods import detect_gods
    from ...detectors.flat_dirs import detect_flat_dirs
    from .extractors import detect_passthrough_functions, extract_py_classes

    structural: dict[str, dict] = {}

    large_entries, file_count = detect_large_files(path, file_finder=lang.file_finder,
                                                    threshold=lang.large_threshold)
    for e in large_entries:
        add_structural_signal(structural, e["file"], f"large ({e['loc']} LOC)",
                              {"loc": e["loc"]})

    complexity_entries, _ = detect_complexity(path, signals=PY_COMPLEXITY_SIGNALS,
                                              file_finder=lang.file_finder,
                                              threshold=lang.complexity_threshold)
    for e in complexity_entries:
        add_structural_signal(structural, e["file"], f"complexity score {e['score']}",
                              {"complexity_score": e["score"],
                               "complexity_signals": e["signals"]})

    god_entries, god_count = detect_gods(extract_py_classes(path), PY_GOD_RULES)
    for e in god_entries:
        add_structural_signal(structural, e["file"], e["signal_text"], e["detail"])

    results = merge_structural_signals(structural, log)

    # Flat directories
    from ...state import make_finding
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

    # Passthrough functions
    pt_entries = detect_passthrough_functions(path)
    results.extend(make_passthrough_findings(pt_entries, "function", "total_params", log))

    potentials = {
        "structural": file_count,
        "flat_dirs": dir_count,
        "props": len(pt_entries) if pt_entries else 0,
    }
    return results, potentials


def _phase_coupling(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.deps import build_dep_graph
    from ...detectors.graph import detect_cycles
    from ...detectors.orphaned import detect_orphaned_files
    from ...detectors.single_use import detect_single_use_abstractions

    graph = build_dep_graph(path)

    single_entries, single_candidates = detect_single_use_abstractions(
        path, graph, barrel_names=lang.barrel_names)
    results = make_single_use_findings(single_entries, lang.get_area,
                                       skip_dir_names={"commands"}, stderr_fn=log)

    cycle_entries, total_edges = detect_cycles(graph)
    results.extend(make_cycle_findings(cycle_entries, log))

    orphan_entries, total_graph_files = detect_orphaned_files(
        path, graph, extensions=lang.extensions,
        extra_entry_patterns=lang.entry_patterns,
        extra_barrel_names=lang.barrel_names)
    results.extend(make_orphaned_findings(orphan_entries, log))

    log(f"         -> {len(results)} coupling/structural findings total")
    potentials = {
        "single_use": single_candidates,
        "cycles": total_edges,
        "orphaned": total_graph_files,
    }
    return results, potentials


def _phase_smells(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.smells import detect_smells
    entries, total_files = detect_smells(path)
    return make_smell_findings(entries, log), {"smells": total_files}


# ── Build the config ──────────────────────────────────────


def _py_build_dep_graph(path: Path) -> dict:
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _py_extract_functions(path: Path) -> list:
    """Extract all Python functions for duplicate detection."""
    from .extractors import extract_py_functions
    functions = []
    for filepath in find_py_files(path):
        functions.extend(extract_py_functions(filepath))
    return functions


@register_lang("python")
class PythonConfig(LangConfig):
    def __init__(self):
        from .commands import get_detect_commands, DETECTOR_NAMES
        super().__init__(
            name="python",
            extensions=[".py"],
            exclusions=["__pycache__", ".venv", "node_modules", ".eggs", "*.egg-info"],
            default_src=".",
            build_dep_graph=_py_build_dep_graph,
            entry_patterns=PY_ENTRY_PATTERNS,
            barrel_names={"__init__.py"},
            phases=[
                DetectorPhase("Unused (ruff)", _phase_unused),
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", _phase_coupling),
                DetectorPhase("Code smells", _phase_smells),
                DetectorPhase("Duplicates", phase_dupes, slow=True),
            ],
            fixers={},
            get_area=_get_py_area,
            detector_names=DETECTOR_NAMES,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="",
            file_finder=find_py_files,
            large_threshold=300,
            complexity_threshold=25,
            extract_functions=_py_extract_functions,
        )
