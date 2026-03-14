"""`update-skill` command package with backward-compatible exports."""

from __future__ import annotations

import argparse

from . import cmd as _cmd

SKILL_BEGIN = _cmd.SKILL_BEGIN
SKILL_END = _cmd.SKILL_END
SKILL_TARGETS = _cmd.SKILL_TARGETS
SKILL_VERSION = _cmd.SKILL_VERSION
SKILL_VERSION_RE = _cmd.SKILL_VERSION_RE
SkillInstall = _cmd.SkillInstall
SkillScope = _cmd.SkillScope

_RAW_BASE = _cmd._RAW_BASE
_FRONTMATTER_FIRST_INTERFACES = _cmd._FRONTMATTER_FIRST_INTERFACES
_download = _cmd._download
_get_home_path = _cmd._get_home_path
_build_section = _cmd._build_section
_ensure_frontmatter_first = _cmd._ensure_frontmatter_first
_replace_section = _cmd._replace_section

find_installed_skill = _cmd.find_installed_skill
find_installed_skills = _cmd.find_installed_skills
get_project_root = _cmd.get_project_root
resolve_scope = _cmd.resolve_scope
safe_write_text = _cmd.safe_write_text
colorize = _cmd.colorize


def resolve_interface(
    explicit: str | None = None,
    install: SkillInstall | None = None,
    installs: list[SkillInstall] | None = None,
    active_interface: str | None = None,
) -> str | None:
    """Resolve which interface to update."""
    resolved_installs = installs if installs is not None else find_installed_skills()
    resolved_install = install
    if resolved_install is None and len(resolved_installs) == 1:
        resolved_install = resolved_installs[0]
    return _cmd.resolve_interface(
        explicit=explicit,
        install=resolved_install,
        installs=resolved_installs,
        active_interface=active_interface,
    )


def update_installed_skill(interface: str, scope: str | None = "auto") -> bool:
    """Download and install the skill document for the given interface."""
    return _cmd._update_installed_skill_with_deps(
        interface,
        scope=resolve_scope(interface, scope),
        download_fn=_download,
        get_home_path_fn=_get_home_path,
        get_project_root_fn=get_project_root,
        safe_write_text_fn=safe_write_text,
        colorize_fn=colorize,
    )


def cmd_update_skill(args: argparse.Namespace) -> None:
    """Install or update the desloppify skill document."""
    _cmd._run_cmd_update_skill(
        args,
        resolve_interface_fn=resolve_interface,
        update_installed_skill_fn=update_installed_skill,
        colorize_fn=colorize,
        find_installed_skills_fn=find_installed_skills,
    )


__all__ = [
    "SKILL_BEGIN",
    "SKILL_END",
    "SKILL_TARGETS",
    "SKILL_VERSION",
    "SKILL_VERSION_RE",
    "SkillInstall",
    "SkillScope",
    "_FRONTMATTER_FIRST_INTERFACES",
    "_RAW_BASE",
    "_build_section",
    "_download",
    "_get_home_path",
    "_ensure_frontmatter_first",
    "_replace_section",
    "cmd_update_skill",
    "colorize",
    "find_installed_skill",
    "find_installed_skills",
    "get_project_root",
    "resolve_interface",
    "resolve_scope",
    "update_installed_skill",
]
