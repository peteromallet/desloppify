"""Skill-document versioning and install metadata helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root

# Bump this integer whenever docs/SKILL.md changes in a way that agents
# should pick up (new commands, changed workflows, removed sections).
SKILL_VERSION = 8

SKILL_VERSION_RE = re.compile(r"<!--\s*desloppify-skill-version:\s*(\d+)\s*-->")
SKILL_OVERLAY_RE = re.compile(r"<!--\s*desloppify-overlay:\s*(\w+)\s*-->")

SKILL_BEGIN = "<!-- desloppify-begin -->"
SKILL_END = "<!-- desloppify-end -->"

# Locations where the skill doc might be installed, relative to project root.
SKILL_SEARCH_PATHS = (
    ".factory/skills/desloppify/SKILL.md",
    ".agents/skills/desloppify/SKILL.md",
    ".claude/skills/desloppify/SKILL.md",
    ".opencode/skills/desloppify/SKILL.md",
    ".qwen/skills/desloppify/SKILL.md",
    ".rovodev/skills/desloppify/SKILL.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/desloppify.md",
    ".github/copilot-instructions.md",
)

# Interface name → (target file, overlay filename, dedicated).
# Dedicated files are overwritten entirely; shared files get section replacement.
SKILL_TARGETS: dict[str, tuple[str, str, bool]] = {
    "amp": (".agents/skills/desloppify/SKILL.md", "AMP", True),
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", True),
    # OpenCode support added with thanks to @H3xKatana.
    "opencode": (".opencode/skills/desloppify/SKILL.md", "OPENCODE", True),
    "qwen": (".qwen/skills/desloppify/SKILL.md", "QWEN", True),
    "codex": (".agents/skills/desloppify/SKILL.md", "CODEX", True),
    "cursor": (".cursor/rules/desloppify.md", "CURSOR", True),
    "copilot": (".github/copilot-instructions.md", "COPILOT", False),
    "droid": (".factory/skills/desloppify/SKILL.md", "DROID", True),
    "rovodev": (".rovodev/skills/desloppify/SKILL.md", "ROVODEV", True),
    "windsurf": ("AGENTS.md", "WINDSURF", False),
    "gemini": ("AGENTS.md", "GEMINI", False),
    "hermes": ("AGENTS.md", "HERMES", False),
}

# Global (user-level) skill install targets.
# Single source of truth — setup/cmd.py imports this.
# interface -> (path relative to ~/, overlay name, tool config dir to check, dedicated)
#
# Verified against official docs (2026-03-22):
#   claude:   code.claude.com/docs/en/skills
#   codex:    developers.openai.com/codex/guides/agents-md
#   gemini:   geminicli.com/docs/cli/skills/
#   amp:      ampcode.com/news/agent-skills
#   opencode: opencode.ai/docs/skills/
#   qwen:     qwenlm.github.io/qwen-code-docs/en/users/features/skills/
#   rovodev:  support.atlassian.com/rovo/docs/extend-rovo-dev-cli-with-agent-skills/
#
# Cursor is excluded — global rules are UI-only (cursor.com/docs/rules).
GLOBAL_TARGETS: dict[str, tuple[str, str, str, bool]] = {
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", ".claude", True),
    "codex": (".codex/AGENTS.md", "CODEX", ".codex", False),
    "gemini": (".gemini/skills/desloppify/SKILL.md", "GEMINI", ".gemini", True),
    "amp": (".config/agents/skills/desloppify/SKILL.md", "AMP", ".config/agents", True),
    "opencode": (
        ".config/opencode/skills/desloppify/SKILL.md",
        "OPENCODE",
        ".config/opencode",
        True,
    ),
    "qwen": (".qwen/skills/desloppify/SKILL.md", "QWEN", ".qwen", True),
    "rovodev": (
        ".rovodev/skills/desloppify/SKILL.md",
        "ROVODEV",
        ".rovodev",
        True,
    ),
}


@dataclass
class SkillInstall:
    """Detected skill document installation."""

    rel_path: str
    version: int
    overlay: str | None
    stale: bool


def _parse_skill_content(rel_path: str, content: str) -> SkillInstall | None:
    """Extract version/overlay metadata from skill file content."""
    version_match = SKILL_VERSION_RE.search(content)
    if not version_match:
        return None
    installed_version = int(version_match.group(1))
    overlay_match = SKILL_OVERLAY_RE.search(content)
    overlay = overlay_match.group(1) if overlay_match else None
    return SkillInstall(
        rel_path=rel_path,
        version=installed_version,
        overlay=overlay,
        stale=installed_version < SKILL_VERSION,
    )


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
        install = _parse_skill_content(rel_path, content)
        if install is not None:
            return install
    return None


def _scan_global_installs() -> list[SkillInstall]:
    """Find all globally-installed skill documents."""
    home = Path.home()
    results: list[SkillInstall] = []
    for rel_path, _overlay, _check_dir, _dedicated in GLOBAL_TARGETS.values():
        full = home / rel_path
        if not full.is_file():
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        install = _parse_skill_content(f"~/{rel_path}", content)
        if install is not None:
            results.append(install)
    return results


def find_stale_global_installs() -> list[SkillInstall]:
    """Return all globally-installed skill documents that are stale."""
    return [i for i in _scan_global_installs() if i.stale]


def find_any_global_install() -> bool:
    """Return True if any global skill install exists (stale or current)."""
    return bool(_scan_global_installs())


def check_skill_version() -> str | None:
    """Return a warning if installed skill doc is outdated."""
    # Per-project takes precedence (it's what the tool loads in-project).
    install = find_installed_skill()
    if install:
        if not install.stale:
            return None
        return (
            f"Your desloppify skill document is outdated "
            f"(v{install.version}, current v{SKILL_VERSION}). "
            "Run: desloppify update-skill"
        )
    # Check global installs.
    stale_globals = find_stale_global_installs()
    if stale_globals:
        return (
            f"Your global desloppify skill is outdated "
            f"(v{stale_globals[0].version}, current v{SKILL_VERSION}). "
            "Run: desloppify setup"
        )
    return None


__all__ = [
    "SKILL_VERSION",
    "SKILL_VERSION_RE",
    "SKILL_OVERLAY_RE",
    "SKILL_BEGIN",
    "SKILL_END",
    "SKILL_SEARCH_PATHS",
    "SKILL_TARGETS",
    "GLOBAL_TARGETS",
    "SkillInstall",
    "find_installed_skill",
    "find_stale_global_installs",
    "find_any_global_install",
    "check_skill_version",
]
