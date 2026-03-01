"""Structured IO/output namespace for core APIs and implementations."""

from __future__ import annotations

_IO_NAMESPACE_SHIM = __name__

from . import api, impl

__all__ = ["api", "impl"]
