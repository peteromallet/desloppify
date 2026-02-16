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
    config markers. When no marker is found, fall back to the provided path
    subtree so file-count detection can choose a local language.
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
    # No marker found — prefer the user-provided path subtree so file-count
    # based detection can still pick the local language.
    return search_root


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
        langs_str = ", ".join(langs) if langs else "registered language plugins"
        print(colorize(f"  {e}", "red"), file=sys.stderr)
        print(colorize(f"  Hint: use --lang to select manually (available: {langs_str})", "dim"),
              file=sys.stderr)
        sys.exit(1)


def _parse_lang_opt_assignments(raw_values: list[str] | None) -> dict[str, str]:
    """Parse repeated KEY=VALUE --lang-opt inputs."""
    values = raw_values or []
    parsed: dict[str, str] = {}
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"Invalid --lang-opt '{raw}'. Expected KEY=VALUE.")
        key, value = text.split("=", 1)
        key = key.strip().replace("-", "_")
        if not key:
            raise ValueError(f"Invalid --lang-opt '{raw}'. Missing option key.")
        parsed[key] = value.strip()
    return parsed


def resolve_lang_runtime_options(args, lang: LangConfig) -> dict[str, object]:
    """Resolve runtime options from generic --lang-opt and legacy aliases."""
    try:
        options = _parse_lang_opt_assignments(getattr(args, "lang_opt", None))
    except ValueError as e:
        from ..utils import colorize
        print(colorize(f"  {e}", "red"), file=sys.stderr)
        sys.exit(2)

    for arg_name, option_key in (lang.runtime_option_aliases or {}).items():
        value = getattr(args, arg_name, None)
        if value not in (None, ""):
            options[option_key] = value

    try:
        return lang.normalize_runtime_options(options, strict=True)
    except KeyError as e:
        from ..utils import colorize
        supported = sorted((lang.runtime_option_specs or {}).keys())
        hint = ", ".join(supported) if supported else "(none)"
        print(colorize(f"  {e}", "red"), file=sys.stderr)
        print(colorize(f"  Supported {lang.name} runtime options: {hint}", "dim"), file=sys.stderr)
        sys.exit(2)


def resolve_lang_settings(config: dict, lang: LangConfig) -> dict[str, object]:
    """Resolve persisted per-language settings from config.languages.<lang>."""
    if not isinstance(config, dict):
        return lang.normalize_settings({})
    languages = config.get("languages", {})
    if not isinstance(languages, dict):
        return lang.normalize_settings({})
    raw = languages.get(lang.name, {})
    return lang.normalize_settings(raw if isinstance(raw, dict) else {})
