"""Heuristic checks for deciding whether modules need direct tests."""

from __future__ import annotations

import logging
from pathlib import Path

from desloppify.hook_registry import get_lang_hook

LOGGER = logging.getLogger(__name__)


def _load_lang_test_coverage_module(lang_name: str):
    """Load language-specific test coverage helpers from lang hooks."""
    return get_lang_hook(lang_name, "test_coverage") or object()


def _has_testable_logic(filepath: str, lang_name: str) -> bool:
    """Check whether a file contains runtime logic worth testing."""
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return True

    mod = _load_lang_test_coverage_module(lang_name)
    has_logic = getattr(mod, "has_testable_logic", None)
    if callable(has_logic):
        return bool(has_logic(filepath, content))
    return True


def _is_runtime_entrypoint(filepath: str, lang_name: str) -> bool:
    """Best-effort runtime entrypoint detection for no-tests classification."""
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return False

    mod = _load_lang_test_coverage_module(lang_name)
    hook = getattr(mod, "is_runtime_entrypoint", None)
    if callable(hook):
        try:
            return bool(hook(filepath, content))
        except (TypeError, ValueError):
            LOGGER.debug(
                "runtime_entrypoint hook failed for %s", filepath, exc_info=True
            )

    lowered_path = filepath.replace("\\", "/").lower()
    lowered = content.lower()
    if lang_name == "typescript":
        if "/supabase/functions/" in lowered_path and lowered_path.endswith("/index.ts"):
            return True
        if "serve((" in lowered or "serve (" in lowered:
            if (
                "deno.land/std/http/server" in lowered
                or "jsr:@std/http/server" in lowered
            ):
                return True
    return False
