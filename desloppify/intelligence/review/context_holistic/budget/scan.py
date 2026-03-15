"""Scanning pass and derived analysis for abstraction-economy context."""

from __future__ import annotations

import ast
import dataclasses
import re
from collections import defaultdict
from pathlib import Path

from desloppify.base.discovery.file_paths import rel

from .analysis import _count_signature_params, _extract_type_names
from .axes import _assemble_context, _compute_sub_axes
from .patterns_enums import (
    _census_type_strategies,
    _collect_enum_defs,
    _find_enum_bypass,
)
from .patterns_types import (
    _collect_typed_dict_defs,
    _find_dict_any_annotations,
    _find_typed_dict_usage_violations,
)
from .patterns_wrappers import (
    _find_delegation_heavy_classes,
    _find_facade_modules,
    _find_python_passthrough_wrappers,
)

_DEF_SIGNATURE_RE = re.compile(
    r"(?:^|\n)\s*(?:async\s+def|def|async\s+function|function)\s+\w+\s*\(([^)]*)\)",
    re.MULTILINE,
)

_TS_PASSTHROUGH_RE = re.compile(
    r"\bfunction\s+(\w+)\s*\([^)]*\)\s*\{\s*return\s+(\w+)\s*\(",
    re.MULTILINE,
)

_INTERFACE_RE = re.compile(
    r"\binterface\s+([A-Za-z_]\w*)\b|\bclass\s+([A-Za-z_]\w*Protocol)\b"
)

_IMPLEMENTS_RE = re.compile(r"\bclass\s+\w+\s+implements\s+([^{:\n]+)")

_INHERITS_RE = re.compile(r"\bclass\s+\w+\s*(?:\(([^)\n]+)\)\s*:|:\s*([^\n{]+))")

_CHAIN_RE = re.compile(r"\b(?:\w+\.){2,}\w+\b")

_CONFIG_BAG_RE = re.compile(
    r"\b(?:config|configs|options|opts|params|ctx|context)\b",
    re.IGNORECASE,
)


def _excerpt_from_content(content: str, *, max_lines: int = 30) -> str:
    """Return a short leading excerpt directly from in-memory file content."""
    lines = content.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return content
    return "".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


@dataclasses.dataclass
class _AbstractionsCollector:
    """Accumulated state for the abstractions scan pass."""

    util_files: list = dataclasses.field(default_factory=list)
    wrappers_by_file: list[dict[str, object]] = dataclasses.field(default_factory=list)
    interface_declarations: dict[str, set[str]] = dataclasses.field(
        default_factory=lambda: defaultdict(set)
    )
    implementations: dict[str, set[str]] = dataclasses.field(
        default_factory=lambda: defaultdict(set)
    )
    indirection_hotspots: list[dict[str, object]] = dataclasses.field(
        default_factory=list
    )
    wide_param_bags: list[dict[str, object]] = dataclasses.field(default_factory=list)
    delegation_classes: list[dict] = dataclasses.field(default_factory=list)
    facade_modules: list[dict] = dataclasses.field(default_factory=list)
    typed_dict_defs: dict[str, set[str]] = dataclasses.field(default_factory=dict)
    parsed_trees: dict[str, ast.Module] = dataclasses.field(default_factory=dict)
    total_function_signatures: int = 0
    total_wrappers: int = 0


def _scan_file(
    col: _AbstractionsCollector,
    filepath: str,
    content: str,
) -> None:
    """Scan a single file and accumulate results into *col*."""
    rpath = rel(filepath)
    loc = len(content.splitlines())
    basename = Path(rpath).stem.lower()
    if basename in {"utils", "helpers", "util", "helper", "common", "misc"}:
        col.util_files.append(
            {"file": rpath, "loc": loc, "excerpt": _excerpt_from_content(content)}
        )

    signatures = _DEF_SIGNATURE_RE.findall(content)
    col.total_function_signatures += len(signatures)

    ts_wrappers = [
        (wrapper, target)
        for wrapper, target in _TS_PASSTHROUGH_RE.findall(content)
        if wrapper != target
    ]

    for match in _INTERFACE_RE.finditer(content):
        iface = match.group(1) or match.group(2)
        if iface:
            col.interface_declarations[iface].add(rpath)

    for match in _IMPLEMENTS_RE.finditer(content):
        for iface in _extract_type_names(match.group(1)):
            col.implementations[iface].add(rpath)
    for match in _INHERITS_RE.finditer(content):
        blob = match.group(1) or match.group(2) or ""
        for iface in _extract_type_names(blob):
            col.implementations[iface].add(rpath)

    chain_matches = _CHAIN_RE.findall(content)
    max_chain_depth = max((token.count(".") for token in chain_matches), default=0)
    if max_chain_depth >= 3 or len(chain_matches) >= 6:
        col.indirection_hotspots.append(
            {
                "file": rpath,
                "max_chain_depth": max_chain_depth,
                "chain_count": len(chain_matches),
            }
        )

    wide_functions = sum(
        1 for params_blob in signatures if _count_signature_params(params_blob) >= 7
    )
    bag_mentions = len(_CONFIG_BAG_RE.findall(content))
    if wide_functions > 0 or bag_mentions >= 10:
        col.wide_param_bags.append(
            {
                "file": rpath,
                "wide_functions": wide_functions,
                "config_bag_mentions": bag_mentions,
            }
        )

    try:
        tree = ast.parse(content)
    except SyntaxError:
        tree = None

    if tree is not None:
        col.parsed_trees[filepath] = tree
        py_wrappers = _find_python_passthrough_wrappers(tree)
        for entry in _find_delegation_heavy_classes(tree):
            col.delegation_classes.append({"file": rpath, **entry})
        facade_result = _find_facade_modules(tree, loc=loc)
        if facade_result is not None:
            col.facade_modules.append({"file": rpath, **facade_result})
        _collect_typed_dict_defs(tree, col.typed_dict_defs)
    else:
        py_wrappers = []

    wrapper_pairs = py_wrappers + ts_wrappers
    if wrapper_pairs:
        col.total_wrappers += len(wrapper_pairs)
        col.wrappers_by_file.append(
            {
                "file": rpath,
                "count": len(wrapper_pairs),
                "samples": [f"{w}->{t}" for w, t in wrapper_pairs[:5]],
            }
        )


def _derive_post_scan_results(col: _AbstractionsCollector) -> dict:
    """Compute derived analyses from the completed scan collector."""
    one_impl_interfaces: list[dict[str, object]] = []
    for iface, declared_in in col.interface_declarations.items():
        implemented_in = sorted(col.implementations.get(iface, set()))
        if len(implemented_in) != 1:
            continue
        one_impl_interfaces.append(
            {
                "interface": iface,
                "declared_in": sorted(declared_in),
                "implemented_in": implemented_in,
            }
        )

    typed_dict_violations = _find_typed_dict_usage_violations(
        col.parsed_trees,
        col.typed_dict_defs,
    )[:20]
    total_typed_dict_violations = sum(v.get("count", 1) for v in typed_dict_violations)
    typed_dict_violation_files = {v["file"] for v in typed_dict_violations}

    all_td_names = set(col.typed_dict_defs.keys())
    dict_any_annotations = _find_dict_any_annotations(col.parsed_trees, all_td_names)[:30]

    enum_defs = _collect_enum_defs(col.parsed_trees)
    enum_bypass_patterns = _find_enum_bypass(col.parsed_trees, enum_defs)[:30]

    type_strategy_census = _census_type_strategies(col.parsed_trees)

    return {
        "one_impl_interfaces": one_impl_interfaces,
        "typed_dict_violations": typed_dict_violations,
        "total_typed_dict_violations": total_typed_dict_violations,
        "typed_dict_violation_files": typed_dict_violation_files,
        "dict_any_annotations": dict_any_annotations,
        "enum_bypass_patterns": enum_bypass_patterns,
        "type_strategy_census": type_strategy_census,
    }


def _sort_and_trim(col: _AbstractionsCollector, derived: dict) -> None:
    """Sort and trim collected lists in-place for final output."""
    col.wrappers_by_file.sort(key=lambda item: -int(item["count"]))
    col.indirection_hotspots.sort(
        key=lambda item: (-int(item["max_chain_depth"]), -int(item["chain_count"]))
    )
    col.wide_param_bags.sort(
        key=lambda item: (
            -int(item["wide_functions"]),
            -int(item["config_bag_mentions"]),
        )
    )
    derived["one_impl_interfaces"].sort(key=lambda item: str(item["interface"]))
    col.delegation_classes.sort(key=lambda d: -d["delegation_ratio"])
    col.delegation_classes = col.delegation_classes[:20]
    col.facade_modules.sort(key=lambda d: -d["re_export_ratio"])
    col.facade_modules = col.facade_modules[:20]


def _abstractions_context(file_contents: dict[str, str]) -> dict:
    """Produce abstraction-economy context from codebase file contents."""
    col = _AbstractionsCollector()

    for filepath, content in file_contents.items():
        _scan_file(col, filepath, content)

    derived = _derive_post_scan_results(col)
    _sort_and_trim(col, derived)

    wrapper_rate = col.total_wrappers / max(col.total_function_signatures, 1)
    sub_axes = _compute_sub_axes(
        wrapper_rate=wrapper_rate,
        util_files=col.util_files,
        indirection_hotspots=col.indirection_hotspots,
        wide_param_bags=col.wide_param_bags,
        one_impl_interfaces=derived["one_impl_interfaces"],
        delegation_classes=col.delegation_classes,
        facade_modules=col.facade_modules,
        typed_dict_violation_files=derived["typed_dict_violation_files"],
        total_typed_dict_violations=derived["total_typed_dict_violations"],
        dict_any_count=len(derived["dict_any_annotations"]),
        enum_bypass_count=len(derived["enum_bypass_patterns"]),
    )

    return _assemble_context(
        util_files=col.util_files,
        wrapper_rate=wrapper_rate,
        total_wrappers=col.total_wrappers,
        total_function_signatures=col.total_function_signatures,
        wrappers_by_file=col.wrappers_by_file,
        one_impl_interfaces=derived["one_impl_interfaces"],
        indirection_hotspots=col.indirection_hotspots,
        wide_param_bags=col.wide_param_bags,
        delegation_classes=col.delegation_classes,
        facade_modules=col.facade_modules,
        typed_dict_violations=derived["typed_dict_violations"],
        total_typed_dict_violations=derived["total_typed_dict_violations"],
        sub_axes=sub_axes,
        dict_any_annotations=derived["dict_any_annotations"],
        enum_bypass_patterns=derived["enum_bypass_patterns"],
        type_strategy_census=derived["type_strategy_census"],
    )


__all__ = ["_AbstractionsCollector", "_abstractions_context", "_derive_post_scan_results", "_scan_file", "_sort_and_trim"]
