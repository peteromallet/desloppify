"""Heuristic checks for deciding whether modules need direct tests."""

from __future__ import annotations

import logging

from desloppify.engine.hook_registry import get_lang_hook

from .io import read_coverage_file

logger = logging.getLogger(__name__)


def _load_lang_test_coverage_module(lang_name: str):
    """Load language-specific test coverage helpers from lang hooks."""
    return get_lang_hook(lang_name, "test_coverage") or object()


def _has_testable_logic(filepath: str, lang_name: str) -> bool:
    """Check whether a file contains runtime logic worth testing."""
    read_result = read_coverage_file(filepath, context="testable_logic")
    if not read_result.ok:
        return False
    content = read_result.content

    mod = _load_lang_test_coverage_module(lang_name)
    has_logic = getattr(mod, "has_testable_logic", None)
    if callable(has_logic):
        return bool(has_logic(filepath, content))
    return True


def _has_inline_tests(filepath: str, lang_name: str) -> bool:
    """Check whether a production file embeds inline tests."""
    read_result = read_coverage_file(filepath, context="inline_tests")
    if not read_result.ok:
        return False
    content = read_result.content

    mod = _load_lang_test_coverage_module(lang_name)
    has_inline = getattr(mod, "has_inline_tests", None)
    if callable(has_inline):
        try:
            return bool(has_inline(filepath, content))
        except (TypeError, ValueError):
            logger.debug("inline_tests hook failed for %s", filepath, exc_info=True)
    return False


def _expand_direct_test_targets(
    directly_tested: set[str],
    production_files: set[str],
    lang_name: str,
) -> set[str]:
    """Apply a language's semantic direct-test ownership expansion."""
    mod = _load_lang_test_coverage_module(lang_name)
    expand = getattr(mod, "expand_direct_test_targets", None)
    if not callable(expand):
        return set()
    try:
        return set(expand(directly_tested, production_files))
    except (OSError, TypeError, ValueError):
        logger.debug("direct test target expansion failed", exc_info=True)
        return set()


def _is_runtime_entrypoint(filepath: str, lang_name: str) -> bool:
    """Best-effort runtime entrypoint detection for no-tests classification."""
    read_result = read_coverage_file(filepath, context="runtime_entrypoint")
    if not read_result.ok:
        return False
    content = read_result.content

    mod = _load_lang_test_coverage_module(lang_name)
    hook = getattr(mod, "is_runtime_entrypoint", None)
    if callable(hook):
        try:
            return bool(hook(filepath, content))
        except (TypeError, ValueError):
            logger.debug(
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
