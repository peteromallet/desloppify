"""Fix command option and fixer resolution helpers."""

from __future__ import annotations

import dataclasses
import sys

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.languages.framework.base.types import FixerConfig, LangConfig
from desloppify.utils import colorize

_COMMAND_POST_FIX: dict[str, object] = {}


def _load_fixer(args, fixer_name: str) -> tuple[LangConfig, FixerConfig]:
    """Resolve fixer from language plugin registry, or exit."""
    lang = resolve_lang(args)
    if not lang:
        print(colorize("Could not detect language. Use --lang to specify.", "red"))
        sys.exit(1)
    if not lang.fixers:
        print(colorize(f"No auto-fixers available for {lang.name}.", "red"))
        sys.exit(1)
    if fixer_name not in lang.fixers:
        available = ", ".join(sorted(lang.fixers.keys()))
        print(colorize(f"Unknown fixer: {fixer_name}", "red"))
        print(colorize(f"  Available: {available}", "dim"))
        sys.exit(1)
    fc = lang.fixers[fixer_name]
    if fixer_name in _COMMAND_POST_FIX and not fc.post_fix:
        fc = dataclasses.replace(fc, post_fix=_COMMAND_POST_FIX[fixer_name])
    return lang, fc
