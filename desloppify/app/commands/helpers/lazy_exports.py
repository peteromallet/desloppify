"""Shared lazy-export helpers for command package ``__init__`` modules."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping, MutableMapping


def lazy_module_getattr(
    *,
    name: str,
    module_name: str,
    import_target: str,
    export_names: Iterable[str],
    namespace: MutableMapping[str, object],
) -> object:
    """Lazily import one exported attribute from a sibling command module."""
    allowed = set(export_names)
    if name not in allowed:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(import_target, module_name), name)
    namespace[name] = value
    return value


def lazy_module_dir(
    *,
    namespace: Mapping[str, object],
    export_names: Iterable[str],
) -> list[str]:
    """Return module dir() entries including lazy exports."""
    return sorted(set(namespace) | set(export_names))

