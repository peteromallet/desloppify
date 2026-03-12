"""C/C++ move helpers."""

from __future__ import annotations

from desloppify.languages._framework.scaffold_move import (
    find_replacements as scaffold_find_replacements,
    find_self_replacements as scaffold_find_self_replacements,
)

VERIFY_HINT = "desloppify --lang cxx detect deps"


def find_replacements(
    source_abs: str,
    dest_abs: str,
    graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """Return importer replacements for a moved C/C++ file."""
    return scaffold_find_replacements(source_abs, dest_abs, graph)


def find_self_replacements(
    source_abs: str,
    dest_abs: str,
    graph: dict,
) -> list[tuple[str, str]]:
    """Return self-import replacements for a moved C/C++ file."""
    return scaffold_find_self_replacements(source_abs, dest_abs, graph)


def filter_intra_package_importer_changes(
    source_file: str,
    replacements: list[tuple[str, str]],
    moving_files: set[str],
) -> list[tuple[str, str]]:
    """Keep importer replacements unchanged for C/C++ until include rewrites land."""
    del source_file, moving_files
    return replacements


def filter_directory_self_changes(
    source_file: str,
    self_changes: list[tuple[str, str]],
    moving_files: set[str],
) -> list[tuple[str, str]]:
    """Keep self-import replacements unchanged for directory moves."""
    del source_file, moving_files
    return self_changes


def get_verify_hint() -> str:
    """Return the default verification command after a C/C++ move."""
    return VERIFY_HINT


__all__ = [
    "VERIFY_HINT",
    "filter_directory_self_changes",
    "filter_intra_package_importer_changes",
    "find_replacements",
    "find_self_replacements",
    "get_verify_hint",
]
