"""Generic language plugin system — run external tools, parse output, emit issues.

Provides `generic_lang()` to register a language plugin from a list of tool specs.
Each tool runs a shell command at scan time, parses the output into issues, and
gracefully degrades when the tool is not installed or times out.
"""

from __future__ import annotations

from typing import Any

from desloppify.engine.policy.zones import ZoneRule
from desloppify.languages._framework.base.types import LangConfig
from .capabilities import (
    SHARED_PHASE_LABELS,
    capability_report,
    generic_zone_rules,
    make_file_finder,
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
    make_tool_phase,
)
from desloppify.languages._framework.generic_parts.tool_spec import (
    normalize_tool_specs,
)
from .registration import (
    GenericLangOptions,
    _build_generic_phases,
    _register_generic_tool_specs,
    _resolve_generic_extractors,
)


def generic_lang(
    name: str,
    extensions: list[str],
    tools: list[dict[str, Any]],
    *,
    options: GenericLangOptions | None = None,
    exclude: list[str] | None = None,
    depth: str = "shallow",
    detect_markers: list[str] | None = None,
    default_src: str = ".",
    treesitter_spec=None,
    zone_rules: list[ZoneRule] | None = None,
    test_coverage_module: Any | None = None,
    entry_patterns: list[str] | None = None,
    external_test_dirs: list[str] | None = None,
    test_file_extensions: list[str] | None = None,
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
    opts = options or GenericLangOptions(
        exclude=exclude,
        depth=depth,
        detect_markers=detect_markers,
        default_src=default_src,
        treesitter_spec=treesitter_spec,
        zone_rules=zone_rules,
        test_coverage_module=test_coverage_module,
        entry_patterns=entry_patterns,
        external_test_dirs=external_test_dirs,
        test_file_extensions=test_file_extensions,
    )

    from desloppify.languages import register_generic_lang

    tool_specs = normalize_tool_specs(tools, supported_formats=set(_PARSERS))
    fixers = _register_generic_tool_specs(tool_specs)
    file_finder, extract_fn, dep_graph_fn, has_treesitter, ts_spec = _resolve_generic_extractors(
        path_extensions=extensions,
        opts=opts,
    )
    phases = _build_generic_phases(
        tool_specs=tool_specs,
        ts_spec=ts_spec,
        has_treesitter=has_treesitter,
        extract_fn=extract_fn,
        dep_graph_fn=dep_graph_fn,
    )

    cfg = LangConfig(
        name=name,
        extensions=extensions,
        exclusions=opts.exclude or [],
        default_src=opts.default_src,
        build_dep_graph=dep_graph_fn,
        entry_patterns=opts.entry_patterns or [],
        barrel_names=set(),
        phases=phases,
        fixers=fixers,
        get_area=None,
        detect_commands={
            tool["id"]: make_detect_fn(tool["cmd"], _PARSERS[tool["fmt"]])
            for tool in tool_specs
        },
        extract_functions=extract_fn,
        boundaries=[],
        typecheck_cmd="",
        file_finder=file_finder,
        large_threshold=500,
        complexity_threshold=15,
        default_scan_profile="objective",
        detect_markers=opts.detect_markers or [],
        external_test_dirs=opts.external_test_dirs if opts.external_test_dirs is not None else ["tests", "test"],
        test_file_extensions=opts.test_file_extensions if opts.test_file_extensions is not None else extensions,
        zone_rules=opts.zone_rules if opts.zone_rules is not None else generic_zone_rules(extensions),
    )

    # Set integration depth — upgrade when tree-sitter provides capabilities.
    if has_treesitter and opts.depth in ("shallow", "minimal"):
        cfg.integration_depth = "standard"
    else:
        cfg.integration_depth = opts.depth

    # Register language-specific test coverage hooks if provided.
    if opts.test_coverage_module is not None:
        from desloppify.languages._framework.registry.state import register_lang_hooks

        register_lang_hooks(name, test_coverage=opts.test_coverage_module)

    register_generic_lang(name, cfg)
    return cfg


__all__ = [
    "GenericLangOptions",
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
