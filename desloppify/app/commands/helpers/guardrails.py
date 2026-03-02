"""Shared synthesis guardrail banner helpers for command entrypoints."""

from __future__ import annotations

import sys

from desloppify.core.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.core.output_api import colorize
from desloppify.engine.plan import load_plan, synthesis_phase_banner


def print_synthesis_guardrail_banner(*, plan: dict | None = None) -> None:
    """Print synthesis phase guardrail banner with visible load-failure warnings."""
    try:
        resolved_plan = plan if isinstance(plan, dict) else load_plan()
        banner = synthesis_phase_banner(resolved_plan)
    except PLAN_LOAD_EXCEPTIONS as exc:
        print(
            colorize(
                "  Warning: synthesis guardrail unavailable "
                f"({exc.__class__.__name__}: {exc}).",
                "yellow",
            ),
            file=sys.stderr,
        )
        return
    if banner:
        print(colorize(f"  {banner}", "yellow"))


__all__ = ["print_synthesis_guardrail_banner"]
