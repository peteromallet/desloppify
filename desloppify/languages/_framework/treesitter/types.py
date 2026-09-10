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

    # Optional query capturing a file's package/namespace as @package.
    # When set, same-package references (which need no import in JVM-style
    # languages) are registered as importers of the declaring file.
    package_query: str = ""

    # Optional query capturing every top-level declaration as @decl with its
    # @name — used together with package_query for same-package references.
    # Unlike class_query/function_query it must not require a body, so
    # body-less declarations (data classes, interfaces) are included.
    top_level_name_query: str = ""

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
