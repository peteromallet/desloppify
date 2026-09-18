"""setup command: install desloppify skill documents globally."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

from desloppify.app.commands.update_skill import (
    _build_section,
    _ensure_frontmatter_first,
    _replace_section,
)
from desloppify.app.skill_docs import GLOBAL_TARGETS, SKILL_VERSION, SKILL_VERSION_RE
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize

RESOURCE_PACKAGE = "desloppify.data.global"


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
    overlay_name = GLOBAL_TARGETS[interface][1]
    skill_content = _resource_text("SKILL.md")
    overlay_content = _resource_text(f"{overlay_name}.md")
    section = _build_section(skill_content, overlay_content)
    if interface in {"amp", "codex", "copilot", "qwen"}:
        section = _ensure_frontmatter_first(section)
    return section


def _installed_version(path: Path) -> int | None:
    """Return the installed skill version, or None if missing/unparseable."""
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = SKILL_VERSION_RE.search(content)
    return int(match.group(1)) if match is not None else None


def _is_current(path: Path) -> bool:
    """Check if an existing skill file is already at the current version."""
    version = _installed_version(path)
    return version is not None and version >= SKILL_VERSION


def _warn_skip(interface: str, tool_dir: str) -> None:
    print(
        colorize(
            f"Skipping {interface} (~/{tool_dir} not found)",
            "yellow",
        )
    )


def _install_global(interface: str) -> tuple[str, Path]:
    """Install one global skill file. Returns (action, path)."""
    rel_path, _overlay_name, tool_dir, dedicated = GLOBAL_TARGETS[interface]
    home = Path.home()
    tool_root = home / tool_dir
    if not tool_root.exists():
        raise CommandError(
            f"~/{tool_dir}/ not found — {interface.title()} doesn't appear to be installed."
        )

    target_path = home / rel_path
    old_version = _installed_version(target_path)
    if old_version is not None and old_version >= SKILL_VERSION:
        return "skipped", target_path

    section = _build_bundled_section(interface)
    if dedicated:
        safe_write_text(target_path, section)
    elif target_path.is_file():
        existing = target_path.read_text(encoding="utf-8", errors="replace")
        safe_write_text(target_path, _replace_section(existing, section))
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text(target_path, section)

    return ("updated" if old_version is not None else "installed"), target_path


def _run_global_setup(interface: str | None) -> None:
    """Install skill files into supported home-directory targets."""
    if interface is not None:
        if interface not in GLOBAL_TARGETS:
            names = ", ".join(sorted(GLOBAL_TARGETS))
            raise CommandError(f"Global setup only supports: {names}")
        action, target_path = _install_global(interface)
        if action == "skipped":
            print(colorize(f"{interface}: up to date (v{SKILL_VERSION})", "dim"))
        else:
            label = "Updated" if action == "updated" else "Installed"
            print(colorize(f"{label} {interface} skill:", "green"))
            print(str(target_path))
        return

    installed: list[tuple[str, Path]] = []
    updated: list[tuple[str, Path]] = []
    skipped_current: list[str] = []
    skipped_missing: list[tuple[str, str]] = []
    for name, (_rel_path, _overlay, tool_dir, _dedicated) in GLOBAL_TARGETS.items():
        home = Path.home()
        if not (home / tool_dir).exists():
            skipped_missing.append((name, tool_dir))
            continue
        action, target_path = _install_global(name)
        if action == "skipped":
            skipped_current.append(name)
        elif action == "updated":
            updated.append((name, target_path))
        else:
            installed.append((name, target_path))

    for name, tool_dir in skipped_missing:
        _warn_skip(name, tool_dir)

    if not installed and not updated and not skipped_current:
        dirs = ", ".join(f"~/{t[2]}/" for t in GLOBAL_TARGETS.values())
        raise CommandError(f"No supported AI tools detected. Install one of: {dirs}")

    if installed:
        print(colorize("Installed global skill files:", "green"))
        for name, path in installed:
            print(f"  {name}: {path}")
    if updated:
        print(colorize("Updated global skill files:", "green"))
        for name, path in updated:
            print(f"  {name}: {path}")
    if skipped_current:
        print(colorize(f"Up to date: {', '.join(skipped_current)}", "dim"))


def cmd_setup(args: argparse.Namespace) -> None:
    """Install skill documents globally."""
    interface = getattr(args, "interface", None)
    interface = interface.lower() if isinstance(interface, str) else None
    _run_global_setup(interface)


__all__ = ["cmd_setup"]
