"""update-skill command: install or update the desloppify skill document."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request

from desloppify.utils import (
    PROJECT_ROOT,
    SKILL_BEGIN,
    SKILL_END,
    SKILL_TARGETS,
    SKILL_VERSION,
    SKILL_VERSION_RE,
    SkillInstall,
    colorize,
    find_installed_skill,
)

_RAW_BASE = (
    "https://raw.githubusercontent.com/peteromallet/desloppify/main/docs"
)


def _download(filename: str) -> str:
    """Download a file from the desloppify docs directory on GitHub."""
    url = f"{_RAW_BASE}/{filename}"
    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def _build_section(skill_content: str, overlay_content: str | None) -> str:
    """Assemble the complete skill section from downloaded parts."""
    parts = [skill_content.rstrip()]
    if overlay_content:
        parts.append(overlay_content.rstrip())
    return "\n\n".join(parts) + "\n"


def _replace_section(file_content: str, new_section: str) -> str:
    """Replace the desloppify section in a shared file, preserving surrounding content.

    Uses first ``<!-- desloppify-begin -->`` and last ``<!-- desloppify-end -->``
    so the overlay (which also has an end marker) is captured correctly.
    """
    begin = file_content.find(SKILL_BEGIN)
    end = file_content.rfind(SKILL_END)
    if begin == -1 or end == -1:
        # No section markers — append (first install into existing shared file).
        return file_content.rstrip() + "\n\n" + new_section

    before = file_content[:begin]
    after = file_content[end + len(SKILL_END):]
    before = before.rstrip() + "\n\n" if before.strip() else ""
    after = "\n" + after.lstrip("\n") if after.strip() else "\n"
    return before + new_section + after


def resolve_interface(
    explicit: str | None = None,
    install: SkillInstall | None = None,
) -> str | None:
    """Resolve which interface to update.

    Uses the explicit argument if given, otherwise infers from an existing
    install's overlay marker or file path.
    """
    if explicit:
        return explicit.lower()

    if install is None:
        install = find_installed_skill()
    if not install:
        return None

    if install.overlay:
        return install.overlay.lower()

    for name, (target, _overlay, _ded) in SKILL_TARGETS.items():
        if target == install.rel_path:
            return name
    return None


def update_installed_skill(interface: str) -> bool:
    """Download and install the skill document for the given interface.

    Returns True on success, False on failure. Prints status messages.
    """
    target_rel, overlay_name, dedicated = SKILL_TARGETS[interface]
    target_path = PROJECT_ROOT / target_rel

    print(colorize(f"Downloading skill document ({interface})...", "dim"))
    try:
        skill_content = _download("SKILL.md")
        overlay_content = _download(f"{overlay_name}.md") if overlay_name else None
    except (urllib.error.URLError, OSError) as exc:
        print(colorize(f"Download failed: {exc}", "red"))
        return False

    if "desloppify-skill-version" not in skill_content:
        print(colorize("Downloaded content doesn't look like a skill document.", "red"))
        return False

    new_section = _build_section(skill_content, overlay_content)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if dedicated:
        result = new_section
    elif target_path.is_file():
        existing = target_path.read_text(encoding="utf-8", errors="replace")
        result = _replace_section(existing, new_section)
    else:
        result = new_section

    target_path.write_text(result, encoding="utf-8")

    version_match = SKILL_VERSION_RE.search(new_section)
    version = version_match.group(1) if version_match else "?"
    print(
        colorize(
            f"Updated {target_rel} (v{version}, tool expects v{SKILL_VERSION})",
            "green",
        )
    )
    return True


def cmd_update_skill(args: argparse.Namespace) -> None:
    """Install or update the desloppify skill document."""
    interface = resolve_interface(getattr(args, "interface", None))

    if not interface:
        print(colorize("No installed skill document found.", "yellow"))
        print()
        names = ", ".join(sorted(SKILL_TARGETS))
        print(f"Install with: desloppify update-skill <{names}>")
        return

    if interface not in SKILL_TARGETS:
        names = ", ".join(sorted(SKILL_TARGETS))
        print(colorize(f"Unknown interface '{interface}'.", "red"))
        print(f"Available: {names}")
        return

    update_installed_skill(interface)
