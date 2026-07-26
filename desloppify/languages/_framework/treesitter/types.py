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

    class_query: str = ""

    # Imports that a language resolves by *convention* rather than by name, so the
    # imported symbol never appears in the file body. Each entry is a
    # ``(name_pattern, body_pattern)`` pair: when an import's simple name matches
    # ``name_pattern`` and ``body_pattern`` is found in the file body, the import is
    # treated as used. Example: Kotlin's ``import ...getValue`` is required by
    # ``var x by remember { ... }`` but "getValue" is never written out.
    implicit_import_uses: tuple[tuple[str, str], ...] = ()

    log_patterns: tuple[str, ...] = (
        r"^\s*(?:fmt\.Print|log\.)",
        r"^\s*(?:println!|eprintln!|dbg!)",
        r"^\s*(?:puts |p |pp )",
        r"^\s*(?:print\(|NSLog)",
        r"^\s*(?:System\.out\.|Logger\.)",
        r"^\s*console\.",
    )


__all__ = ["TreeSitterLangSpec"]
