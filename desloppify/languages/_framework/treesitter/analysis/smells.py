"""Tree-sitter based cross-language smell detectors.

Detects universal anti-patterns via AST traversal:
- Empty catch/except blocks
- Unreachable code after return/break/continue/throw
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .. import PARSE_INIT_ERRORS
from ..imports.cache import get_or_parse_tree
from .extractors import _get_parser

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

logger = logging.getLogger(__name__)


# ── Empty catch/except blocks ─────────────────────────────────

# Node types for catch/except clauses across languages.
_CATCH_NODE_TYPES = frozenset({
    "catch_clause",       # Java, JS, C#, Kotlin, Dart
    "except_clause",      # Python
    "rescue",             # Ruby
    "rescue_clause",      # Elixir
    "catch",              # Erlang, Scala
    "handler",            # C++
})

# Node types for block bodies.
_BLOCK_NODE_TYPES = frozenset({
    "block", "statement_block", "compound_statement", "body",
    "clause_body", "do_block", "stab_clause",
})

# Node types to ignore when checking if a block is "empty".
_IGNORABLE_NODE_TYPES = frozenset({
    "comment", "{", "}", ":", "pass_statement", "do", "end",
    "catch", "rescue", "except", "finally",
})


def detect_empty_catches(
    file_list: list[str],
    spec: TreeSitterLangSpec,
) -> list[dict]:
    """Find empty catch/except blocks in source files.

    Returns list of {file, line, type} entries.
    """
    try:
        parser, language = _get_parser(spec.grammar)
    except PARSE_INIT_ERRORS as exc:
        logger.debug("tree-sitter init failed: %s", exc)
        return []

    entries: list[dict] = []
    for filepath in file_list:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
        if cached is None:
            continue
        _source, tree = cached

        # Walk the full AST looking for catch/except nodes.
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in _CATCH_NODE_TYPES:
                if _is_empty_handler(node):
                    entries.append({
                        "file": filepath,
                        "line": node.start_point[0] + 1,
                        "type": node.type,
                    })
            for i in range(node.child_count - 1, -1, -1):
                stack.append(node.children[i])

    return entries


def _is_empty_handler(catch_node) -> bool:
    """Check if a catch/except handler has an empty body."""
    # Find the block/body child.
    body = None
    for child in catch_node.children:
        if child.type in _BLOCK_NODE_TYPES:
            body = child
            break

    if body is None:
        # Some grammars inline the body as direct children of the catch clause.
        # Check if the catch node itself has only ignorable children.
        meaningful = [
            c for c in catch_node.children
            if c.type not in _IGNORABLE_NODE_TYPES
            and c.type not in _CATCH_NODE_TYPES
            and not c.type.startswith("catch")
            and not c.type.startswith("except")
        ]
        # If we found parameter nodes (like identifiers) but no statements, it's empty.
        has_statement = any(
            c.type.endswith("statement") or c.type.endswith("expression")
            for c in meaningful
        )
        return not has_statement and len(catch_node.children) > 0

    # Check if the body has any meaningful (non-comment, non-punctuation) children.
    for child in body.children:
        if child.type not in _IGNORABLE_NODE_TYPES:
            return False
    return True


# ── Unreachable code ──────────────────────────────────────────

# Node types that terminate control flow.
_TERMINATOR_TYPES = frozenset({
    "return_statement", "return",
    "break_statement", "break",
    "continue_statement", "continue",
    "throw_statement", "throw_expression",
    "raise_statement",
})

# Nodes emitted when the grammar loses sync with the source. Statement order
# around them is not trustworthy, so no unreachable-code claim can be made.
_PARSE_ERROR_NODE_TYPES = frozenset({"ERROR", "MISSING"})

# Declarations that are hoisted, so position relative to a terminator says
# nothing about reachability. C# local functions are routinely declared at the
# bottom of a method, after its `return`; JavaScript function declarations are
# likewise hoisted to the top of their scope.
_HOISTED_DECLARATION_NODE_TYPES = frozenset({
    "local_function_statement",  # C#
    "function_declaration",      # JavaScript
})

# Node types whose children form a statement sequence.
_SEQUENCE_NODE_TYPES = frozenset({
    "block", "statement_block", "compound_statement",
    "program", "module", "source_file", "compilation_unit",
    "body", "function_body", "method_body",
    "clause_body", "do_block",
    "switch_body",
})


def detect_unreachable_code(
    file_list: list[str],
    spec: TreeSitterLangSpec,
) -> list[dict]:
    """Find code after return/break/continue/throw in the same block.

    Returns list of {file, line, after} entries.
    """
    try:
        parser, language = _get_parser(spec.grammar)
    except PARSE_INIT_ERRORS as exc:
        logger.debug("tree-sitter init failed: %s", exc)
        return []

    entries: list[dict] = []
    for filepath in file_list:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
        if cached is None:
            continue
        _source, tree = cached

        # Walk the AST looking for sequence blocks.
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in _SEQUENCE_NODE_TYPES:
                _check_sequence_for_unreachable(node, filepath, entries)

            for i in range(node.child_count - 1, -1, -1):
                stack.append(node.children[i])

    return entries


def _check_sequence_for_unreachable(block_node, filepath: str, entries: list[dict]):
    """Check a statement sequence for code after terminators."""
    children = block_node.children
    saw_terminator = False
    terminator_type = ""

    for child in children:
        if child.type in _IGNORABLE_NODE_TYPES:
            continue

        if child.type in _HOISTED_DECLARATION_NODE_TYPES:
            # Reachable wherever it sits, and it does not make later statements
            # reachable either, so keep any pending terminator in play.
            continue

        if child.type in _PARSE_ERROR_NODE_TYPES:
            # The parse is unreliable from here on, so drop any pending
            # terminator rather than blaming the next node for being after it.
            saw_terminator = False
            continue

        if saw_terminator:
            # Code after terminator — this is unreachable.
            # Don't flag if the next node is itself a closing brace or similar.
            if child.type not in _IGNORABLE_NODE_TYPES and child.type not in (
                "}", "]", ")", "end", "else_clause", "elif_clause",
                "else", "elif", "catch_clause", "except_clause",
                "finally_clause", "case_clause", "default_clause",
                "rescue",
            ):
                entries.append({
                    "file": filepath,
                    "line": child.start_point[0] + 1,
                    "after": terminator_type,
                })
            # Only flag the first unreachable node per terminator.
            saw_terminator = False

        if child.type in _TERMINATOR_TYPES:
            saw_terminator = True
            terminator_type = child.type


__all__ = [
    "detect_empty_catches",
    "detect_unreachable_code",
]
