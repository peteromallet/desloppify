"""Skill-document versioning and install metadata helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from desloppify.base.discovery.paths import get_project_root

# Bump this integer whenever docs/SKILL.md changes in a way that agents
# should pick up (new commands, changed workflows, removed sections).
SKILL_VERSION = 6

SKILL_VERSION_RE = re.compile(r"<!--\s*desloppify-skill-version:\s*(\d+)\s*-->")
SKILL_OVERLAY_RE = re.compile(r"<!--\s*desloppify-overlay:\s*(\w+)\s*-->")

SKILL_BEGIN = "<!-- desloppify-begin -->"
SKILL_END = "<!-- desloppify-end -->"

SkillScope = Literal["user", "project"]
SkillSourceKind = Literal["canonical_user", "legacy_project", "shared_file"]


@dataclass(frozen=True)
class SkillTarget:
    """One writable skill target for an interface."""

    interface: str
    scope: SkillScope
    rel_path: str
    overlay_name: str
    dedicated: bool
    source_kind: SkillSourceKind
    canonical: bool

    def absolute_path(
        self,
        *,
        project_root: Path | None = None,
        home: Path | None = None,
    ) -> Path:
        if self.scope == "user":
            base = home if home is not None else Path.home()
            return base / self.rel_path
        base = project_root if project_root is not None else get_project_root()
        return base / self.rel_path


@dataclass(frozen=True)
class SkillInstall:
    """Detected skill document installation."""

    rel_path: str
    absolute_path: Path
    interface: str | None
    scope: SkillScope
    source_kind: SkillSourceKind
    canonical: bool
    version: int
    overlay: str | None
    stale: bool


SKILL_TARGETS: dict[str, tuple[str, str, bool]] = {
    "amp": (".agents/skills/desloppify/SKILL.md", "AMP", True),
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", True),
    "opencode": (".opencode/skills/desloppify/SKILL.md", "OPENCODE", True),
    "codex": (".codex/skills/desloppify/SKILL.md", "CODEX", True),
    "cursor": (".cursor/rules/desloppify.md", "CURSOR", True),
    "copilot": (".github/copilot-instructions.md", "COPILOT", False),
    "windsurf": ("AGENTS.md", "WINDSURF", False),
    "gemini": ("AGENTS.md", "GEMINI", False),
    "hermes": ("AGENTS.md", "HERMES", False),
}

SKILL_DEFAULT_SCOPES: dict[str, SkillScope] = {
    "codex": "user",
    "claude": "user",
}

SKILL_PROJECT_TARGETS: dict[str, SkillTarget] = {
    "amp": SkillTarget("amp", "project", ".agents/skills/desloppify/SKILL.md", "AMP", True, "legacy_project", True),
    "claude": SkillTarget("claude", "project", ".claude/skills/desloppify/SKILL.md", "CLAUDE", True, "legacy_project", False),
    "opencode": SkillTarget("opencode", "project", ".opencode/skills/desloppify/SKILL.md", "OPENCODE", True, "legacy_project", True),
    "codex": SkillTarget("codex", "project", ".agents/skills/desloppify/SKILL.md", "CODEX", True, "legacy_project", False),
    "cursor": SkillTarget("cursor", "project", ".cursor/rules/desloppify.md", "CURSOR", True, "shared_file", True),
    "copilot": SkillTarget("copilot", "project", ".github/copilot-instructions.md", "COPILOT", False, "shared_file", True),
    "windsurf": SkillTarget("windsurf", "project", "AGENTS.md", "WINDSURF", False, "shared_file", True),
    "gemini": SkillTarget("gemini", "project", "AGENTS.md", "GEMINI", False, "shared_file", True),
    "hermes": SkillTarget("hermes", "project", "AGENTS.md", "HERMES", False, "shared_file", True),
}

SKILL_USER_TARGETS: dict[str, SkillTarget] = {
    "codex": SkillTarget("codex", "user", ".codex/skills/desloppify/SKILL.md", "CODEX", True, "canonical_user", True),
    "claude": SkillTarget("claude", "user", ".claude/skills/desloppify/SKILL.md", "CLAUDE", True, "canonical_user", True),
}


def get_skill_target(interface: str, scope: SkillScope = "project") -> SkillTarget:
    """Return the writable target metadata for an interface and scope."""
    interface_name = interface.lower()
    if scope == "user":
        target = SKILL_USER_TARGETS.get(interface_name)
        if target is None:
            raise ValueError(f"Interface '{interface_name}' does not support user scope.")
        return target
    target = SKILL_PROJECT_TARGETS.get(interface_name)
    if target is None:
        raise ValueError(f"Unknown interface '{interface_name}'.")
    return target


def get_default_scope(interface: str) -> SkillScope:
    """Return the default install scope for an interface."""
    return SKILL_DEFAULT_SCOPES.get(interface.lower(), "project")


def get_skill_targets(interface: str) -> list[SkillTarget]:
    """Return all known targets for an interface."""
    targets: list[SkillTarget] = []
    user_target = SKILL_USER_TARGETS.get(interface.lower())
    if user_target is not None:
        targets.append(user_target)
    project_target = SKILL_PROJECT_TARGETS.get(interface.lower())
    if project_target is not None:
        targets.append(project_target)
    return targets


def _shared_search_targets() -> tuple[SkillTarget, ...]:
    return (
        SkillTarget("claude", "project", "CLAUDE.md", "CLAUDE", False, "shared_file", False),
        SkillTarget("windsurf", "project", "AGENTS.md", "WINDSURF", False, "shared_file", True),
        SkillTarget("gemini", "project", "AGENTS.md", "GEMINI", False, "shared_file", True),
        SkillTarget("hermes", "project", "AGENTS.md", "HERMES", False, "shared_file", True),
    )


SKILL_SEARCH_PATHS = tuple(
    target.rel_path
    for target in (
        *SKILL_USER_TARGETS.values(),
        *SKILL_PROJECT_TARGETS.values(),
        *_shared_search_targets(),
    )
)


def _display_rel_path(path: Path, *, project_root: Path, home: Path) -> str:
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        pass
    try:
        relative_home = path.relative_to(home)
        return f"~/{str(relative_home).replace('\\', '/')}"
    except ValueError:
        return str(path)


def _read_skill_install(target: SkillTarget, *, project_root: Path, home: Path) -> SkillInstall | None:
    full = target.absolute_path(project_root=project_root, home=home)
    if not full.is_file():
        return None
    try:
        content = full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    version_match = SKILL_VERSION_RE.search(content)
    if not version_match:
        return None
    installed_version = int(version_match.group(1))
    overlay_match = SKILL_OVERLAY_RE.search(content)
    overlay = overlay_match.group(1).lower() if overlay_match else None
    interface = overlay or target.interface
    return SkillInstall(
        rel_path=_display_rel_path(full, project_root=project_root, home=home),
        absolute_path=full,
        interface=interface,
        scope=target.scope,
        source_kind=target.source_kind,
        canonical=target.canonical,
        version=installed_version,
        overlay=overlay,
        stale=installed_version < SKILL_VERSION,
    )


def find_installed_skills(
    interface: str | None = None,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> list[SkillInstall]:
    """Return all installed skill documents known to the resolver."""
    root = project_root if project_root is not None else get_project_root()
    home_dir = home if home is not None else Path.home()
    installs: list[SkillInstall] = []
    seen: set[Path] = set()
    targets = [
        *SKILL_USER_TARGETS.values(),
        *SKILL_PROJECT_TARGETS.values(),
        *_shared_search_targets(),
    ]
    for target in targets:
        full = target.absolute_path(project_root=root, home=home_dir)
        if full in seen:
            continue
        seen.add(full)
        install = _read_skill_install(target, project_root=root, home=home_dir)
        if install is None:
            continue
        if interface and install.interface != interface.lower():
            continue
        installs.append(install)
    return sorted(
        installs,
        key=lambda item: (
            item.interface or "",
            0 if item.canonical else 1,
            0 if item.scope == "user" else 1,
            0 if not item.stale else 1,
            item.rel_path,
        ),
    )


def select_preferred_install(
    installs: list[SkillInstall],
    *,
    interface: str | None = None,
) -> SkillInstall | None:
    """Pick the best install from a resolver result set."""
    filtered = [
        install for install in installs
        if interface is None or install.interface == interface.lower()
    ]
    if not filtered:
        return None
    return sorted(
        filtered,
        key=lambda item: (
            0 if item.canonical else 1,
            0 if item.scope == "user" else 1,
            0 if not item.stale else 1,
            item.rel_path,
        ),
    )[0]


def find_installed_skill(interface: str | None = None) -> SkillInstall | None:
    """Compatibility wrapper returning one preferred installed skill document."""
    return select_preferred_install(find_installed_skills(interface=interface), interface=interface)


def check_skill_version() -> str | None:
    """Return a warning if an installed skill doc is outdated."""
    installs = find_installed_skills()
    if not installs:
        return None
    if all(not install.stale for install in installs):
        return None
    install = select_preferred_install(installs)
    if install is None or not install.stale:
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
    "SKILL_DEFAULT_SCOPES",
    "SKILL_PROJECT_TARGETS",
    "SKILL_SEARCH_PATHS",
    "SKILL_TARGETS",
    "SKILL_USER_TARGETS",
    "SkillInstall",
    "SkillScope",
    "SkillSourceKind",
    "SkillTarget",
    "check_skill_version",
    "find_installed_skill",
    "find_installed_skills",
    "get_default_scope",
    "get_skill_target",
    "get_skill_targets",
    "select_preferred_install",
]
