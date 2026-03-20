"""`setup` command package with a stable command entrypoint export."""

from __future__ import annotations

from .cmd import GLOBAL_TARGETS, cmd_setup

__all__ = ["GLOBAL_TARGETS", "cmd_setup"]
