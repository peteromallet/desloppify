"""Structured pathing namespace for core APIs and implementations."""

from __future__ import annotations

_PATHING_NAMESPACE_SHIM = __name__

from . import api, impl

__all__ = ["api", "impl"]
