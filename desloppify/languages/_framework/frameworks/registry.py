"""Framework spec registry (analogous to tree-sitter spec registry)."""

from __future__ import annotations

from collections.abc import Iterable

from .types import FrameworkSpec

FRAMEWORK_SPECS: dict[str, FrameworkSpec] = {}


def register_framework_spec(spec: FrameworkSpec) -> None:
    """Register a framework spec by id."""
    key = str(spec.id or "").strip()
    if not key:
        raise ValueError("FrameworkSpec.id must be non-empty")
    FRAMEWORK_SPECS[key] = spec


def get_framework_spec(framework_id: str) -> FrameworkSpec | None:
    """Return a registered framework spec by id."""
    key = str(framework_id or "").strip()
    if not key:
        return None
    return FRAMEWORK_SPECS.get(key)


def list_framework_specs(*, ecosystem: str | None = None) -> dict[str, FrameworkSpec]:
    """Return a copy of the framework registry, optionally filtered by ecosystem."""
    if ecosystem is None:
        return dict(FRAMEWORK_SPECS)
    eco = str(ecosystem or "").strip().lower()
    if not eco:
        return dict(FRAMEWORK_SPECS)
    return {k: v for k, v in FRAMEWORK_SPECS.items() if str(v.ecosystem).lower() == eco}


def _register_builtin_specs() -> None:
    """Register built-in framework specs shipped with the repo."""
    if FRAMEWORK_SPECS:
        return
    from .specs.nextjs import NEXTJS_SPEC

    register_framework_spec(NEXTJS_SPEC)


def ensure_builtin_specs_loaded() -> None:
    """Idempotently load built-in framework specs."""
    _register_builtin_specs()


__all__ = [
    "FRAMEWORK_SPECS",
    "ensure_builtin_specs_loaded",
    "get_framework_spec",
    "list_framework_specs",
    "register_framework_spec",
]
