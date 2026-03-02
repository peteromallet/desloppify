"""AST-based complexity signals using tree-sitter."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import PARSE_INIT_ERRORS
from ._cache import _PARSE_CACHE
from ._extractors import _get_parser

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

logger = logging.getLogger(__name__)


def _ensure_parser(
    cache: dict,
    spec: TreeSitterLangSpec,
    *,
    with_query: bool = False,
) -> bool:
    """Lazily initialise parser (and optionally a function query) into *cache*.

    Returns ``True`` if the cache is ready, ``False`` on initialisation
    failure.  Callers should ``return None`` on ``False``.
    """
    if "parser" in cache:
        return True
    try:
        p, lang = _get_parser(spec.grammar)
        cache["parser"] = p
        cache["language"] = lang
        if with_query:
            from ._extractors import _make_query

            cache["query"] = _make_query(lang, spec.function_query)
    except PARSE_INIT_ERRORS as exc:
        logger.debug("tree-sitter init failed: %s", exc)
        return False
    return True

# Node types that increase nesting depth (cross-language superset).
_NESTING_NODE_TYPES = frozenset({
    # Conditionals
    "if_statement", "if_expression", "if_let_expression",
    "else_clause", "elif_clause",
    # Loops
    "for_statement", "for_expression", "for_in_statement",
    "while_statement", "while_expression", "do_statement",
    "loop_expression",
    # Error handling
    "try_statement", "try_expression", "catch_clause", "rescue",
    "except_clause",
    # Branching
    "switch_statement", "switch_expression", "match_expression",
    "case_clause", "match_arm",
    # Blocks that indicate nesting
    "with_statement", "with_clause",
    # Closures/lambdas
    "lambda_expression", "closure_expression",
})


def compute_nesting_depth_ts(
    filepath: str, spec: TreeSitterLangSpec, parser, language
) -> int | None:
    """Compute max nesting depth using AST traversal.

    Walks the parse tree and counts depth of nested control-flow nodes.
    Returns max depth found in the file, or None if file can't be parsed.
    """
    cached = _PARSE_CACHE.get_or_parse(filepath, parser, spec.grammar)
    if cached is None:
        return None
    _source, tree = cached

    # Iterative DFS with depth tracking.
    max_depth = 0
    # Stack: (node, current_nesting_depth)
    stack: list[tuple[object, int]] = [(tree.root_node, 0)]

    while stack:
        node, depth = stack.pop()
        if node.type in _NESTING_NODE_TYPES:
            depth += 1
            if depth > max_depth:
                max_depth = depth

        for i in range(node.child_count - 1, -1, -1):
            stack.append((node.children[i], depth))

    return max_depth


def make_nesting_depth_compute(spec: TreeSitterLangSpec):
    """Create a compute function for nesting depth using tree-sitter.

    Returns a callable matching ComplexitySignal.compute signature:
    (content: str, lines: list[str]) -> (count, label) | None
    """
    # Cache parser/language per spec to avoid repeated lookups.
    _cached_parser: dict = {}

    def compute(content: str, lines: list[str], *, _filepath: str = "") -> tuple[int, str] | None:
        if not _filepath:
            return None

        if not _ensure_parser(_cached_parser, spec):
            return None

        depth = compute_nesting_depth_ts(
            _filepath, spec, _cached_parser["parser"], _cached_parser["language"]
        )
        if depth is None or depth <= 0:
            return None
        return depth, f"nesting depth {depth}"

    return compute


def make_long_functions_compute(spec: TreeSitterLangSpec):
    """Create a compute function for long functions using tree-sitter.

    Flags the longest function in a file if it exceeds the threshold.
    Returns a callable matching ComplexitySignal.compute signature.
    """
    from ._extractors import _run_query, _unwrap_node

    _cached_parser: dict = {}

    def compute(content: str, lines: list[str], *, _filepath: str = "") -> tuple[int, str] | None:
        if not _filepath:
            return None

        if not _ensure_parser(_cached_parser, spec, with_query=True):
            return None

        parser = _cached_parser["parser"]
        query = _cached_parser["query"]

        cached = _PARSE_CACHE.get_or_parse(_filepath, parser, spec.grammar)
        if cached is None:
            return None
        _source, tree = cached

        matches = _run_query(query, tree.root_node)
        max_loc = 0
        for _pattern_idx, captures in matches:
            func_node = _unwrap_node(captures.get("func"))
            if not func_node:
                continue
            loc = func_node.end_point[0] - func_node.start_point[0] + 1
            if loc > max_loc:
                max_loc = loc

        if max_loc <= 0:
            return None
        return max_loc, f"longest function {max_loc} LOC"

    return compute


# ── Cyclomatic complexity per function ────────────────────────

# Node types that represent branching decisions (adds 1 to cyclomatic complexity).
_BRANCHING_NODE_TYPES = frozenset({
    "if_statement", "if_expression", "if_let_expression",
    "elif_clause", "else_if",
    "for_statement", "for_expression", "for_in_statement",
    "while_statement", "while_expression", "do_statement",
    "loop_expression",
    "case_clause", "match_arm", "match_conditional_expression",
    "catch_clause", "rescue", "except_clause",
    "ternary_expression", "conditional_expression",
    # Logical operators (short-circuit evaluation).
    "binary_expression",  # checked for && / || below
})

_LOGICAL_OPS = frozenset({"&&", "||", "and", "or"})


def _count_decisions(node) -> int:
    """Count decision points in a subtree for cyclomatic complexity."""
    count = 0
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in _BRANCHING_NODE_TYPES:
            if n.type == "binary_expression":
                # Only count if the operator is a logical operator.
                for child in n.children:
                    if child.type in _LOGICAL_OPS or (
                        child.child_count == 0 and child.text and
                        (child.text if isinstance(child.text, str) else child.text.decode("utf-8", "replace"))
                        in _LOGICAL_OPS
                    ):
                        count += 1
                        break
            else:
                count += 1
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])
    return count


def make_cyclomatic_complexity_compute(spec: TreeSitterLangSpec):
    """Create a compute function for max cyclomatic complexity per function.

    Cyclomatic complexity = 1 + number of decision points (if/for/while/case/catch/&&/||).
    Returns the max CC across all functions in the file.
    """
    from ._extractors import _run_query, _unwrap_node

    _cached_parser: dict = {}

    def compute(content: str, lines: list[str], *, _filepath: str = "") -> tuple[int, str] | None:
        if not _filepath:
            return None

        if not _ensure_parser(_cached_parser, spec, with_query=True):
            return None

        parser = _cached_parser["parser"]
        query = _cached_parser["query"]

        cached = _PARSE_CACHE.get_or_parse(_filepath, parser, spec.grammar)
        if cached is None:
            return None
        _source, tree = cached

        matches = _run_query(query, tree.root_node)
        max_cc = 0
        for _pattern_idx, captures in matches:
            func_node = _unwrap_node(captures.get("func"))
            if not func_node:
                continue
            cc = 1 + _count_decisions(func_node)
            if cc > max_cc:
                max_cc = cc

        if max_cc <= 1:
            return None
        return max_cc, f"cyclomatic complexity {max_cc}"

    return compute


# ── Long parameter lists ─────────────────────────────────────


def make_max_params_compute(spec: TreeSitterLangSpec):
    """Create a compute function that finds the max parameter count across functions.

    Uses tree-sitter function extraction with parameter parsing.
    """
    from ._extractors import (
        _extract_param_names,
        _run_query,
        _unwrap_node,
    )

    _cached_parser: dict = {}

    def compute(content: str, lines: list[str], *, _filepath: str = "") -> tuple[int, str] | None:
        if not _filepath:
            return None

        if not _ensure_parser(_cached_parser, spec, with_query=True):
            return None

        parser = _cached_parser["parser"]
        query = _cached_parser["query"]

        cached = _PARSE_CACHE.get_or_parse(_filepath, parser, spec.grammar)
        if cached is None:
            return None
        _source, tree = cached

        matches = _run_query(query, tree.root_node)
        max_params = 0
        for _pattern_idx, captures in matches:
            func_node = _unwrap_node(captures.get("func"))
            if not func_node:
                continue
            params = _extract_param_names(func_node)
            # Filter out self/cls/this.
            params = [p for p in params if p not in ("self", "cls", "this")]
            if len(params) > max_params:
                max_params = len(params)

        if max_params <= 0:
            return None
        return max_params, f"{max_params} params"

    return compute


# ── Callback/closure nesting depth ────────────────────────────

# Node types for closures/lambdas/anonymous functions.
_CLOSURE_NODE_TYPES = frozenset({
    "arrow_function", "function_expression", "function",
    "lambda_expression", "closure_expression", "lambda",
    "anonymous_function", "block_argument",
    # Go anonymous functions
    "func_literal",
    # PHP anonymous functions (``function() { ... }``)
    "anonymous_function_creation_expression",
})


def make_callback_depth_compute(spec: TreeSitterLangSpec):
    """Create a compute function for max callback/closure nesting depth.

    Counts nested anonymous functions / arrow functions / lambdas.
    Separate from control-flow nesting — catches callback hell patterns.
    """
    _cached_parser: dict = {}

    def compute(content: str, lines: list[str], *, _filepath: str = "") -> tuple[int, str] | None:
        if not _filepath:
            return None

        if not _ensure_parser(_cached_parser, spec):
            return None

        parser = _cached_parser["parser"]

        cached = _PARSE_CACHE.get_or_parse(_filepath, parser, spec.grammar)
        if cached is None:
            return None
        _source, tree = cached

        max_depth = 0
        stack: list[tuple[object, int]] = [(tree.root_node, 0)]
        while stack:
            node, depth = stack.pop()
            if node.type in _CLOSURE_NODE_TYPES:
                depth += 1
                if depth > max_depth:
                    max_depth = depth
            for i in range(node.child_count - 1, -1, -1):
                stack.append((node.children[i], depth))

        if max_depth <= 1:
            return None
        return max_depth, f"callback depth {max_depth}"

    return compute


__all__ = [
    "compute_nesting_depth_ts",
    "make_callback_depth_compute",
    "make_cyclomatic_complexity_compute",
    "make_long_functions_compute",
    "make_max_params_compute",
    "make_nesting_depth_compute",
]
