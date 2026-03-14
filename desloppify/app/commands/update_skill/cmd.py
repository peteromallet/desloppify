"""update-skill command: install or update the desloppify skill document."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from pathlib import Path

from desloppify.app.skill_docs import (
    SKILL_BEGIN,
    SKILL_END,
    SKILL_TARGETS,
    SKILL_VERSION,
    SKILL_VERSION_RE,
    SkillInstall,
    SkillScope,
    find_installed_skill,
    find_installed_skills,
    get_default_scope,
    get_skill_target,
)
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.output.terminal import colorize

_RAW_BASE = "https://raw.githubusercontent.com/cpjet64/desloppify/main/docs"


def _get_home_path() -> Path:
    """Return the current user's home directory."""
    return Path.home()


def _download(filename: str) -> str:
    """Download a file from the desloppify docs directory on GitHub."""
    url = f"{_RAW_BASE}/{filename}"
    with urllib.request.urlopen(url, timeout=15) as resp:  # nosec B310
        return resp.read().decode("utf-8")


def _build_section(skill_content: str, overlay_content: str | None) -> str:
    """Assemble the complete skill section from downloaded parts."""
    parts = [skill_content.rstrip()]
    if overlay_content:
        parts.append(overlay_content.rstrip())
    return "\n\n".join(parts) + "\n"


_FRONTMATTER_FIRST_INTERFACES = frozenset({"amp", "codex"})


def _ensure_frontmatter_first(content: str) -> str:
    """Move YAML frontmatter to the top if HTML comments precede it."""
    lines = content.split("\n")

    fm_start = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            fm_start = i
            break
    if fm_start is None or fm_start == 0:
        return content

    prefix_lines = lines[:fm_start]

    fm_end = None
    for i, line in enumerate(lines[fm_start + 1 :], fm_start + 1):
        if line.strip() == "---":
            fm_end = i
            break
    if fm_end is None:
        return content

    reordered = lines[fm_start : fm_end + 1] + prefix_lines + lines[fm_end + 1 :]
    return "\n".join(reordered)


def _replace_section(file_content: str, new_section: str) -> str:
    """Replace the desloppify section in a shared file, preserving surrounding content."""
    begin = file_content.find(SKILL_BEGIN)
    end = file_content.rfind(SKILL_END)
    if begin == -1 or end == -1:
        return file_content.rstrip() + "\n\n" + new_section

    before = file_content[:begin]
    after = file_content[end + len(SKILL_END) :]
    before = before.rstrip() + "\n\n" if before.strip() else ""
    after = "\n" + after.lstrip("\n") if after.strip() else "\n"
    return before + new_section + after


def resolve_interface(
    explicit: str | None = None,
    install: SkillInstall | None = None,
    installs: list[SkillInstall] | None = None,
    active_interface: str | None = None,
) -> str | None:
    """Resolve which interface to update."""
    if explicit:
        return explicit.lower()

    if install is not None and install.overlay:
        return install.overlay.lower()
    if install is not None and install.interface:
        return install.interface.lower()

    detected = installs if installs is not None else find_installed_skills()
    if active_interface:
        active_name = active_interface.lower()
        if any(item.interface == active_name for item in detected):
            return active_name

    interfaces = sorted({item.interface for item in detected if item.interface})
    if len(interfaces) == 1:
        return interfaces[0]
    return None


def resolve_scope(interface: str, requested_scope: str | None = "auto") -> SkillScope:
    """Resolve the install scope for an interface."""
    scope_name = (requested_scope or "auto").lower()
    if scope_name == "auto":
        return get_default_scope(interface)
    if scope_name not in {"user", "project"}:
        raise ValueError(f"Unknown scope '{requested_scope}'.")
    return scope_name


def _print_detected_installs(installs: list[SkillInstall]) -> None:
    if not installs:
        return
    print("Detected installs:")
    for install in installs:
        interface = install.interface or "unknown"
        freshness = "stale" if install.stale else "current"
        print(
            f"  - {interface}: {install.rel_path} "
            f"[scope={install.scope}, source={install.source_kind}, {freshness}]"
        )


def _update_installed_skill_with_deps(
    interface: str,
    *,
    scope: SkillScope = "auto",
    download_fn,
    get_home_path_fn,
    get_project_root_fn,
    safe_write_text_fn,
    colorize_fn,
) -> bool:
    """Download and install the skill document for the given interface."""
    resolved_scope = resolve_scope(interface, scope)
    target = get_skill_target(interface, resolved_scope)
    target_path = target.absolute_path(
        project_root=get_project_root_fn(),
        home=get_home_path_fn(),
    )

    print(colorize_fn(f"Downloading skill document ({interface})...", "dim"))
    try:
        skill_content = download_fn("SKILL.md")
        overlay_content = download_fn(f"{target.overlay_name}.md") if target.overlay_name else None
    except (urllib.error.URLError, OSError) as exc:
        print(colorize_fn(f"Download failed: {exc}", "red"))
        return False

    if "desloppify-skill-version" not in skill_content:
        print(colorize_fn("Downloaded content doesn't look like a skill document.", "red"))
        return False

    new_section = _build_section(skill_content, overlay_content)
    if interface in _FRONTMATTER_FIRST_INTERFACES:
        new_section = _ensure_frontmatter_first(new_section)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target.dedicated:
        result = new_section
    elif target_path.is_file():
        existing = target_path.read_text(encoding="utf-8", errors="replace")
        result = _replace_section(existing, new_section)
    else:
        result = new_section

    safe_write_text_fn(target_path, result)

    version_match = SKILL_VERSION_RE.search(new_section)
    version = version_match.group(1) if version_match else "?"
    print(
        colorize_fn(
            f"Updated {target.rel_path} (v{version}, tool expects v{SKILL_VERSION})",
            "green",
        )
    )
    if interface in {"codex", "claude"} and resolved_scope == "project":
        print(colorize_fn("Wrote the project-scoped compatibility install.", "yellow"))
    return True


def update_installed_skill(interface: str, scope: str | None = "auto") -> bool:
    """Download and install the skill document for the given interface."""
    return _update_installed_skill_with_deps(
        interface,
        scope=resolve_scope(interface, scope),
        download_fn=_download,
        get_home_path_fn=_get_home_path,
        get_project_root_fn=get_project_root,
        safe_write_text_fn=safe_write_text,
        colorize_fn=colorize,
    )


def _run_cmd_update_skill(
    args: argparse.Namespace,
    *,
    resolve_interface_fn,
    update_installed_skill_fn,
    colorize_fn,
    find_installed_skills_fn=None,
) -> None:
    """Run the update-skill command with injectable package seams."""
    if find_installed_skills_fn is None:
        find_installed_skills_fn = find_installed_skills
    explicit_interface = getattr(args, "interface", None)
    requested_scope = getattr(args, "scope", "auto")
    installs = find_installed_skills_fn()
    interface = resolve_interface_fn(explicit_interface, installs=installs)

    if explicit_interface and interface not in SKILL_TARGETS:
        names = ", ".join(sorted(SKILL_TARGETS))
        print(colorize_fn(f"Unknown interface '{interface}'.", "red"))
        print(f"Available: {names}")
        return

    if not explicit_interface:
        interfaces = sorted({install.interface for install in installs if install.interface})
        if len(interfaces) > 1 and interface is None:
            print(colorize_fn("Multiple installed skill documents were detected.", "yellow"))
            _print_detected_installs(installs)
            print()
            print("Run: desloppify update-skill <interface>")
            return
        if interface is None:
            print(colorize_fn("No installed skill document found.", "yellow"))
            print()
            names = ", ".join(sorted(SKILL_TARGETS))
            print(f"Install with: desloppify update-skill <{names}>")
            return

    update_installed_skill_fn(interface, requested_scope)


def cmd_update_skill(args: argparse.Namespace) -> None:
    """Install or update the desloppify skill document."""
    _run_cmd_update_skill(
        args,
        resolve_interface_fn=resolve_interface,
        update_installed_skill_fn=update_installed_skill,
        colorize_fn=colorize,
    )
