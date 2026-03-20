"""Canonical stage command dispatch for triage flow."""

from __future__ import annotations

import argparse

from .observe import cmd_stage_observe
from .organize import cmd_stage_organize
from .reflect import cmd_stage_reflect
from .strategize import cmd_stage_strategize
from ..services import TriageServices
from .enrich import cmd_stage_enrich
from .sense_check import cmd_stage_sense_check

STAGE_COMMAND_HANDLERS = {
    "strategize": cmd_stage_strategize,
    "observe": cmd_stage_observe,
    "reflect": cmd_stage_reflect,
    "organize": cmd_stage_organize,
    "enrich": cmd_stage_enrich,
    "sense-check": cmd_stage_sense_check,
}


def run_stage_command(
    stage: str | None,
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> bool:
    """Run one named triage stage command when available."""
    handler = STAGE_COMMAND_HANDLERS.get(stage or "")
    if handler is None:
        return False
    handler(args, services=services)
    return True


__all__ = [
    "STAGE_COMMAND_HANDLERS",
    "cmd_stage_enrich",
    "cmd_stage_observe",
    "cmd_stage_organize",
    "cmd_stage_reflect",
    "cmd_stage_sense_check",
    "cmd_stage_strategize",
    "run_stage_command",
]
