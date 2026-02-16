"""Shared helpers used by multiple command modules."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from ..state import json_default
from ..utils import PROJECT_ROOT

if TYPE_CHECKING:
    from ..lang.base import LangConfig


QUERY_FILE = PROJECT_ROOT / ".desloppify" / "query.json"
EXTRA_ROOT_MARKERS = (
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "Cargo.toml",
)


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
        safe_write_text(QUERY_FILE, json.dumps(data, indent=2, default=json_default) + "\n")
        print(f"  \u2192 query.json updated", file=sys.stderr)
    except OSError as e:
        print(f"  \u26a0 Could not write query.json: {e}", file=sys.stderr)


@lru_cache(maxsize=1)
def _lang_config_markers() -> tuple[str, ...]:
    """Collect project-root marker files from language plugins + fallback markers."""
    markers = set(EXTRA_ROOT_MARKERS)
    try:
        from ..lang import available_langs, get_lang
    except Exception:
        return tuple(sorted(markers))

    for lang_name in available_langs():
        try:
            cfg = get_lang(lang_name)
        except Exception:
            continue
        for marker in getattr(cfg, "detect_markers", []) or []:
            if not isinstance(marker, str):
                continue
            cleaned = marker.strip()
            if cleaned:
                markers.add(cleaned)
    return tuple(sorted(markers))


def _looks_like_project_root(path: Path) -> bool:
    """Return True when a directory contains language config markers."""
    return any((path / marker).exists() for marker in _lang_config_markers())


def _resolve_detection_root(args) -> Path:
    """Best root to auto-detect language from.

    Prefer --path when it points to (or is under) a project root with language
    config markers. Fall back to PROJECT_ROOT when no marker can be found.
    """
    raw_path = getattr(args, "path", None)
    if not raw_path:
        return PROJECT_ROOT

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate = candidate.resolve()
    search_root = candidate if candidate.is_dir() else candidate.parent

    for root in (search_root, *search_root.parents):
        if _looks_like_project_root(root):
            return root
    return PROJECT_ROOT


def _auto_detect_lang_name(args) -> str | None:
    """Auto-detect language using the most relevant root for this command."""
    from ..lang import auto_detect_lang

    root = _resolve_detection_root(args)
    detected = auto_detect_lang(root)
    if detected is None and root != PROJECT_ROOT:
        detected = auto_detect_lang(PROJECT_ROOT)
    return detected


def state_path(args) -> Path | None:
    """Get state file path from args, or None for default."""
    p = getattr(args, "state", None)
    if p:
        return Path(p)
    # Per-language state files when --lang is explicit or auto-detected
    lang_name = getattr(args, "lang", None)
    if not lang_name:
        lang_name = _auto_detect_lang_name(args)
    if lang_name:
        return PROJECT_ROOT / ".desloppify" / f"state-{lang_name}.json"
    return None


def resolve_lang(args) -> LangConfig | None:
    """Resolve the language config from args, with auto-detection fallback."""
    lang_name = getattr(args, "lang", None)
    if lang_name is None:
        lang_name = _auto_detect_lang_name(args)
    if lang_name is None:
        return None
    from ..lang import get_lang
    try:
        return get_lang(lang_name)
    except ValueError as e:
        from ..lang import available_langs
        from ..utils import colorize
        langs = available_langs()
        sample = langs[0] if langs else "<language>"
        print(colorize(f"  {e}", "red"), file=sys.stderr)
        print(colorize(f"  Hint: use --lang to select manually (e.g. --lang {sample})", "dim"),
              file=sys.stderr)
        sys.exit(1)
