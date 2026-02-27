"""Source-file discovery, exclusions, and scan-scoped content caching."""

from __future__ import annotations

import os
from pathlib import Path

from desloppify.core._internal.text_utils import get_project_root
from desloppify.core.file_paths import matches_exclusion
from desloppify.core.file_paths import (
    normalize_path_separators as _normalize_path_separators,
)
from desloppify.core.file_paths import (
    safe_relpath as _safe_relpath,
)
from desloppify.core.runtime_state import current_runtime_context

# Directories that are never useful to scan — always pruned during traversal.
DEFAULT_EXCLUSIONS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        ".venv*",
        "venv",
        ".env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".output",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
        "*.egg-info",
        ".svn",
        ".hg",
    }
)


def set_exclusions(patterns: list[str]) -> None:
    """Set global exclusion patterns (called once from CLI at startup)."""
    runtime = current_runtime_context()
    runtime.exclusions = tuple(patterns)
    runtime.source_file_cache.clear()


def get_exclusions() -> tuple[str, ...]:
    """Return current extra exclusion patterns."""
    return current_runtime_context().exclusions


def enable_file_cache() -> None:
    """Enable scan-scoped file content cache."""
    runtime = current_runtime_context()
    runtime.file_text_cache.enable()
    runtime.cache_enabled = True


def disable_file_cache() -> None:
    """Disable file content cache and free memory."""
    runtime = current_runtime_context()
    runtime.file_text_cache.disable()
    runtime.cache_enabled = False


def is_file_cache_enabled() -> bool:
    """Return whether scan-scoped file cache is currently enabled."""
    return current_runtime_context().cache_enabled


def read_file_text(filepath: str) -> str | None:
    """Read a file as text, with optional caching."""
    return current_runtime_context().file_text_cache.read(filepath)


def clear_source_file_cache_for_tests() -> None:
    current_runtime_context().source_file_cache.clear()


def collect_exclude_dirs(scan_root: Path) -> list[str]:
    """All exclusion directories as absolute paths, for passing to external tools.

    Combines DEFAULT_EXCLUSIONS (non-glob entries) + get_exclusions() (runtime/config),
    resolves each against *scan_root*. Filters out glob patterns (``*`` in name)
    since most CLI tools want plain directory paths.
    """
    patterns = set()
    for pat in DEFAULT_EXCLUSIONS:
        if "*" not in pat:
            patterns.add(pat)
    patterns.update(p for p in get_exclusions() if p and "*" not in p)
    return [str(scan_root / p) for p in sorted(patterns) if p]


def _is_excluded_dir(name: str, rel_path: str, extra: tuple[str, ...]) -> bool:
    in_default_exclusions = name in DEFAULT_EXCLUSIONS or name.endswith(".egg-info")
    is_virtualenv_dir = name.startswith(".venv") or name.startswith("venv")
    matches_extra_exclusion = bool(
        extra
        and any(
            matches_exclusion(rel_path, exclusion)
            or exclusion == name
            or exclusion == name + "/**"
            or exclusion == name + "/*"
            for exclusion in extra
        )
    )
    return in_default_exclusions or is_virtualenv_dir or matches_extra_exclusion


def _find_source_files_cached(
    path: str,
    extensions: tuple[str, ...],
    exclusions: tuple[str, ...] | None = None,
    extra_exclusions: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Cached file discovery using os.walk with traversal-time pruning."""
    cache_key = (path, extensions, exclusions, extra_exclusions)
    cache = current_runtime_context().source_file_cache
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    project_root = get_project_root()
    root = Path(path)
    if not root.is_absolute():
        root = project_root / root
    all_exclusions = (exclusions or ()) + extra_exclusions
    ext_set = set(extensions)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = _normalize_path_separators(_safe_relpath(dirpath, project_root))
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _is_excluded_dir(d, rel_dir + "/" + d, all_exclusions)
        )
        for fname in filenames:
            if any(fname.endswith(ext) for ext in ext_set):
                full = os.path.join(dirpath, fname)
                rel_file = _normalize_path_separators(_safe_relpath(full, project_root))
                if all_exclusions and any(
                    matches_exclusion(rel_file, ex) for ex in all_exclusions
                ):
                    continue
                files.append(rel_file)
    result = tuple(sorted(files))
    cache.put(cache_key, result)
    return result


def find_source_files(
    path: str | Path, extensions: list[str], exclusions: list[str] | None = None
) -> list[str]:
    """Find all files with given extensions under a path, excluding patterns."""
    return list(
        _find_source_files_cached(
            str(path),
            tuple(extensions),
            tuple(exclusions) if exclusions else None,
            get_exclusions(),
        )
    )


def find_ts_files(path: str | Path) -> list[str]:
    return find_source_files(path, [".ts", ".tsx"])


def find_tsx_files(path: str | Path) -> list[str]:
    return find_source_files(path, [".tsx"])


def find_py_files(path: str | Path) -> list[str]:
    return find_source_files(path, [".py"])


__all__ = [
    "DEFAULT_EXCLUSIONS",
    "collect_exclude_dirs",
    "set_exclusions",
    "get_exclusions",
    "enable_file_cache",
    "disable_file_cache",
    "is_file_cache_enabled",
    "read_file_text",
    "clear_source_file_cache_for_tests",
    "find_source_files",
    "find_ts_files",
    "find_tsx_files",
    "find_py_files",
]
