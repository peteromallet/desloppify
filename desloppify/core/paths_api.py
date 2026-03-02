"""Public path and snippet helpers used by command/runtime code."""

from __future__ import annotations

import os
from pathlib import Path

from desloppify.core._internal import text_utils as _text_utils

_get_project_root = _text_utils.get_project_root

_PROJECT_ROOT_SENTINEL = _text_utils.PROJECT_ROOT
PROJECT_ROOT = _PROJECT_ROOT_SENTINEL
_DEFAULT_PATH_SENTINEL = PROJECT_ROOT / "src"
DEFAULT_PATH = _DEFAULT_PATH_SENTINEL
_SRC_PATH_SENTINEL = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")
SRC_PATH = _SRC_PATH_SENTINEL


def get_project_root() -> Path:
    """Return the runtime project root, honoring path API overrides."""
    if PROJECT_ROOT is not _PROJECT_ROOT_SENTINEL and isinstance(
        PROJECT_ROOT, Path | str
    ):
        return Path(PROJECT_ROOT).resolve()
    return _get_project_root()


def get_default_path() -> Path:
    """Return default scan path, honoring path API overrides."""
    if DEFAULT_PATH is not _DEFAULT_PATH_SENTINEL and isinstance(
        DEFAULT_PATH, Path | str
    ):
        return Path(DEFAULT_PATH).resolve()
    return get_project_root() / "src"


def get_src_path() -> Path:
    """Return TypeScript source root, honoring path API overrides."""
    if SRC_PATH is not _SRC_PATH_SENTINEL and isinstance(SRC_PATH, Path | str):
        return Path(SRC_PATH).resolve()
    return get_project_root() / os.environ.get("DESLOPPIFY_SRC", "src")


def read_code_snippet(filepath: str, line: int, context: int = 1) -> str | None:
    """Read a snippet around a 1-based line number."""
    return _text_utils.read_code_snippet(
        filepath,
        line,
        context,
        project_root=get_project_root(),
    )


def get_area(filepath: str, *, min_depth: int = 2) -> str:
    """Public wrapper for area derivation from a relative file path."""
    return _text_utils.get_area(filepath, min_depth=min_depth)


__all__ = [
    "PROJECT_ROOT",
    "DEFAULT_PATH",
    "SRC_PATH",
    "get_area",
    "get_project_root",
    "get_default_path",
    "get_src_path",
    "read_code_snippet",
]
