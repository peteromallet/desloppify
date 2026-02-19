"""Registry for optional language hook modules consumed by detectors."""

from __future__ import annotations

import importlib
import logging
import sys
from collections import defaultdict

_LANG_HOOKS: dict[str, dict[str, object]] = defaultdict(dict)
_LOGGER = logging.getLogger(__name__)


def register_lang_hooks(
    lang_name: str,
    *,
    test_coverage: object | None = None,
) -> None:
    """Register optional detector hook modules for a language."""
    hooks = _LANG_HOOKS[lang_name]
    if test_coverage is not None:
        hooks["test_coverage"] = test_coverage


def get_lang_hook(lang_name: str | None, hook_name: str) -> object | None:
    """Get a previously-registered language hook module."""
    if not lang_name:
        return None

    hook = _LANG_HOOKS.get(lang_name, {}).get(hook_name)
    if hook is not None:
        return hook

    module_name = f"desloppify.languages.{lang_name}"
    module = sys.modules.get(module_name)

    # Lazy-load only the requested language package.
    if module is None:
        try:
            importlib.import_module(module_name)
        except (ImportError, ValueError, TypeError, RuntimeError, OSError) as exc:
            _LOGGER.debug(
                "Unable to import language hook package %s: %s", lang_name, exc
            )
            return None
    elif lang_name not in _LANG_HOOKS:
        try:
            importlib.reload(module)
        except (ImportError, ValueError, TypeError, RuntimeError, OSError) as exc:
            _LOGGER.debug(
                "Unable to reload language hook package %s: %s", lang_name, exc
            )
            return None

    return _LANG_HOOKS.get(lang_name, {}).get(hook_name)


def clear_lang_hooks_for_tests() -> None:
    """Clear registry (test helper)."""
    _LANG_HOOKS.clear()


__all__ = [
    "clear_lang_hooks_for_tests",
    "get_lang_hook",
    "register_lang_hooks",
]
