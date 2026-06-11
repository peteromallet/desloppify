"""Python detector phase runners and config constants."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.engine.detectors.base import ComplexitySignal, GodRule
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages._framework.issue_factories import (
    make_unused_issues,
)
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages.python.detectors import (
    responsibility_cohesion as cohesion_detector_mod,
)
from desloppify.languages.python.detectors import uncalled as uncalled_detector_mod
from desloppify.languages.python.detectors import unused as unused_detector_mod
from desloppify.languages.python.detectors import unused_enums as unused_enums_mod
from desloppify.languages.python.detectors.complexity import (
    compute_long_functions,
    compute_max_params,
    compute_nesting_depth,
)
from desloppify.languages.python.phases_quality import (
    phase_dict_keys,
    phase_layer_violation,
    phase_mutable_state,
    phase_smells,
)
from desloppify.languages.python.phases_runtime import (
    run_phase_coupling,
    run_phase_structural,
)
from desloppify.state_io import Issue

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
    "conf.py",  # Sphinx documentation config (loaded by sphinx-build)
    "wsgi.py",
    "asgi.py",
    "cli.py",  # CLI entry points (loaded via framework/importlib)
    "/commands/",  # CLI subcommands (loaded dynamically)
    "/fixers/",  # Fixer modules (loaded dynamically)
    "/lang/",  # Language modules (loaded dynamically)
    "/extractors/",  # Extractor modules (loaded dynamically)
    "__init__.py",  # Package init files (barrels, not orphans)
]


def phase_unused(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    entries, total_files = unused_detector_mod.detect_unused(path)
    return make_unused_issues(entries, log), {
        "unused": adjust_potential(lang.zone_map, total_files),
    }


def phase_structural(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], dict[str, int]]:
    return run_phase_structural(
        path,
        lang,
        complexity_signals=PY_COMPLEXITY_SIGNALS,
        god_rules=PY_GOD_RULES,
        log_fn=log,
    )


def phase_coupling(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    return run_phase_coupling(path, lang, log_fn=log)


def phase_responsibility_cohesion(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], dict[str, int]]:
    entries, candidates = cohesion_detector_mod.detect_responsibility_cohesion(path)
    entries = filter_entries(lang.zone_map, entries, "responsibility_cohesion")

    results: list[dict] = []
    for entry in entries:
        comp_sizes = ", ".join(str(size) for size in entry["component_sizes"][:5])
        if len(entry["component_sizes"]) > 5:
            comp_sizes += f", +{len(entry['component_sizes']) - 5} more"
        results.append(
            make_issue(
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

def phase_uncalled_functions(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], dict[str, int]]:
    """Detect underscore-prefixed top-level functions with zero references."""
    entries, total = uncalled_detector_mod.detect_uncalled_functions(
        path, lang.dep_graph
    )
    zm = lang.zone_map
    entries = filter_entries(zm, entries, "uncalled_functions")

    results: list[Issue] = []
    for entry in entries:
        results.append(
            make_issue(
                "uncalled_functions",
                entry["file"],
                entry["name"],
                tier=3,
                confidence="high",
                summary=f"Uncalled private function: {entry['name']}() — {entry['loc']} LOC, zero references",
                detail={"line": entry["line"], "loc": entry["loc"]},
            )
        )

    if results:
        log(f"         uncalled functions: {len(results)} dead private functions")
    return results, {"uncalled_functions": adjust_potential(zm, total)}


def phase_unused_enums(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], dict[str, int]]:
    """Detect enum classes with zero external imports."""
    entries, total = unused_enums_mod.detect_unused_enums(path)
    entries = filter_entries(lang.zone_map, entries, "unused_enums")

    results: list[Issue] = []
    for entry in entries:
        results.append(
            make_issue(
                "unused_enums",
                entry["file"],
                entry["name"],
                tier=2,
                confidence="high",
                summary=(
                    f"Unused enum: {entry['name']} "
                    f"({entry['member_count']} members) — never imported externally"
                ),
                detail={
                    "line": entry["line"],
                    "member_count": entry["member_count"],
                },
            )
        )

    if results:
        log(f"         unused enums: {len(results)} enum classes with zero imports")
    return results, {"unused_enums": adjust_potential(lang.zone_map, total)}

__all__ = [
    "PY_COMPLEXITY_SIGNALS",
    "PY_ENTRY_PATTERNS",
    "PY_GOD_RULES",
    "PY_SKIP_NAMES",
    "phase_coupling",
    "phase_dict_keys",
    "phase_layer_violation",
    "phase_mutable_state",
    "phase_responsibility_cohesion",
    "phase_smells",
    "phase_structural",
    "phase_uncalled_functions",
    "phase_unused",
    "phase_unused_enums",
]
