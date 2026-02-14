"""Shared helpers used by multiple command modules."""

import json
import sys
from pathlib import Path

from ..state import _json_default
from ..utils import PROJECT_ROOT


QUERY_FILE = PROJECT_ROOT / ".desloppify" / "query.json"


def _write_query(data: dict):
    """Write structured query output to .desloppify/query.json.

    Every query command calls this so the LLM can always Read the file
    instead of parsing terminal output. Auto-includes config for agent visibility.
    """
    if "config" not in data:
        try:
            from ..config import load_config, config_for_query
            data["config"] = config_for_query(load_config())
        except (OSError, ValueError, json.JSONDecodeError):
            pass  # Non-fatal — config is a convenience, not required
    try:
        from ..utils import safe_write_text
        safe_write_text(QUERY_FILE, json.dumps(data, indent=2, default=_json_default) + "\n")
        print(f"  \u2192 query.json updated", file=sys.stderr)
    except OSError as e:
        print(f"  \u26a0 Could not write query.json: {e}", file=sys.stderr)


def _state_path(args) -> Path | None:
    """Get state file path from args, or None for default."""
    p = getattr(args, "state", None)
    if p:
        return Path(p)
    # Per-language state files when --lang is explicit or auto-detected
    lang_name = getattr(args, "lang", None)
    if not lang_name:
        from ..lang import auto_detect_lang
        lang_name = auto_detect_lang(PROJECT_ROOT)
    if lang_name:
        return PROJECT_ROOT / ".desloppify" / f"state-{lang_name}.json"
    return None


def _resolve_lang(args):
    """Resolve the language config from args, with auto-detection fallback."""
    lang_name = getattr(args, "lang", None)
    if lang_name is None:
        from ..lang import auto_detect_lang
        from ..utils import PROJECT_ROOT
        lang_name = auto_detect_lang(PROJECT_ROOT)
    if lang_name is None:
        return None
    from ..lang import get_lang
    try:
        return get_lang(lang_name)
    except ValueError as e:
        from ..utils import colorize
        from ..lang import available_langs
        langs = ", ".join(available_langs()) or "python, typescript, csharp"
        print(colorize(f"  {e}", "red"), file=sys.stderr)
        print(colorize(f"  Hint: use --lang to select manually (available: {langs})", "dim"),
              file=sys.stderr)
        sys.exit(1)
