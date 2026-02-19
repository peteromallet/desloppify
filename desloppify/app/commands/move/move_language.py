"""Language detection and move-module loading for the move command."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

from desloppify import languages as lang_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.utils import colorize


def _build_ext_to_lang_map() -> dict[str, str]:
    """Build extension→language map from registered language configs."""
    ext_map: dict[str, str] = {}
    for lang_name in lang_mod.available_langs():
        cfg = lang_mod.get_lang(lang_name)
        for ext in cfg.extensions:
            ext_map.setdefault(ext, lang_name)
    return ext_map


_EXT_TO_LANG = _build_ext_to_lang_map()


def detect_lang_from_ext(source: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(source).suffix
    return _EXT_TO_LANG.get(ext)


def detect_lang_from_dir(source_dir: str) -> str | None:
    """Detect language from files in a directory."""
    source_path = Path(source_dir)
    for filepath in source_path.rglob("*"):
        if filepath.is_file():
            lang = detect_lang_from_ext(str(filepath))
            if lang:
                return lang
    return None


def resolve_lang_for_file_move(source_abs: str, args) -> str | None:
    """Resolve language for a single-file move operation.

    Explicit ``--lang`` takes priority. Otherwise, infer from file extension and
    finally fall back to generic language resolution.
    """
    explicit_lang = getattr(args, "lang", None)
    if explicit_lang:
        lang = resolve_lang(args)
        if lang:
            return lang.name

    lang_name = detect_lang_from_ext(source_abs)
    if not lang_name:
        lang = resolve_lang(args)
        if lang:
            lang_name = lang.name
    return lang_name


def supported_ext_hint() -> str:
    """Return a display string for known source extensions."""
    exts = ", ".join(sorted(_EXT_TO_LANG))
    return exts or "<none>"


def load_lang_move_module(lang_name: str) -> ModuleType:
    """Load language-specific move helpers from ``lang/<name>/move.py``."""
    module_name = f"desloppify.languages.{lang_name}.move"
    try:
        return importlib.import_module(module_name)
    except ImportError as ex:
        print(
            colorize(f"Move not yet supported for language: {lang_name} ({ex})", "red"),
            file=sys.stderr,
        )
        sys.exit(1)


def resolve_move_verify_hint(move_mod: ModuleType) -> str:
    """Return a move-module verification hint."""
    get_verify_hint = getattr(move_mod, "get_verify_hint", None)
    if callable(get_verify_hint):
        hint = get_verify_hint()
        if isinstance(hint, str):
            return hint.strip()
    return ""


__all__ = [
    "detect_lang_from_dir",
    "detect_lang_from_ext",
    "load_lang_move_module",
    "resolve_move_verify_hint",
    "resolve_lang_for_file_move",
    "supported_ext_hint",
]
