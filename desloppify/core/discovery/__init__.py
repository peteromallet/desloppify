"""Structured discovery namespace for core APIs and implementations."""

from __future__ import annotations

_DISCOVERY_NAMESPACE_SHIM = __name__

from . import api

__all__ = ["api"]
