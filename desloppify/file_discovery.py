"""File discovery: source file finding, exclusion matching, and traversal caching."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.core.runtime_state import current_runtime_context


# Directories that are never useful to scan — always pruned during traversal.
DEFAULT_EXCLUSIONS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
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


def set_exclusions(patterns: list[str]):
    """Set global exclusion patterns (called once from CLI at startup)."""
    runtime = current_runtime_context()
    runtime.exclusion_config.values = tuple(patterns)
    runtime.source_file_cache.clear()


def get_exclusions() -> tuple[str, ...]:
    """Return current extra exclusion patterns."""
    return current_runtime_context().exclusion_config.values


def matches_exclusion(rel_path: str, exclusion: str) -> bool:
    """Check if a relative path matches an exclusion pattern (path-component aware).

    Matches if exclusion is a path component (e.g. "test" matches "test/foo.py"
    or "src/test/bar.py") or a directory prefix (e.g. "src/test" matches
    "src/test/bar.py"). Does NOT do substring matching — "test" will NOT match
    "testimony.py".
    """
    parts = Path(rel_path).parts
    if exclusion in parts:
        return True
    if "/" in exclusion or os.sep in exclusion:
        normalized = exclusion.rstrip("/").rstrip(os.sep)
        return rel_path.startswith(normalized + "/") or rel_path.startswith(
            normalized + os.sep
        )
    return False


def _normalize_path_separators(path: str) -> str:
    return path.replace("\\", "/")


def _safe_relpath(path: str | Path, start: str | Path) -> str:
    try:
        return os.path.relpath(str(path), str(start))
    except ValueError:
        return str(Path(path).resolve())


def rel(path: str) -> str:
    resolved = Path(path).resolve()
    try:
        return _normalize_path_separators(str(resolved.relative_to(PROJECT_ROOT)))
    except ValueError:
        return _normalize_path_separators(_safe_relpath(resolved, PROJECT_ROOT))


def resolve_path(filepath: str) -> str:
    """Resolve a filepath to absolute, handling both relative and absolute."""
    p = Path(filepath)
    if p.is_absolute():
        return str(p.resolve())
    return str((PROJECT_ROOT / filepath).resolve())


def safe_write_text(filepath: str | Path, content: str) -> None:
    """Atomically write text to a file using temp+rename."""
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, str(p))
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── File content cache & reading ──────────────────────────────


def enable_file_cache():
    """Enable scan-scoped file content cache."""
    runtime = current_runtime_context()
    runtime.file_text_cache.enable()
    runtime.cache_enabled.set(True)


def disable_file_cache():
    """Disable file content cache and free memory."""
    runtime = current_runtime_context()
    runtime.file_text_cache.disable()
    runtime.cache_enabled.set(False)


def is_file_cache_enabled() -> bool:
    """Return whether scan-scoped file cache is currently enabled."""
    return bool(current_runtime_context().cache_enabled)


def read_file_text(filepath: str) -> str | None:
    """Read a file as text, with optional caching."""
    return current_runtime_context().file_text_cache.read(filepath)


def _is_excluded_dir(name: str, rel_path: str, extra: tuple[str, ...]) -> bool:
    in_default_exclusions = name in DEFAULT_EXCLUSIONS or name.endswith(".egg-info")
    is_virtualenv_dir = name.startswith(".venv") or name.startswith("venv")
    matches_extra_exclusion = bool(
        extra
        and any(
            matches_exclusion(rel_path, exclusion) or exclusion == name
            for exclusion in extra
        )
    )
    return in_default_exclusions or is_virtualenv_dir or matches_extra_exclusion


def _clear_source_file_cache() -> None:
    current_runtime_context().source_file_cache.clear()


def _find_source_files_cached(
    path: str,
    extensions: tuple[str, ...],
    exclusions: tuple[str, ...] | None = None,
    extra_exclusions: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Cached file discovery using os.walk — cross-platform, prunes during traversal."""
    cache_key = (path, extensions, exclusions, extra_exclusions)
    cache = current_runtime_context().source_file_cache
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    root = Path(path)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    all_exclusions = (exclusions or ()) + extra_exclusions
    ext_set = set(extensions)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = _normalize_path_separators(_safe_relpath(dirpath, PROJECT_ROOT))
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _is_excluded_dir(d, rel_dir + "/" + d, all_exclusions)
        )
        for fname in filenames:
            if any(fname.endswith(ext) for ext in ext_set):
                full = os.path.join(dirpath, fname)
                rel_file = _normalize_path_separators(_safe_relpath(full, PROJECT_ROOT))
                if all_exclusions and any(
                    matches_exclusion(rel_file, ex) for ex in all_exclusions
                ):
                    continue
                files.append(rel_file)
    result = tuple(sorted(files))
    cache.put(cache_key, result)
    return result


_find_source_files_cached.cache_clear = _clear_source_file_cache


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
