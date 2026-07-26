"""Shared primitives for Python dict-key detector components."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class TrackedDict:
    """A dict variable tracked within a single scope."""

    name: str
    created_line: int
    locally_created: bool
    returned_or_passed: bool = False
    has_dynamic_key: bool = False
    has_star_unpack: bool = False
    keyset_is_open: bool = False
    writes: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    reads: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    bulk_read: bool = False


_CONFIG_NAMES = {
    "config",
    "settings",
    "defaults",
    "options",
    "kwargs",
    "context",
    "ctx",
    "env",
    "params",
    "metadata",
    "headers",
    "attrs",
    "attributes",
    "props",
    "properties",
}

_READ_METHODS = {"get", "pop", "setdefault", "__getitem__", "__contains__"}
_WRITE_METHODS = {"update", "setdefault", "__setitem__"}
_BULK_READ_METHODS = {"keys", "values", "items", "copy", "__iter__"}


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _is_singular_plural(a: str, b: str) -> bool:
    """Check if a and b are singular/plural variants of each other."""
    return (
        a + "s" == b
        or b + "s" == a
        or a + "es" == b
        or b + "es" == a
        or (a.endswith("ies") and a[:-3] + "y" == b)
        or (b.endswith("ies") and b[:-3] + "y" == a)
    )


def _get_name(node: ast.expr) -> str | None:
    """Extract variable name from a Name or Attribute(self.x) node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _get_str_key(node: ast.expr) -> str | None:
    """Extract a string literal from a subscript slice."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
