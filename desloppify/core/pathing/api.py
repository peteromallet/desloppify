"""Canonical path and snippet API surface."""

from __future__ import annotations

import os
from pathlib import Path

from desloppify.core import file_paths as file_paths_mod
from desloppify.core._internal import text_utils as _text_utils
from desloppify.core._internal.path_proxy import DynamicPathProxy


PROJECT_ROOT = _text_utils.PROJECT_ROOT
DEFAULT_PATH = DynamicPathProxy(
    lambda: get_project_root() / "src",
    label="DEFAULT_PATH",
)
SRC_PATH = DynamicPathProxy(
    lambda: get_project_root() / os.environ.get("DESLOPPIFY_SRC", "src"),
    label="SRC_PATH",
)


def get_project_root() -> Path:
    """Return the active runtime project root."""
    return _text_utils.get_project_root()


def get_default_path() -> Path:
    """Return default scan path from runtime root."""
    return get_project_root() / "src"


def get_src_path() -> Path:
    """Return configured source path from runtime root."""
    return get_project_root() / os.environ.get("DESLOPPIFY_SRC", "src")


def read_code_snippet(
    filepath: str,
    line: int,
    context: int = 1,
    *,
    project_root: Path | str | None = None,
) -> str | None:
    """Read a snippet around a 1-based line number."""
    return _text_utils.read_code_snippet(
        filepath,
        line,
        context,
        project_root=project_root if project_root is not None else get_project_root(),
    )


def matches_exclusion(rel_path: str, exclusion: str) -> bool:
    """Check if a relative path matches an exclusion pattern."""
    return file_paths_mod.matches_exclusion(rel_path, exclusion)


def normalize_path_separators(path: str) -> str:
    """Normalize path separators to forward slashes for stable display."""
    return file_paths_mod.normalize_path_separators(path)


def safe_relpath(path: str | Path, start: str | Path) -> str:
    """Best-effort relpath helper that tolerates drive boundary mismatches."""
    return file_paths_mod.safe_relpath(path, start)


def rel(path: str) -> str:
    """Return project-root-relative path using normalized separators."""
    return file_paths_mod.rel(path)


def resolve_path(filepath: str) -> str:
    """Resolve filepath to an absolute path from the active project root."""
    return file_paths_mod.resolve_path(filepath)


def resolve_scan_file(
    filepath: str | Path,
    *,
    scan_root: str | Path | None = None,
) -> Path:
    """Resolve a scan candidate path using scan-root-first semantics."""
    return file_paths_mod.resolve_scan_file(filepath, scan_root=scan_root)


def safe_write_text(filepath: str | Path, content: str) -> None:
    """Atomically write text content using temp+rename."""
    file_paths_mod.safe_write_text(filepath, content)


__all__ = [
    "PROJECT_ROOT",
    "DEFAULT_PATH",
    "SRC_PATH",
    "get_project_root",
    "get_default_path",
    "get_src_path",
    "read_code_snippet",
    "matches_exclusion",
    "normalize_path_separators",
    "safe_relpath",
    "rel",
    "resolve_path",
    "resolve_scan_file",
    "safe_write_text",
]
