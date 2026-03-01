"""Deprecated compatibility facade for legacy imports.

Use focused public APIs instead:
- ``desloppify.core.pathing.api``
- ``desloppify.core.discovery.api``
- ``desloppify.core.io.api``
- ``desloppify.core.tooling``
- ``desloppify.core.skill_docs``

Compatibility exports remain for downstream callers and tests.
Planned removal: 2026-09-30 (or later major version).
"""

from __future__ import annotations

from pathlib import Path

from desloppify.core.discovery import api as _discovery_api
from desloppify.core.grep import grep_count_files, grep_files, grep_files_containing
from desloppify.core.io.api import (
    COLORS,
    LOC_COMPACT_THRESHOLD,
    NO_COLOR,
    colorize,
    display_entries,
    log,
    print_table,
)
from desloppify.core.pathing import api as _pathing_api
from desloppify.core.pathing.api import (
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
_LEGACY_DISCOVERY_EXPORTS = frozenset(
    {
        "DEFAULT_EXCLUSIONS",
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
    }
)
_LEGACY_PATHING_EXPORTS = frozenset(
    {
        "matches_exclusion",
        "rel",
        "resolve_path",
        "safe_write_text",
    }
)


def compute_tool_hash() -> str:
    """Compatibility wrapper honoring ``utils.TOOL_DIR`` test overrides."""
    return _tooling.compute_tool_hash(tool_dir=Path(TOOL_DIR))


def check_tool_staleness(state: dict) -> str | None:
    """Compatibility wrapper honoring ``utils.TOOL_DIR`` test overrides."""
    return _tooling.check_tool_staleness(state, tool_dir=Path(TOOL_DIR))


def __getattr__(name: str):
    """Lazily serve legacy discovery exports for compatibility callers."""
    if name in _LEGACY_DISCOVERY_EXPORTS:
        return getattr(_discovery_api, name)
    if name in _LEGACY_PATHING_EXPORTS:
        return getattr(_pathing_api, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Path constants + helpers
    "PROJECT_ROOT",
    "DEFAULT_PATH",
    "SRC_PATH",
    "get_project_root",
    "get_default_path",
    "get_src_path",
    "read_code_snippet",
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
