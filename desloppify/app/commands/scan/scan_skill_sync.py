"""Skill auto-install/update helpers for scan workflows."""

from __future__ import annotations

import logging

from desloppify.app.commands import update_skill as update_skill_mod
from desloppify.app.commands.scan.scan_agent_env import (
    detect_agent_interface,
    is_agent_environment,
)
from desloppify.core import skill_docs as skill_docs_mod

logger = logging.getLogger(__name__)


def _try_auto_update_skill() -> None:
    """Attempt to auto-install or update the skill document best-effort."""
    install = skill_docs_mod.find_installed_skill()
    if install and not install.stale:
        return

    try:
        interface = (
            update_skill_mod.resolve_interface(install=install)
            if install
            else detect_agent_interface()
        )
        if interface:
            update_skill_mod.update_installed_skill(interface)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.debug("Skill auto-update skipped: %s", exc, exc_info=True)
        return


def auto_update_skill() -> None:
    """Auto-install or update the skill document if an agent runtime is detected."""
    if not is_agent_environment():
        return

    _try_auto_update_skill()
    install = skill_docs_mod.find_installed_skill()
    if not install:
        names = ", ".join(sorted(skill_docs_mod.SKILL_TARGETS))
        print(
            f"No skill document found. Install one for better workflow guidance: "
            f"desloppify update-skill <{names}>"
        )
    elif install.stale:
        print(
            f"Skill document is outdated "
            f"(v{install.version}, current v{skill_docs_mod.SKILL_VERSION}). "
            f"Run: desloppify update-skill"
        )


__all__ = ["auto_update_skill"]
