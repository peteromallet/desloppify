"""Shared language-framework internals.

This package contains framework code used by all language plugins:
- config/runtime contracts
- plugin discovery/registration state
- shared detect-command factories
- shared finding factories and facade helpers
"""

from __future__ import annotations

from .base.types import (
    BoundaryRule,
    DetectorPhase,
    FixerConfig,
    FixResult,
    LangConfig,
    LangValueSpec,
)
from .resolution import auto_detect_lang, available_langs, get_lang, make_lang_config

__all__ = [
    "BoundaryRule",
    "DetectorPhase",
    "FixerConfig",
    "FixResult",
    "LangConfig",
    "LangValueSpec",
    "auto_detect_lang",
    "available_langs",
    "get_lang",
    "make_lang_config",
]
