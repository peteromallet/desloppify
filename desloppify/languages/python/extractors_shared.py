"""Shared helpers for Python extractors."""

from __future__ import annotations

from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT


def read_file(filepath: str) -> str | None:
    """Read a file, returning None on error."""
    path = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def find_block_end(
    lines: list[str],
    start: int,
    base_indent: int,
    limit: int | None = None,
) -> int:
    """Find end of an indented block (first line at or below base indent)."""
    end = limit if limit is not None else len(lines)
    index = start
    while index < end:
        if lines[index].strip() == "":
            index += 1
            continue
        if len(lines[index]) - len(lines[index].lstrip()) <= base_indent:
            break
        index += 1
    return index


def extract_py_params(param_str: str) -> list[str]:
    """Extract parameter names from a Python function signature."""
    params = []
    for token in " ".join(param_str.split()).split(","):
        token = token.strip()
        if not token or token in ("self", "cls"):
            continue
        name = token.lstrip("*").split(":")[0].split("=")[0].strip()
        if name and name.isidentifier():
            params.append(name)
    return params


__all__ = ["extract_py_params", "find_block_end", "read_file"]
