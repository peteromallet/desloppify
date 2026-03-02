"""Deprecated compatibility facade for legacy imports.

Use focused public APIs instead:
- ``desloppify.core.paths_api``
- ``desloppify.core.discovery_api``
- ``desloppify.core.output_api``
- ``desloppify.core.tooling``
- ``desloppify.core.skill_docs``

Compatibility exports remain for downstream callers and tests.
Planned removal: 2026-09-30 (or later major version).
"""

from __future__ import annotations

import warnings as _warnings
from pathlib import Path

_warnings.warn(
    "desloppify.utils is deprecated; use focused public APIs instead "
    "(desloppify.core.paths_api, discovery_api, output_api, tooling). "
    "Planned removal: 2026-09-30.",
    DeprecationWarning,
    stacklevel=2,
)

from desloppify.core.discovery_api import (
    DEFAULT_EXCLUSIONS,
    clear_source_file_cache_for_tests,
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
from desloppify.core.grep import grep_count_files, grep_files, grep_files_containing
from desloppify.core.output_api import (
    COLORS,
    LOC_COMPACT_THRESHOLD,
    NO_COLOR,
    colorize,
    display_entries,
    log,
    print_table,
)
from desloppify.core.paths_api import (
    DEFAULT_PATH,
    PROJECT_ROOT,
    SRC_PATH,
    get_default_path,
    get_project_root,
    get_src_path,
    read_code_snippet,
)
from desloppify.core.skill_docs import (
    SKILL_BEGIN,
    SKILL_END,
    SKILL_OVERLAY_RE,
    SKILL_SEARCH_PATHS,
    SKILL_TARGETS,
    SKILL_VERSION,
    SKILL_VERSION_RE,
    SkillInstall,
    check_skill_version,
    find_installed_skill,
)
from desloppify.core import tooling as _tooling

TOOL_DIR = _tooling.TOOL_DIR


def compute_tool_hash() -> str:
    """Compatibility wrapper honoring ``utils.TOOL_DIR`` test overrides."""
    return _tooling.compute_tool_hash(tool_dir=Path(TOOL_DIR))


def check_tool_staleness(state: dict) -> str | None:
    """Compatibility wrapper honoring ``utils.TOOL_DIR`` test overrides."""
    return _tooling.check_tool_staleness(state, tool_dir=Path(TOOL_DIR))

__all__ = [
    # Path constants + helpers
    "PROJECT_ROOT",
    "DEFAULT_PATH",
    "SRC_PATH",
    "get_project_root",
    "get_default_path",
    "get_src_path",
    "read_code_snippet",
    # Discovery helpers retained for legacy callsites
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
    # Grep helpers
    "grep_files",
    "grep_files_containing",
    "grep_count_files",
    # Output formatting
    "LOC_COMPACT_THRESHOLD",
    "COLORS",
    "NO_COLOR",
    "colorize",
    "log",
    "print_table",
    "display_entries",
    # Tool staleness
    "TOOL_DIR",
    "compute_tool_hash",
    "check_tool_staleness",
    # Skill document tracking
    "SKILL_VERSION",
    "SKILL_VERSION_RE",
    "SKILL_OVERLAY_RE",
    "SKILL_BEGIN",
    "SKILL_END",
    "SKILL_SEARCH_PATHS",
    "SKILL_TARGETS",
    "SkillInstall",
    "find_installed_skill",
    "check_skill_version",
]
