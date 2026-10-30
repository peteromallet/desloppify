"""Shared tree-sitter spec types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TreeSitterLangSpec:
    """Per-language tree-sitter configuration."""

    grammar: str
    function_query: str
    comment_node_types: frozenset[str]
    string_node_types: frozenset[str] = frozenset()

    import_query: str = ""
    resolve_import: Callable[[str, str, str], str | None] | None = None
    # (imported name, regex) pairs: an import whose name never appears in the
    # file still counts as used when the regex matches, e.g. Kotlin operator
    # conventions (`getValue` is called by `by`, `contains` by `in`).
    implicit_import_uses: tuple[tuple[str, str], ...] = ()

    class_query: str = ""

    log_patterns: tuple[str, ...] = (
        r"^\s*(?:fmt\.Print|log\.)",
        r"^\s*(?:println!|eprintln!|dbg!)",
        r"^\s*(?:puts |p |pp )",
        r"^\s*(?:print\(|NSLog)",
        r"^\s*(?:System\.out\.|Logger\.)",
        r"^\s*console\.",
    )


__all__ = ["TreeSitterLangSpec"]
