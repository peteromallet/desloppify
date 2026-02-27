"""Public discovery + file-path helpers for scan/review flows."""

from __future__ import annotations

from desloppify.core.file_paths import (
    matches_exclusion,
    rel,
    resolve_path,
    resolve_scan_file,
    safe_write_text,
)
from desloppify.core.source_discovery import (
    clear_source_file_cache_for_tests,
    collect_exclude_dirs,
    DEFAULT_EXCLUSIONS,
    disable_file_cache,
    enable_file_cache,
    find_py_files,
    find_source_files,
    find_ts_files,
    find_tsx_files,
    get_exclusions,
    is_file_cache_enabled,
    read_file_text,
    set_exclusions,
)

__all__ = [
    "DEFAULT_EXCLUSIONS",
    "collect_exclude_dirs",
    "set_exclusions",
    "get_exclusions",
    "matches_exclusion",
    "rel",
    "resolve_path",
    "resolve_scan_file",
    "safe_write_text",
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
