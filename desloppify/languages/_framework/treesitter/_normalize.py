"""AST-aware body normalization for tree-sitter extracted functions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

# Pre-compiled once at module level, populated lazily.
_LOG_RE_CACHE: dict[tuple[str, ...], list[re.Pattern]] = {}


def _get_log_patterns(patterns: tuple[str, ...]) -> list[re.Pattern]:
    """Get compiled log patterns, caching by the frozen tuple key."""
    if patterns not in _LOG_RE_CACHE:
        _LOG_RE_CACHE[patterns] = [re.compile(p) for p in patterns]
    return _LOG_RE_CACHE[patterns]


def _collect_comment_ranges(node, comment_types: frozenset[str]) -> list[tuple[int, int]]:
    """Walk the AST and collect byte ranges of all comment nodes."""
    ranges: list[tuple[int, int]] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in comment_types:
            ranges.append((n.start_byte, n.end_byte))
        else:
            # Iterate children in reverse so we process them in order when popping.
            for i in range(n.child_count - 1, -1, -1):
                stack.append(n.children[i])
    return ranges


def _remove_byte_ranges(source: bytes, ranges: list[tuple[int, int]]) -> str:
    """Remove byte ranges from source, replacing with whitespace to preserve line structure."""
    if not ranges:
        return source.decode("utf-8", errors="replace")

    # Sort ranges by start position.
    ranges.sort()
    parts: list[bytes] = []
    pos = 0
    for start, end in ranges:
        if start > pos:
            parts.append(source[pos:start])
        # Replace comment bytes with spaces (preserves line positions).
        chunk = source[start:end]
        # Keep newlines, replace everything else with space.
        replacement = bytes(0x0A if b == 0x0A else 0x20 for b in chunk)
        parts.append(replacement)
        pos = end
    if pos < len(source):
        parts.append(source[pos:])
    return b"".join(parts).decode("utf-8", errors="replace")


def normalize_body(
    source_bytes: bytes,
    func_node,
    spec: TreeSitterLangSpec,
) -> str:
    """Strip comments, blank lines, and log lines from a function body using AST ranges.

    Returns the normalized text suitable for duplicate detection hashing.
    """
    # 1. Collect byte ranges of all comment nodes within the function.
    comment_ranges = _collect_comment_ranges(func_node, spec.comment_node_types)

    # 2. Remove comment ranges from the function source.
    func_source = source_bytes[func_node.start_byte : func_node.end_byte]
    # Adjust ranges to be relative to func_node.start_byte.
    offset = func_node.start_byte
    relative_ranges = [(s - offset, e - offset) for s, e in comment_ranges]
    text = _remove_byte_ranges(func_source, relative_ranges)

    # 3. Split into lines, strip blank/whitespace-only lines.
    lines = [line for line in text.splitlines() if line.strip()]

    # 4. Strip lines matching log patterns.
    log_res = _get_log_patterns(spec.log_patterns)
    if log_res:
        lines = [line for line in lines if not any(r.search(line) for r in log_res)]

    return "\n".join(lines)


__all__ = ["normalize_body"]
