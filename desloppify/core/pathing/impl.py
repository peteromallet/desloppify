"""Pathing implementation surface.

New code should prefer ``desloppify.core.pathing.api`` unless implementation
helpers are explicitly required.
"""

from __future__ import annotations

_PATHING_IMPL_SHIM = __name__

from desloppify.core.file_paths import *  # noqa: F401,F403
from desloppify.core.file_paths import __all__ as _PATHING_IMPL_ALL

__all__ = list(_PATHING_IMPL_ALL)
