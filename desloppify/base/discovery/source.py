"""Source-file discovery, exclusions, and scan-scoped content caching."""

from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import matches_exclusion
from desloppify.base.discovery.file_paths import (
    normalize_path_separators as _normalize_path_separators,
)
from desloppify.base.discovery.file_paths import (
    safe_relpath as _safe_relpath,
)
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.runtime_state import (
    FileTextReadResult,
    RuntimeContext,
    SourceFileCache,
    resolve_runtime_context,
)

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


@dataclass(frozen=True)
class SourceDiscoveryOptions:
    """Options bundle for source-file discovery and cache lookups."""

    exclusions: tuple[str, ...] | None = None
    extra_exclusions: tuple[str, ...] = ()
    project_root: Path | None = None
    source_file_cache: SourceFileCache | None = None


def set_exclusions(
    patterns: list[str],
    *,
    runtime: RuntimeContext | None = None,
) -> None:
    """Set global exclusion patterns (called once from CLI at startup)."""
    resolved_runtime = resolve_runtime_context(runtime)
    resolved_runtime.exclusions = tuple(patterns)
    resolved_runtime.source_file_cache.clear()


def get_exclusions(*, runtime: RuntimeContext | None = None) -> tuple[str, ...]:
    """Return current extra exclusion patterns."""
    return resolve_runtime_context(runtime).exclusions


def enable_file_cache(*, runtime: RuntimeContext | None = None) -> None:
    """Enable scan-scoped file content cache."""
    resolved_runtime = resolve_runtime_context(runtime)
    resolved_runtime.file_text_cache.enable()
    resolved_runtime.cache_enabled = True


def disable_file_cache(*, runtime: RuntimeContext | None = None) -> None:
    """Disable file content cache and free memory."""
    resolved_runtime = resolve_runtime_context(runtime)
    resolved_runtime.file_text_cache.disable()
    resolved_runtime.cache_enabled = False


@contextmanager
def file_cache_scope(*, runtime: RuntimeContext | None = None) -> Iterator[None]:
    """Temporarily enable file cache within a context, with nested safety."""
    resolved_runtime = resolve_runtime_context(runtime)
    was_enabled = resolved_runtime.cache_enabled
    if not was_enabled:
        enable_file_cache(runtime=resolved_runtime)
    try:
        yield
    finally:
        if not was_enabled:
            disable_file_cache(runtime=resolved_runtime)


def is_file_cache_enabled(*, runtime: RuntimeContext | None = None) -> bool:
    """Return whether scan-scoped file cache is currently enabled."""
    return resolve_runtime_context(runtime).cache_enabled


def read_file_text(filepath: str, *, runtime: RuntimeContext | None = None) -> str | None:
    """Read a file as text, with optional caching."""
    return resolve_runtime_context(runtime).file_text_cache.read(filepath)


def read_file_text_result(
    filepath: str,
    *,
    runtime: RuntimeContext | None = None,
) -> FileTextReadResult:
    """Read a file as text and include read-status metadata."""
    return resolve_runtime_context(runtime).file_text_cache.read_result(filepath)


def clear_source_file_cache_for_tests(*, runtime: RuntimeContext | None = None) -> None:
    resolve_runtime_context(runtime).source_file_cache.clear()


def collect_exclude_dirs(
    scan_root: Path,
    *,
    extra_exclusions: tuple[str, ...] | None = None,
    runtime: RuntimeContext | None = None,
) -> list[str]:
    """All exclusion directories as absolute paths, for passing to external tools.

    Combines DEFAULT_EXCLUSIONS (non-glob entries) + get_exclusions() (runtime/config),
    resolves each against *scan_root*. Filters out glob patterns (``*`` in name)
    since most CLI tools want plain directory paths.
    """
    resolved_exclusions = (
        extra_exclusions
        if extra_exclusions is not None
        else get_exclusions(runtime=runtime)
    )
    patterns = set()
    for pat in DEFAULT_EXCLUSIONS:
        if "*" not in pat:
            patterns.add(pat)
    patterns.update(p for p in resolved_exclusions if p and "*" not in p)
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
    options: SourceDiscoveryOptions | None = None,
    *,
    runtime: RuntimeContext | None = None,
) -> tuple[str, ...]:
    """Cached file discovery using os.walk with traversal-time pruning."""
    resolved_runtime = resolve_runtime_context(runtime)
    resolved_options = options or SourceDiscoveryOptions()
    resolved_project_root = (
        resolved_options.project_root.resolve()
        if resolved_options.project_root is not None
        else get_project_root(runtime=resolved_runtime)
    )
    cache = resolved_options.source_file_cache or resolved_runtime.source_file_cache
    cache_key = (
        path,
        extensions,
        resolved_options.exclusions,
        resolved_options.extra_exclusions,
        str(resolved_project_root),
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    root = Path(path)
    if not root.is_absolute():
        root = resolved_project_root / root
    all_exclusions = (
        (resolved_options.exclusions or ()) + resolved_options.extra_exclusions
    )
    ext_set = set(extensions)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = _normalize_path_separators(
            _safe_relpath(dirpath, resolved_project_root)
        )
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _is_excluded_dir(d, rel_dir + "/" + d, all_exclusions)
        )
        for fname in filenames:
            if any(fname.endswith(ext) for ext in ext_set):
                full = os.path.join(dirpath, fname)
                rel_file = _normalize_path_separators(
                    _safe_relpath(full, resolved_project_root)
                )
                if all_exclusions and any(
                    matches_exclusion(rel_file, ex) for ex in all_exclusions
                ):
                    continue
                files.append(rel_file)
    result = tuple(sorted(files))
    cache.put(cache_key, result)
    return result


def find_source_files(
    path: str | Path,
    extensions: list[str],
    options: SourceDiscoveryOptions | None = None,
    *,
    runtime: RuntimeContext | None = None,
) -> list[str]:
    """Find all files with given extensions under a path, excluding patterns."""
    resolved_runtime = resolve_runtime_context(runtime)
    resolved_options = options or SourceDiscoveryOptions()
    resolved_project_root = get_project_root(
        project_root=resolved_options.project_root,
        runtime=resolved_runtime,
    )
    resolved_extra_exclusions = (
        resolved_options.extra_exclusions
        if resolved_options.extra_exclusions
        else get_exclusions(runtime=resolved_runtime)
    )
    return list(
        _find_source_files_cached(
            str(path),
            tuple(extensions),
            SourceDiscoveryOptions(
                exclusions=resolved_options.exclusions,
                extra_exclusions=resolved_extra_exclusions,
                project_root=resolved_project_root,
                source_file_cache=resolved_options.source_file_cache,
            ),
            runtime=resolved_runtime,
        )
    )


def find_ts_files(path: str | Path, *, runtime: RuntimeContext | None = None) -> list[str]:
    """Find TypeScript ``.ts`` source files (excluding ``.tsx``)."""
    if runtime is None:
        return find_source_files(path, [".ts"])
    return find_source_files(path, [".ts"], runtime=runtime)


def find_ts_and_tsx_files(
    path: str | Path,
    *,
    runtime: RuntimeContext | None = None,
) -> list[str]:
    """Find TypeScript source files across ``.ts`` and ``.tsx`` extensions."""
    if runtime is None:
        return find_source_files(path, [".ts", ".tsx"])
    return find_source_files(path, [".ts", ".tsx"], runtime=runtime)


def find_tsx_files(path: str | Path, *, runtime: RuntimeContext | None = None) -> list[str]:
    if runtime is None:
        return find_source_files(path, [".tsx"])
    return find_source_files(path, [".tsx"], runtime=runtime)


def find_js_and_jsx_files(
    path: str | Path,
    *,
    runtime: RuntimeContext | None = None,
) -> list[str]:
    """Find JavaScript source files across common extensions."""
    exts = [".js", ".jsx", ".mjs", ".cjs"]
    if runtime is None:
        return find_source_files(path, exts)
    return find_source_files(path, exts, runtime=runtime)


def find_js_ts_and_tsx_files(
    path: str | Path,
    *,
    runtime: RuntimeContext | None = None,
) -> list[str]:
    """Find JavaScript + TypeScript source files across common extensions."""
    exts = [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]
    if runtime is None:
        return find_source_files(path, exts)
    return find_source_files(path, exts, runtime=runtime)


def find_py_files(path: str | Path, *, runtime: RuntimeContext | None = None) -> list[str]:
    if runtime is None:
        return find_source_files(path, [".py"])
    return find_source_files(path, [".py"], runtime=runtime)


__all__ = [
    "DEFAULT_EXCLUSIONS",
    "SourceDiscoveryOptions",
    "collect_exclude_dirs",
    "set_exclusions",
    "get_exclusions",
    "enable_file_cache",
    "disable_file_cache",
    "file_cache_scope",
    "is_file_cache_enabled",
    "read_file_text",
    "read_file_text_result",
    "clear_source_file_cache_for_tests",
    "find_source_files",
    "find_ts_files",
    "find_ts_and_tsx_files",
    "find_tsx_files",
    "find_js_and_jsx_files",
    "find_js_ts_and_tsx_files",
    "find_py_files",
]
