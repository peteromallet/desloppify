"""Shared degraded-plan warning helpers for resolve flows."""

from __future__ import annotations

import sys

from desloppify.base.output.terminal import colorize

_warned_degraded_mode = False


def warn_plan_load_degraded_once(*, error_kind: str | None, behavior: str) -> None:
    """Print one consistent warning when resolve behavior degrades."""
    global _warned_degraded_mode
    if _warned_degraded_mode:
        return
    _warned_degraded_mode = True

    detail = f" ({error_kind})" if error_kind else ""
    print(
        colorize(
            "  Warning: resolve is running in degraded mode because the living "
            f"plan could not be loaded{detail}.",
            "yellow",
        ),
        file=sys.stderr,
    )
    print(
        colorize(f"  {behavior}", "dim"),
        file=sys.stderr,
    )


def _reset_degraded_plan_warning_for_tests() -> None:
    """Test helper to reset warning dedupe state."""
    global _warned_degraded_mode
    _warned_degraded_mode = False


__all__ = [
    "warn_plan_load_degraded_once",
]
