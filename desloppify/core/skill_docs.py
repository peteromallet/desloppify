"""Skill-document versioning and install metadata helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from desloppify.core._internal.text_utils import get_project_root

# Bump this integer whenever docs/SKILL.md changes in a way that agents
# should pick up (new commands, changed workflows, removed sections).
SKILL_VERSION = 2

SKILL_VERSION_RE = re.compile(r"<!--\s*desloppify-skill-version:\s*(\d+)\s*-->")
SKILL_OVERLAY_RE = re.compile(r"<!--\s*desloppify-overlay:\s*(\w+)\s*-->")

SKILL_BEGIN = "<!-- desloppify-begin -->"
SKILL_END = "<!-- desloppify-end -->"

# Locations where the skill doc might be installed, relative to project root.
SKILL_SEARCH_PATHS = (
    ".claude/skills/desloppify/SKILL.md",
    ".opencode/skills/desloppify/SKILL.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/desloppify.md",
    ".github/copilot-instructions.md",
)

# Interface name → (target file, overlay filename, dedicated).
# Dedicated files are overwritten entirely; shared files get section replacement.
SKILL_TARGETS: dict[str, tuple[str, str, bool]] = {
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", True),
    # OpenCode support added with thanks to @H3xKatana.
    "opencode": (".opencode/skills/desloppify/SKILL.md", "OPENCODE", True),
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
    project_root = get_project_root()
    for rel_path in SKILL_SEARCH_PATHS:
        full = project_root / rel_path
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


__all__ = [
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
