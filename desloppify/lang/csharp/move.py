"""C# move helpers."""

from __future__ import annotations


VERIFY_HINT = "dotnet build"


def find_replacements(
    _source_abs: str, _dest_abs: str, _graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """C# import/namespace rewrites are not implemented yet."""
    return {}


def find_self_replacements(
    _source_abs: str, _dest_abs: str, _graph: dict,
) -> list[tuple[str, str]]:
    """No self-import rewrites for C# at this time."""
    return []


def filter_intra_package_importer_changes(
    _source_file: str, replacements: list[tuple[str, str]], _moving_files: set[str],
) -> list[tuple[str, str]]:
    """Return replacements unchanged for C#."""
    return replacements


def filter_directory_self_changes(
    _source_file: str, self_changes: list[tuple[str, str]], _moving_files: set[str],
) -> list[tuple[str, str]]:
    """Return self changes unchanged for C#."""
    return self_changes
