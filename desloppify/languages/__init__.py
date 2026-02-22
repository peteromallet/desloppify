"""Language registry: plugin registration and language resolution."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from desloppify.languages._framework import (
    discovery,
    registry_state,
    resolution,
    runtime,
)
from desloppify.languages._framework.base.types import LangConfig
from desloppify.languages._framework.contract_validation import validate_lang_contract
from desloppify.languages._framework.policy import REQUIRED_DIRS, REQUIRED_FILES
from desloppify.languages._framework.resolution import (
    auto_detect_lang,
    available_langs,
    get_lang,
    make_lang_config,
)
from desloppify.languages._framework.structure_validation import validate_lang_structure

T = TypeVar("T")


def register_lang(name: str) -> Callable[[T], T]:
    """Decorator to register a language config class.

    Validates structure, instantiates the class, validates the contract,
    and stores the *instance* in the registry.
    """

    def decorator(cls: T) -> T:
        module = inspect.getmodule(cls)
        if module and hasattr(module, "__file__"):
            validate_lang_structure(Path(module.__file__).parent, name)
        if isinstance(cls, type) and issubclass(cls, LangConfig):
            cfg = make_lang_config(name, cls)  # instantiate + validate
            registry_state.register(name, cfg)  # store instance
        else:
            registry_state.register(name, cls)  # test doubles
        return cls

    return decorator


def register_generic_lang(name: str, cfg: LangConfig) -> None:
    """Register a pre-built language plugin instance (no package structure required)."""
    validate_lang_contract(name, cfg)
    registry_state.register(name, cfg)


__all__ = [
    "REQUIRED_FILES",
    "REQUIRED_DIRS",
    "register_lang",
    "register_generic_lang",
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
