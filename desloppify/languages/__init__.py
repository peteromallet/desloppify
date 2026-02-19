"""Language registry: plugin registration and language resolution."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from desloppify.languages.framework import (
    discovery,
    registry_state,
    resolution,
    runtime,
)
from desloppify.languages.framework.base.types import LangConfig
from desloppify.languages.framework.contract_validation import validate_lang_contract
from desloppify.languages.framework.policy import REQUIRED_DIRS, REQUIRED_FILES
from desloppify.languages.framework.resolution import (
    auto_detect_lang,
    available_langs,
    get_lang,
    make_lang_config,
)
from desloppify.languages.framework.structure_validation import validate_lang_structure

T = TypeVar("T")


def register_lang(name: str) -> Callable[[T], T]:
    """Decorator to register a language config module."""

    def decorator(cls: T) -> T:
        module = inspect.getmodule(cls)
        if module and hasattr(module, "__file__"):
            validate_lang_structure(Path(module.__file__).parent, name)
        # Fail fast for concrete LangConfig plugins while keeping decorator-friendly
        # behavior for plain test doubles and scaffolds.
        if isinstance(cls, type) and issubclass(cls, LangConfig):
            make_lang_config(name, cls)
        registry_state._registry[name] = cls
        return cls

    return decorator


__all__ = [
    "REQUIRED_FILES",
    "REQUIRED_DIRS",
    "register_lang",
    "get_lang",
    "available_langs",
    "auto_detect_lang",
    "make_lang_config",
    "validate_lang_structure",
    "validate_lang_contract",
    "discovery",
    "registry_state",
    "resolution",
    "runtime",
]
