"""Compatibility facade over focused core utility modules."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from desloppify.core import tooling as _tooling
from desloppify.core._internal import text_utils as _text_utils
from desloppify.core.grep import grep_count_files, grep_files, grep_files_containing
from desloppify.core.output import (
    COLORS,
    LOC_COMPACT_THRESHOLD,
    NO_COLOR,
    colorize,
    display_entries,
    log,
    print_table,
)

__all__ = [
    # Path constants
    "PROJECT_ROOT",
    "DEFAULT_PATH",
    "SRC_PATH",
    # Grep helpers
    "read_code_snippet",
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

_get_project_root = _text_utils.get_project_root

PROJECT_ROOT = _text_utils.PROJECT_ROOT
DEFAULT_PATH = PROJECT_ROOT / "src"
SRC_PATH = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")
TOOL_DIR = _tooling.TOOL_DIR


def read_code_snippet(filepath: str, line: int, context: int = 1) -> str | None:
    """Read a snippet around a 1-based line number."""
    return _text_utils.read_code_snippet(
        filepath,
        line,
        context,
        project_root=_get_project_root(),
    )


def compute_tool_hash() -> str:
    """Compute a content hash of tool code honoring ``utils.TOOL_DIR`` overrides."""
    original_tool_dir = _tooling.TOOL_DIR
    _tooling.TOOL_DIR = TOOL_DIR
    try:
        return _tooling.compute_tool_hash()
    finally:
        _tooling.TOOL_DIR = original_tool_dir


def check_tool_staleness(state: dict) -> str | None:
    """Return warning if tool code changed, honoring ``utils.TOOL_DIR`` overrides."""
    original_tool_dir = _tooling.TOOL_DIR
    _tooling.TOOL_DIR = TOOL_DIR
    try:
        return _tooling.check_tool_staleness(state)
    finally:
        _tooling.TOOL_DIR = original_tool_dir


# ── Skill document version tracking ─────────────────────────
# Bump this integer whenever docs/SKILL.md changes in a way that agents
# should pick up (new commands, changed workflows, removed sections).
SKILL_VERSION = 1

SKILL_VERSION_RE = re.compile(r"<!--\s*desloppify-skill-version:\s*(\d+)\s*-->")
SKILL_OVERLAY_RE = re.compile(r"<!--\s*desloppify-overlay:\s*(\w+)\s*-->")

SKILL_BEGIN = "<!-- desloppify-begin -->"
SKILL_END = "<!-- desloppify-end -->"

# Locations where the skill doc might be installed, relative to PROJECT_ROOT.
SKILL_SEARCH_PATHS = (
    ".claude/skills/desloppify/SKILL.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/desloppify.md",
    ".github/copilot-instructions.md",
)

# Interface name → (target file, overlay filename, dedicated).
# Dedicated files are overwritten entirely; shared files get section replacement.
SKILL_TARGETS: dict[str, tuple[str, str, bool]] = {
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", True),
    "codex": ("AGENTS.md", "CODEX", False),
    "cursor": (".cursor/rules/desloppify.md", "CURSOR", True),
    "copilot": (".github/copilot-instructions.md", "COPILOT", False),
    "windsurf": ("AGENTS.md", "WINDSURF", False),
    "gemini": ("AGENTS.md", "GEMINI", False),
}


@dataclass
class SkillInstall:
    """Detected skill document installation."""

    rel_path: str
    version: int
    overlay: str | None
    stale: bool


def find_installed_skill() -> SkillInstall | None:
    """Find installed skill document metadata, or None."""
    for rel_path in SKILL_SEARCH_PATHS:
        full = _get_project_root() / rel_path
        if not full.is_file():
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        version_match = SKILL_VERSION_RE.search(content)
        if not version_match:
            continue
        installed_version = int(version_match.group(1))
        overlay_match = SKILL_OVERLAY_RE.search(content)
        overlay = overlay_match.group(1) if overlay_match else None
        return SkillInstall(
            rel_path=rel_path,
            version=installed_version,
            overlay=overlay,
            stale=installed_version < SKILL_VERSION,
        )
    return None


def check_skill_version() -> str | None:
    """Return a warning if installed skill doc is outdated."""
    install = find_installed_skill()
    if not install or not install.stale:
        return None
    return (
        f"Your desloppify skill document is outdated "
        f"(v{install.version}, current v{SKILL_VERSION}). "
        "Run: desloppify update-skill"
    )
