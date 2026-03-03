"""Generic language plugin system — run external tools, parse output, emit findings.

Provides `generic_lang()` to register a language plugin from a list of tool specs.
Each tool runs a shell command at scan time, parses the output into findings, and
gracefully degrades when the tool is not installed or times out.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.core.registry import DetectorMeta, register_detector
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.core.source_discovery import find_source_files
from desloppify.languages._framework.base.types import (
    DetectorPhase,
    FixerConfig,
    LangConfig,
)
from desloppify.languages._framework.generic_parts.parsers import (
    PARSERS as _PARSERS,
)
from desloppify.languages._framework.generic_parts.parsers import (
    parse_cargo,
    parse_eslint,
    parse_gnu,
    parse_golangci,
    parse_json,
    parse_rubocop,
)
from desloppify.languages._framework.generic_parts.tool_factories import (
    make_detect_fn,
    make_generic_fixer,
    make_tool_phase,
)
from desloppify.languages._framework.generic_parts.tool_spec import (
    normalize_tool_specs,
)
from desloppify.languages._framework.treesitter import (
    PARSE_INIT_ERRORS as _TS_INIT_ERRORS,
)
from desloppify.scoring import DetectorScoringPolicy, register_scoring_policy

logger = logging.getLogger(__name__)

# Shared phase labels — used by capability_report and langs command.
SHARED_PHASE_LABELS = frozenset({
    "Security", "Subjective review", "Boilerplate duplication", "Duplicates",
    "Structural analysis", "Coupling + cycles + orphaned", "Test coverage",
    "AST smells", "Responsibility cohesion", "Unused imports", "Signature analysis",
})


# Parser and tool execution helpers are composed from smaller modules to keep
# this file focused on plugin assembly.


# ── Stubs for generic configs ─────────────────────────────


def make_file_finder(
    extensions: list[str], exclusions: list[str] | None = None
) -> Callable:
    """Return a file finder function for the given extensions."""
    excl = exclusions or []

    def finder(path: str | Path) -> list[str]:
        return find_source_files(path, extensions, excl or None)

    return finder


def empty_dep_graph(path: Path) -> dict[str, dict[str, Any]]:
    """Stub dep graph builder — generic plugins have no import parsing."""
    return {}


def noop_extract_functions(path: Path) -> list[FunctionInfo]:
    """Stub function extractor — generic plugins don't extract functions."""
    return []


def generic_zone_rules(extensions: list[str]) -> list[ZoneRule]:
    """Minimal zone rules: test dirs → test, vendor/node_modules → vendor, plus common."""
    return [
        ZoneRule(Zone.VENDOR, ["/node_modules/"]),
    ] + COMMON_ZONE_RULES


# ── Capability introspection ─────────────────────────────


def capability_report(cfg: LangConfig) -> tuple[list[str], list[str]] | None:
    """Return (present, missing) capability lists. None for full plugins."""
    if cfg.integration_depth == "full":
        return None

    phase_labels = {p.label for p in cfg.phases}
    present: list[str] = []
    missing: list[str] = []

    def check(condition: bool, label: str) -> None:
        (present if condition else missing).append(label)

    tool_phases = [p.label for p in cfg.phases if p.label not in SHARED_PHASE_LABELS]
    check(bool(tool_phases), f"linting ({', '.join(tool_phases)})" if tool_phases else "linting")
    check(bool(cfg.fixers), "auto-fix")
    check(cfg.build_dep_graph is not empty_dep_graph, "import analysis")
    check(cfg.extract_functions is not noop_extract_functions, "function extraction")
    check("Security" in phase_labels, "security scan")
    check("Boilerplate duplication" in phase_labels, "boilerplate detection")
    check("Subjective review" in phase_labels, "design review")

    return present, missing


# ── Main entry point ──────────────────────────────────────


def generic_lang(
    name: str,
    extensions: list[str],
    tools: list[dict[str, Any]],
    *,
    exclude: list[str] | None = None,
    depth: str = "shallow",
    detect_markers: list[str] | None = None,
    default_src: str = ".",
    treesitter_spec=None,
    zone_rules: list[ZoneRule] | None = None,
    test_coverage_module: object | None = None,
    entry_patterns: list[str] | None = None,
) -> LangConfig:
    """Build and register a generic language plugin from tool specs.

    Each entry in `tools` is::

        {"label": str, "cmd": str, "fmt": str, "id": str, "tier": int,
         "fix_cmd": str | None}

    When ``treesitter_spec`` is provided and ``tree-sitter-language-pack`` is
    installed, the plugin gains function extraction (enables duplicate
    detection), and optionally import analysis (enables coupling/orphan/cycle
    detection and test-coverage analysis) for no additional configuration.

    Returns the built LangConfig (also registered in the language registry).
    """
    from desloppify.languages import register_generic_lang
    from desloppify.languages._framework.base.phase_builders import (
        detector_phase_security,
        detector_phase_test_coverage,
        shared_subjective_duplicates_tail,
    )
    tool_specs = normalize_tool_specs(tools, supported_formats=set(_PARSERS))

    # ── Register each tool as a detector + scoring policy ──
    fixers: dict[str, FixerConfig] = {}
    for tool in tool_specs:
        has_fixer = tool.get("fix_cmd") is not None
        fixer_name = tool["id"].replace("_", "-") if has_fixer else ""
        register_detector(DetectorMeta(
            name=tool["id"],
            display=tool["label"],
            dimension="Code quality",
            action_type="auto_fix" if has_fixer else "manual_fix",
            guidance=f"review and fix {tool['label']} findings",
            fixers=(fixer_name,) if has_fixer else (),
        ))
        register_scoring_policy(DetectorScoringPolicy(
            detector=tool["id"],
            dimension="Code quality",
            tier=tool["tier"],
            file_based=True,
        ))
        if has_fixer:
            fixers[fixer_name] = make_generic_fixer(tool)

    # ── Determine extractors based on tree-sitter availability ──
    file_finder = make_file_finder(extensions, exclude)
    extract_fn = noop_extract_functions
    dep_graph_fn = empty_dep_graph
    has_treesitter = False

    if treesitter_spec is not None:
        from desloppify.languages._framework.treesitter import is_available

        if is_available():
            from desloppify.languages._framework.treesitter._extractors import (
                make_ts_extractor,
            )
            from desloppify.languages._framework.treesitter._imports import (
                make_ts_dep_builder,
            )

            has_treesitter = True
            extract_fn = make_ts_extractor(treesitter_spec, file_finder)
            if treesitter_spec.import_query and treesitter_spec.resolve_import:
                dep_graph_fn = make_ts_dep_builder(treesitter_spec, file_finder)

    # ── Build phases: tool-specific + structural + coupling + shared ──
    phases = [
        make_tool_phase(t["label"], t["cmd"], t["fmt"], t["id"], t["tier"])
        for t in tool_specs
    ]

    # Add structural phase (with AST complexity if tree-sitter available).
    phases.append(_make_structural_phase(
        treesitter_spec if has_treesitter else None,
    ))

    # Add tree-sitter-powered AST phases when available.
    if has_treesitter:
        from desloppify.languages._framework.treesitter.phases import (
            make_ast_smells_phase,
            make_cohesion_phase,
            make_unused_imports_phase,
        )

        phases.append(make_ast_smells_phase(treesitter_spec))
        phases.append(make_cohesion_phase(treesitter_spec))
        if treesitter_spec.import_query:
            phases.append(make_unused_imports_phase(treesitter_spec))

    # Signature analysis — uses lang.extract_functions (no tree-sitter needed).
    if extract_fn is not noop_extract_functions:
        from desloppify.languages._framework.base.phase_builders import (
            detector_phase_signature,
        )

        phases.append(detector_phase_signature())

    phases.append(detector_phase_security())

    # Add coupling phase if we have a real dep graph.
    if dep_graph_fn is not empty_dep_graph:
        phases.append(_make_coupling_phase(dep_graph_fn))
        phases.append(detector_phase_test_coverage())

    phases.extend(shared_subjective_duplicates_tail())

    cfg = LangConfig(
        name=name,
        extensions=extensions,
        exclusions=exclude or [],
        default_src=default_src,
        build_dep_graph=dep_graph_fn,
        entry_patterns=entry_patterns or [],
        barrel_names=set(),
        phases=phases,
        fixers=fixers,
        get_area=None,
        detect_commands={
            t["id"]: make_detect_fn(t["cmd"], _PARSERS[t["fmt"]])
            for t in tool_specs
        },
        extract_functions=extract_fn,
        boundaries=[],
        typecheck_cmd="",
        file_finder=file_finder,
        large_threshold=500,
        complexity_threshold=15,
        default_scan_profile="objective",
        detect_markers=detect_markers or [],
        external_test_dirs=["tests", "test"],
        test_file_extensions=extensions,
        zone_rules=zone_rules if zone_rules is not None else generic_zone_rules(extensions),
    )

    # Set integration depth — upgrade when tree-sitter provides capabilities.
    if has_treesitter and depth in ("shallow", "minimal"):
        cfg.integration_depth = "standard"
    else:
        cfg.integration_depth = depth

    # Register language-specific test coverage hooks if provided.
    if test_coverage_module is not None:
        from desloppify.hook_registry import register_lang_hooks

        register_lang_hooks(name, test_coverage=test_coverage_module)

    register_generic_lang(name, cfg)
    return cfg


# ── Structural + coupling phase helpers ──────────────────────


def _make_structural_phase(treesitter_spec=None) -> DetectorPhase:
    """Create a structural analysis phase for generic plugins."""
    from desloppify.engine.detectors.base import ComplexitySignal
    from desloppify.core.output import log

    signals = [
        ComplexitySignal(
            "TODOs",
            r"(?://|#|--|/\*)\s*(?:TODO|FIXME|HACK|XXX)",
            weight=2,
            threshold=0,
        ),
    ]

    if treesitter_spec is not None:
        from desloppify.languages._framework.treesitter import is_available

        if is_available():
            from desloppify.languages._framework.treesitter._complexity import (
                make_callback_depth_compute,
                make_cyclomatic_complexity_compute,
                make_long_functions_compute,
                make_max_params_compute,
                make_nesting_depth_compute,
            )

            signals.append(ComplexitySignal(
                "nesting_depth", None, weight=3, threshold=4,
                compute=make_nesting_depth_compute(treesitter_spec),
            ))
            signals.append(ComplexitySignal(
                "long_functions", None, weight=3, threshold=80,
                compute=make_long_functions_compute(treesitter_spec),
            ))
            signals.append(ComplexitySignal(
                "cyclomatic_complexity", None, weight=2, threshold=15,
                compute=make_cyclomatic_complexity_compute(treesitter_spec),
            ))
            signals.append(ComplexitySignal(
                "many_params", None, weight=2, threshold=7,
                compute=make_max_params_compute(treesitter_spec),
            ))
            signals.append(ComplexitySignal(
                "callback_depth", None, weight=2, threshold=3,
                compute=make_callback_depth_compute(treesitter_spec),
            ))

    # God class rules (active when tree-sitter provides class extraction).
    god_rules = None
    has_class_query = treesitter_spec is not None and treesitter_spec.class_query
    if has_class_query:
        from desloppify.engine.detectors.base import GodRule

        god_rules = [
            GodRule("methods", "methods", lambda c: len(c.methods), 15),
            GodRule("loc", "LOC", lambda c: c.loc, 500),
            GodRule("attributes", "attributes", lambda c: len(c.attributes), 10),
        ]

    def run(path, lang):
        from desloppify.languages._framework.base.shared_phases import (
            run_structural_phase,
        )

        god_extractor_fn = None
        if god_rules and has_class_query:
            god_extractor_fn = _make_god_extractor(treesitter_spec, lang.file_finder)

        return run_structural_phase(
            path, lang,
            complexity_signals=signals,
            log_fn=log,
            min_loc=40,
            god_rules=god_rules,
            god_extractor_fn=god_extractor_fn,
        )

    return DetectorPhase("Structural analysis", run)


def _make_god_extractor(treesitter_spec, file_finder):
    """Create a god-class extractor function bound to the given spec."""
    def extractor(p):
        return _extract_ts_classes(p, treesitter_spec, file_finder)
    return extractor


def _extract_ts_classes(path, treesitter_spec, file_finder):
    """Extract classes with methods populated via tree-sitter.

    Returns [] on any error (graceful degradation).
    """
    try:
        from collections import defaultdict

        from desloppify.languages._framework.treesitter._extractors import (
            ts_extract_classes,
            ts_extract_functions,
        )

        file_list = file_finder(path)
        classes = ts_extract_classes(path, treesitter_spec, file_list)
        if not classes:
            return classes

        functions = ts_extract_functions(path, treesitter_spec, file_list)
        by_file = defaultdict(list)
        for fn in functions:
            by_file[fn.file].append(fn)
        for cls in classes:
            cls_end = cls.line + cls.loc
            for fn in by_file.get(cls.file, []):
                if cls.line <= fn.line <= cls_end:
                    cls.methods.append(fn)

        return classes
    except _TS_INIT_ERRORS as exc:
        logger.debug("tree-sitter class extraction failed: %s", exc)
        return []


def _make_coupling_phase(dep_graph_fn) -> DetectorPhase:
    """Create a coupling phase for generic plugins with a dep graph."""
    from desloppify.core.output import log

    def run(path, lang):
        from desloppify.languages._framework.base.shared_phases import (
            run_coupling_phase,
        )

        return run_coupling_phase(
            path, lang, build_dep_graph_fn=dep_graph_fn, log_fn=log,
        )

    return DetectorPhase("Coupling + cycles + orphaned", run)


__all__ = [
    "SHARED_PHASE_LABELS",
    "capability_report",
    "generic_lang",
    "generic_zone_rules",
    "make_file_finder",
    "make_tool_phase",
    "parse_cargo",
    "parse_eslint",
    "parse_gnu",
    "parse_golangci",
    "parse_json",
    "parse_rubocop",
]
