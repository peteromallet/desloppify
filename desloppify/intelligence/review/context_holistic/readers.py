"""File-system readers for holistic review context."""

from __future__ import annotations

from desloppify.utils import read_file_text, resolve_path


def _abs(filepath: str) -> str:
    """Resolve filepath to absolute using resolve_path."""
    return resolve_path(filepath)


def _read_file_contents(files: list[str]) -> dict[str, str]:
    file_contents: dict[str, str] = {}
    for filepath in files:
        content = read_file_text(_abs(filepath))
        if content is not None:
            file_contents[filepath] = content
    return file_contents
