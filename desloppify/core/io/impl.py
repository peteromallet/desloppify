"""Output implementation surface."""

from __future__ import annotations

_IO_IMPL_SHIM = __name__

from desloppify.core.output import *  # noqa: F401,F403
from desloppify.core.output import __all__ as _IO_IMPL_ALL

__all__ = list(_IO_IMPL_ALL)
