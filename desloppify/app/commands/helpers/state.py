"""State-path and scan-gating helpers for command modules."""

from __future__ import annotations

from pathlib import Path

from desloppify.app.commands.helpers.lang import auto_detect_lang_name
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.utils import colorize


def _sole_existing_lang_state_file() -> Path | None:
    """Return the only existing language-specific state file, if unambiguous."""
    state_dir = PROJECT_ROOT / ".desloppify"
    if not state_dir.exists():
        return None
    candidates = sorted(path for path in state_dir.glob("state-*.json") if path.is_file())
    if len(candidates) == 1:
        return candidates[0]
    return None


def _allow_lang_state_fallback(args) -> bool:
    """Whether command can safely fallback to the sole existing lang state file."""
    # Scan should always honor detected/explicit language mapping to avoid cross-lang merges.
    return getattr(args, "command", None) != "scan"


def state_path(args) -> Path | None:
    """Get state file path from args, or None for default."""
    path_arg = getattr(args, "state", None)
    if path_arg:
        return Path(path_arg)
    lang_name = getattr(args, "lang", None)
    if not lang_name:
        lang_name = auto_detect_lang_name(args)
    if lang_name:
        resolved = PROJECT_ROOT / ".desloppify" / f"state-{lang_name}.json"
        if resolved.exists() or not _allow_lang_state_fallback(args):
            return resolved
        fallback = _sole_existing_lang_state_file()
        if fallback is not None:
            return fallback
        return resolved

    if _allow_lang_state_fallback(args):
        fallback = _sole_existing_lang_state_file()
        if fallback is not None:
            return fallback
    return None


def require_completed_scan(state: dict) -> bool:
    """Return True when the state contains at least one completed scan."""
    has_completed_scan = bool(state.get("last_scan"))
    if not has_completed_scan:
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
    return has_completed_scan
