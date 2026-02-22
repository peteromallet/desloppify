"""Shared mutable registry state for language plugin discovery."""

from __future__ import annotations

_registry: dict = {}  # str → LangConfig instance
_load_attempted = False
_load_errors: dict[str, BaseException] = {}


# ── Public API ────────────────────────────────────────────


def register(name: str, cfg) -> None:
    """Register a language config by name."""
    _registry[name] = cfg


def get(name: str):
    """Get a language config by name, or None."""
    return _registry.get(name)


def all_items():
    """Return all (name, config) pairs."""
    return _registry.items()


def all_keys() -> list[str]:
    """Return all registered language names."""
    return list(_registry.keys())


def is_registered(name: str) -> bool:
    """Check if a language is registered."""
    return name in _registry


def remove(name: str) -> None:
    """Remove a language by name (for testing)."""
    _registry.pop(name, None)


def clear() -> None:
    """Clear all registrations (for testing)."""
    _registry.clear()


def set_load_attempted(value: bool) -> None:
    """Set the load-attempted flag."""
    global _load_attempted
    _load_attempted = value


def was_load_attempted() -> bool:
    """Check whether plugin loading has been attempted."""
    return _load_attempted


def record_load_error(name: str, error: BaseException) -> None:
    """Record an import error for a language module."""
    _load_errors[name] = error


def set_load_errors(errors: dict[str, BaseException]) -> None:
    """Replace the full load-errors dict (used by discovery)."""
    global _load_errors
    _load_errors = errors


def get_load_errors() -> dict[str, BaseException]:
    """Return the dict of load errors."""
    return _load_errors
