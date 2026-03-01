"""Shared exception tuples used across command/render flows."""

from __future__ import annotations

PLAN_LOAD_EXCEPTIONS = (
    ImportError,
    AttributeError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
)

__all__ = ["PLAN_LOAD_EXCEPTIONS"]
