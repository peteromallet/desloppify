"""Deprecated compatibility facade for discovery/path APIs.

Use ``desloppify.core.discovery_api`` for new imports.
Compatibility exports remain for downstream callers and tests.
Planned removal: 2026-09-30 (or later major version).
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "desloppify.file_discovery is deprecated; use desloppify.core.discovery_api instead. "
    "Planned removal: 2026-09-30.",
    DeprecationWarning,
    stacklevel=2,
)

from desloppify.core.discovery_api import (
    clear_source_file_cache_for_tests,
    DEFAULT_EXCLUSIONS,
    disable_file_cache,
    enable_file_cache,
    find_py_files,
    find_source_files,
    find_ts_files,
    find_tsx_files,
    get_exclusions,
    is_file_cache_enabled,
    matches_exclusion,
    read_file_text,
    rel,
    resolve_path,
    safe_write_text,
    set_exclusions,
)

__all__ = [
    "DEFAULT_EXCLUSIONS",
    "set_exclusions",
    "get_exclusions",
    "matches_exclusion",
    "rel",
    "resolve_path",
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
