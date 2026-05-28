"""Framework spec registry (analogous to tree-sitter spec registry)."""

from __future__ import annotations

from collections.abc import Iterable

from .types import FrameworkSpec

FRAMEWORK_SPECS: dict[str, FrameworkSpec] = {}

# Per-ecosystem cache for ``framework_source_extensions``. Invalidated by any
# registry mutation (``register_framework_spec``). Keyed by the normalized
# ecosystem string ("" for the unfiltered query) so each call shape gets its
# own slot. In production the registry is immutable after startup, so this
# caches a single tuple per ecosystem for the process lifetime; in tests the
# fixture-driven mutations invalidate it cleanly.
_EXTENSIONS_CACHE: dict[str, tuple[str, ...]] = {}


def _invalidate_extensions_cache() -> None:
    _EXTENSIONS_CACHE.clear()


def register_framework_spec(spec: FrameworkSpec) -> None:
    """Register a framework spec by id."""
    key = str(spec.id or "").strip()
    if not key:
        raise ValueError("FrameworkSpec.id must be non-empty")
    FRAMEWORK_SPECS[key] = spec
    _invalidate_extensions_cache()


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
    from .specs.astro import ASTRO_SPEC
    from .specs.nextjs import NEXTJS_SPEC
    from .specs.svelte import SVELTE_SPEC
    from .specs.vue import VUE_SPEC

    register_framework_spec(NEXTJS_SPEC)
    register_framework_spec(ASTRO_SPEC)
    register_framework_spec(SVELTE_SPEC)
    register_framework_spec(VUE_SPEC)


def ensure_builtin_specs_loaded() -> None:
    """Idempotently load built-in framework specs."""
    _register_builtin_specs()


def framework_source_extensions(ecosystem: str | None = None) -> tuple[str, ...]:
    """Return the sorted, deduplicated source extensions across registered specs.

    Used by dep-graph builders to learn which non-host-language file types
    (e.g. ``.astro``, ``.svelte``, ``.vue``) should be scanned as importers
    of the host language's modules. Lookup is driven by the registry, so
    adding a new framework with ``source_extensions`` automatically extends
    every plugin that calls this — no infrastructure edits required.

    Cached per ecosystem key; ``register_framework_spec`` invalidates the
    cache so tests that mutate the registry see fresh results.
    """
    ensure_builtin_specs_loaded()
    cache_key = (ecosystem or "").strip().lower()
    cached = _EXTENSIONS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result = tuple(
        sorted(
            {
                ext
                for spec in list_framework_specs(ecosystem=ecosystem).values()
                for ext in spec.source_extensions
            }
        )
    )
    _EXTENSIONS_CACHE[cache_key] = result
    return result


__all__ = [
    "FRAMEWORK_SPECS",
    "ensure_builtin_specs_loaded",
    "framework_source_extensions",
    "get_framework_spec",
    "list_framework_specs",
    "register_framework_spec",
]
