"""State-path and scan-gating helpers for command modules."""

from __future__ import annotations

from pathlib import Path

from desloppify.app.commands.helpers.lang import auto_detect_lang_name
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.utils import colorize


def state_path(args) -> Path | None:
    """Get state file path from args, or None for default."""
    path_arg = getattr(args, "state", None)
    if path_arg:
        return Path(path_arg)
    lang_name = getattr(args, "lang", None)
    if not lang_name:
        lang_name = auto_detect_lang_name(args)
    if lang_name:
        return PROJECT_ROOT / ".desloppify" / f"state-{lang_name}.json"
    return None


def require_completed_scan(state: dict) -> bool:
    """Return True when the state contains at least one completed scan."""
    has_completed_scan = bool(state.get("last_scan"))
    if not has_completed_scan:
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
    return has_completed_scan

