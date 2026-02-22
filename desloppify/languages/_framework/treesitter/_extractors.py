"""Tree-sitter based function and class extractors."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from desloppify.engine.detectors.base import ClassInfo, FunctionInfo

from ._cache import _PARSE_CACHE
from ._normalize import normalize_body

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

logger = logging.getLogger(__name__)

# Parameter list node types across languages.
_PARAM_NODE_TYPES = frozenset({
    "parameters",
    "parameter_list",
    "formal_parameters",
    "formal_parameter_list",
    "function_type_parameters",
    "lambda_parameters",
    "method_parameters",
    "params",
})

# Identifier-like node types for parameter names.
_IDENT_NODE_TYPES = frozenset({
    "identifier",
    "name",
    "simple_identifier",
    "word",
    "pattern",
    "shorthand_field_identifier",
})

# Node types to skip when walking parameter lists (type annotations, etc.).
_PARAM_SKIP_TYPES = frozenset({
    "type", "type_identifier", "type_annotation", "return_type",
    "default_value", "generic_type", "scoped_type_identifier",
    "constrained_type_parameter", "lifetime", "attribute",
    ":", "=", ",", "(", ")", "[", "]",
})

# Node types whose parent indicates the identifier is a type, not a param name.
_TYPE_PARENT_TYPES = frozenset({
    "type", "type_identifier", "type_annotation", "return_type",
    "generic_type", "scoped_type_identifier", "constrained_type_parameter",
})


def _extract_param_names(func_node) -> list[str]:
    """Extract parameter names from a function node's parameter list."""
    params: list[str] = []
    for child in func_node.children:
        if child.type in _PARAM_NODE_TYPES:
            _walk_params(child, params)
            break
    return params


def _walk_params(node, params: list[str]) -> None:
    """Recursively walk a parameter list node to find identifier names."""
    if node.type in _IDENT_NODE_TYPES:
        if node.parent and node.parent.type not in _TYPE_PARENT_TYPES:
            text = (
                node.text.decode("utf-8", errors="replace")
                if isinstance(node.text, bytes)
                else str(node.text)
            )
            if text and text not in params:
                params.append(text)
        return

    for child in node.children:
        if child.type in _PARAM_SKIP_TYPES:
            continue
        _walk_params(child, params)


def _make_query(language, source: str):
    """Create a tree-sitter Query."""
    from tree_sitter import Query
    return Query(language, source)


def _run_query(query, root_node) -> list[tuple[int, dict]]:
    """Run a query and return matches."""
    from tree_sitter import QueryCursor
    cursor = QueryCursor(query)
    return cursor.matches(root_node)


def _get_parser(grammar: str):
    """Get a tree-sitter parser and language for the given grammar."""
    from tree_sitter_language_pack import get_language, get_parser

    parser = get_parser(grammar)
    language = get_language(grammar)
    return parser, language


def _unwrap_node(node):
    """Unwrap a capture that may be a list of nodes."""
    if isinstance(node, list):
        return node[0] if node else None
    return node


def _node_text(node) -> str:
    """Get text from a node as a str."""
    text = node.text
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def ts_extract_functions(
    path: Path,
    spec: TreeSitterLangSpec,
    file_list: list[str],
) -> list[FunctionInfo]:
    """Extract functions from all files using tree-sitter."""
    parser, language = _get_parser(spec.grammar)
    query = _make_query(language, spec.function_query)
    functions: list[FunctionInfo] = []

    for filepath in file_list:
        cached = _PARSE_CACHE.get_or_parse(filepath, parser, spec.grammar)
        if cached is None:
            continue
        source, tree = cached
        matches = _run_query(query, tree.root_node)

        for _pattern_idx, captures in matches:
            func_node = _unwrap_node(captures.get("func"))
            name_node = _unwrap_node(captures.get("name"))
            if not func_node or not name_node:
                continue

            name_text = _node_text(name_node)

            line = func_node.start_point[0] + 1  # 1-indexed
            end_line = func_node.end_point[0] + 1
            loc = end_line - line + 1

            body = source[func_node.start_byte : func_node.end_byte]
            body_text = body.decode("utf-8", errors="replace")

            normalized = normalize_body(source, func_node, spec)

            # Skip tiny functions (< 3 meaningful lines).
            if len(normalized.splitlines()) < 3:
                continue

            body_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()
            params = _extract_param_names(func_node)

            functions.append(
                FunctionInfo(
                    name=name_text,
                    file=filepath,
                    line=line,
                    end_line=end_line,
                    loc=loc,
                    body=body_text,
                    normalized=normalized,
                    body_hash=body_hash,
                    params=params,
                )
            )

    return functions


def ts_extract_classes(
    path: Path,
    spec: TreeSitterLangSpec,
    file_list: list[str],
) -> list[ClassInfo]:
    """Extract classes/structs from all files using tree-sitter."""
    if not spec.class_query:
        return []

    parser, language = _get_parser(spec.grammar)
    query = _make_query(language, spec.class_query)
    classes: list[ClassInfo] = []

    for filepath in file_list:
        cached = _PARSE_CACHE.get_or_parse(filepath, parser, spec.grammar)
        if cached is None:
            continue
        source, tree = cached
        matches = _run_query(query, tree.root_node)

        for _pattern_idx, captures in matches:
            class_node = _unwrap_node(captures.get("class"))
            name_node = _unwrap_node(captures.get("name"))
            if not class_node or not name_node:
                continue

            name_text = _node_text(name_node)

            line = class_node.start_point[0] + 1
            end_line = class_node.end_point[0] + 1
            loc = end_line - line + 1

            classes.append(
                ClassInfo(
                    name=name_text,
                    file=filepath,
                    line=line,
                    loc=loc,
                )
            )

    return classes


def make_ts_extractor(spec: TreeSitterLangSpec, file_finder):
    """Create a function extractor bound to a TreeSitterLangSpec + file finder.

    Returns a callable with signature (path: Path) -> list[FunctionInfo],
    matching the contract expected by LangConfig.extract_functions.
    """

    def extract(path: Path) -> list[FunctionInfo]:
        file_list = file_finder(path)
        return ts_extract_functions(path, spec, file_list)

    return extract


__all__ = ["make_ts_extractor", "ts_extract_classes", "ts_extract_functions"]
