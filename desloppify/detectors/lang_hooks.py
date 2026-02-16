"""Shared loader for optional language hook modules used by generic detectors."""

from __future__ import annotations

import importlib
from functools import lru_cache
from types import ModuleType


@lru_cache(maxsize=256)
def _import_lang_module(lang_name: str, module_name: str) -> ModuleType:
    return importlib.import_module(f"..lang.{lang_name}.{module_name}", __package__)


def load_lang_hook_module(lang_name: str | None, module_name: str) -> ModuleType | None:
    """Load ``desloppify.lang.<lang_name>.<module_name>`` if available."""
    if not lang_name:
        return None
    try:
        return _import_lang_module(lang_name, module_name)
    except Exception:
        return None
