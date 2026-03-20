"""setup command: install bundled desloppify skill documents offline."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

from desloppify.app.commands.update_skill import (
    _build_section,
    _ensure_frontmatter_first,
)
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize

RESOURCE_PACKAGE = "desloppify.data.global"

# Global install paths — where each AI tool discovers user-level skills.
#
# These paths are NOT validated by the desloppify repo itself; they depend
# on external tool behavior. Sources:
#
#   claude: Claude Code reads ~/.claude/skills/<name>/SKILL.md
#           (same relative structure as the project-level .claude/skills/
#           path already in SKILL_TARGETS, but rooted at $HOME)
#   cursor: Cursor reads ~/.cursor/rules/<name>.md for global rules
#           (project-level equivalent: .cursor/rules/ in SKILL_TARGETS)
#
# The setup command validates that the parent tool directory exists (~/.claude/,
# ~/.cursor/) before writing, so it won't create orphan files for tools the
# user hasn't installed.
GLOBAL_TARGETS: dict[str, tuple[str, str, str]] = {
    # interface -> (path relative to ~/, overlay name, tool config dir to check)
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", ".claude"),
    "cursor": (".cursor/rules/desloppify.md", "CURSOR", ".cursor"),
}


def _resource_text(filename: str) -> str:
    """Read bundled skill content from package data."""
    try:
        return files(RESOURCE_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise CommandError(
            f"Bundled skill resource {filename!r} is unavailable. "
            "Reinstall desloppify or check package data."
        ) from exc


def _build_bundled_section(interface: str) -> str:
    """Assemble the bundled base skill and interface overlay."""
    skill_content = _resource_text("SKILL.md")
    overlay_content = _resource_text(f"{interface.upper()}.md")
    section = _build_section(skill_content, overlay_content)
    if interface in {"amp", "codex"}:
        section = _ensure_frontmatter_first(section)
    return section


def _warn_skip(interface: str, tool_dir: str) -> None:
    print(
        colorize(
            f"Skipping {interface} (~/{tool_dir} not found)",
            "yellow",
        )
    )


def _install_global(interface: str) -> Path:
    """Install one bundled global skill file and return the written path."""
    rel_path, _overlay_name, tool_dir = GLOBAL_TARGETS[interface]
    home = Path.home()
    tool_root = home / tool_dir
    if not tool_root.exists():
        raise CommandError(
            f"~/{tool_dir}/ not found — {interface.title()} doesn't appear to be installed."
        )

    target_path = home / rel_path
    section = _build_bundled_section(interface)
    safe_write_text(target_path, section)
    return target_path


def _run_global_setup(interface: str | None) -> None:
    """Install bundled skill files into supported home-directory targets."""
    if interface == "codex":
        print(
            colorize(
                "Codex global skill path is not yet confirmed. "
                "Use `desloppify update-skill codex` for per-project install.",
                "yellow",
            )
        )
        return

    if interface is not None:
        if interface not in GLOBAL_TARGETS:
            names = ", ".join(sorted(GLOBAL_TARGETS))
            raise CommandError(f"Global setup only supports: {names}")
        written = _install_global(interface)
        print(colorize(f"Installed {interface} skill:", "green"))
        print(str(written))
        return

    written_paths: list[tuple[str, Path]] = []
    skipped: list[tuple[str, str]] = []
    home = Path.home()
    for name, (rel_path, _overlay_name, tool_dir) in GLOBAL_TARGETS.items():
        tool_root = home / tool_dir
        if not tool_root.exists():
            skipped.append((name, tool_dir))
            continue
        target_path = home / rel_path
        section = _build_bundled_section(name)
        safe_write_text(target_path, section)
        written_paths.append((name, target_path))

    for name, tool_dir in skipped:
        _warn_skip(name, tool_dir)

    if not written_paths:
        raise CommandError(
            "No supported AI tools detected. "
            "Install Claude Code (~/.claude/) or Cursor (~/.cursor/) first."
        )

    print(colorize("Installed global skill files:", "green"))
    for name, path in written_paths:
        print(f"- {name}: {path}")


def cmd_setup(args: argparse.Namespace) -> None:
    """Install bundled skill documents globally."""
    interface = getattr(args, "interface", None)
    interface = interface.lower() if isinstance(interface, str) else None
    _run_global_setup(interface)


__all__ = ["GLOBAL_TARGETS", "cmd_setup"]
