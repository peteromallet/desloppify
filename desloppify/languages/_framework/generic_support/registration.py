"""Registration and phase-assembly helpers for generic language plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desloppify.base.registry import DetectorMeta, register_detector
from desloppify.engine._scoring.policy.core import (
    DetectorScoringPolicy,
    register_scoring_policy,
)
from desloppify.engine.policy.zones import ZoneRule
from desloppify.languages._framework.base.types import DetectorPhase, FixerConfig
from .capabilities import (
    empty_dep_graph,
    make_file_finder,
    noop_extract_functions,
)
from desloppify.languages._framework.generic_parts.tool_factories import (
    make_generic_fixer,
    make_tool_phase,
)
from .structural import (
    _make_coupling_phase,
    _make_structural_phase,
)


@dataclass(frozen=True)
class GenericLangOptions:
    """Optional configuration bundle for generic language registration."""

    exclude: list[str] | None = None
    depth: str = "shallow"
    detect_markers: list[str] | None = None
    default_src: str = "."
    treesitter_spec: Any | None = None
    zone_rules: list[ZoneRule] | None = None
    test_coverage_module: Any | None = None
    entry_patterns: list[str] | None = None
    external_test_dirs: list[str] | None = None
    test_file_extensions: list[str] | None = None
    custom_phases: list[DetectorPhase] | None = None


def _register_generic_tool_specs(tool_specs: list[dict[str, Any]]) -> dict[str, FixerConfig]:
    fixers: dict[str, FixerConfig] = {}
    for tool in tool_specs:
        has_fixer = tool.get("fix_cmd") is not None
        fixer_name = tool["id"].replace("_", "-") if has_fixer else ""
        register_detector(
            DetectorMeta(
                name=tool["id"],
                display=tool["label"],
                dimension="Code quality",
                action_type="auto_fix" if has_fixer else "manual_fix",
                guidance=f"review and fix {tool['label']} issues",
                fixers=(fixer_name,) if has_fixer else (),
            )
        )
        register_scoring_policy(
            DetectorScoringPolicy(
                detector=tool["id"],
                dimension="Code quality",
                tier=tool["tier"],
                file_based=True,
            )
        )
        if has_fixer:
            fixers[fixer_name] = make_generic_fixer(tool)
    return fixers


def _resolve_generic_extractors(
    *,
    path_extensions: list[str],
    opts: GenericLangOptions,
) -> tuple[Any, Any, Any, bool, Any]:
    file_finder = make_file_finder(path_extensions, opts.exclude)
    extract_fn = noop_extract_functions
    dep_graph_fn = empty_dep_graph
    ts_spec = opts.treesitter_spec
    has_treesitter = False
    if ts_spec is None:
        return file_finder, extract_fn, dep_graph_fn, has_treesitter, ts_spec

    from desloppify.languages._framework.treesitter import is_available

    if not is_available():
        return file_finder, extract_fn, dep_graph_fn, has_treesitter, ts_spec

    from desloppify.languages._framework.treesitter.analysis.extractors import make_ts_extractor
    from desloppify.languages._framework.treesitter.imports.graph import make_ts_dep_builder

    has_treesitter = True
    extract_fn = make_ts_extractor(ts_spec, file_finder)
    if ts_spec.import_query and ts_spec.resolve_import:
        dep_graph_fn = make_ts_dep_builder(ts_spec, file_finder)
    return file_finder, extract_fn, dep_graph_fn, has_treesitter, ts_spec


def _build_generic_phases(
    *,
    tool_specs: list[dict[str, Any]],
    ts_spec: Any,
    has_treesitter: bool,
    extract_fn,
    dep_graph_fn,
    custom_phases: list[DetectorPhase] | None = None,
) -> list[DetectorPhase]:
    from desloppify.languages._framework.base.phase_builders import (
        detector_phase_security,
        detector_phase_test_coverage,
        shared_subjective_duplicates_tail,
    )

    phases = [
        make_tool_phase(tool["label"], tool["cmd"], tool["fmt"], tool["id"], tool["tier"])
        for tool in tool_specs
    ]
    phases.append(_make_structural_phase(ts_spec if has_treesitter else None))

    if has_treesitter and ts_spec is not None:
        from desloppify.languages._framework.treesitter.phases import (
            make_ast_smells_phase,
            make_cohesion_phase,
            make_unused_imports_phase,
        )

        phases.append(make_ast_smells_phase(ts_spec))
        phases.append(make_cohesion_phase(ts_spec))
        if ts_spec.import_query:
            phases.append(make_unused_imports_phase(ts_spec))

    if extract_fn is not noop_extract_functions:
        from desloppify.languages._framework.base.phase_builders import detector_phase_signature

        phases.append(detector_phase_signature())

    phases.append(detector_phase_security())
    if dep_graph_fn is not empty_dep_graph:
        phases.append(_make_coupling_phase(dep_graph_fn))
        phases.append(detector_phase_test_coverage())

    if custom_phases:
        phases.extend(custom_phases)

    phases.extend(shared_subjective_duplicates_tail())
    return phases


__all__ = [
    "GenericLangOptions",
    "_build_generic_phases",
    "_register_generic_tool_specs",
    "_resolve_generic_extractors",
]
