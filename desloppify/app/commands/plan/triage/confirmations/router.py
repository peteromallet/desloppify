"""Canonical confirmation-stage router for triage."""

from __future__ import annotations

import argparse

from .basic import (
    MIN_ATTESTATION_LEN,
    confirm_observe,
    confirm_reflect,
    validate_attestation,
)
from .enrich import confirm_enrich, confirm_sense_check
from .organize import confirm_organize
from .strategize import confirm_strategize
from ..services import TriageServices, default_triage_services


def cmd_confirm_stage(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Route ``--confirm <stage>`` to the stage-specific confirmation handler."""
    resolved_services = services or default_triage_services()
    confirm_stage = getattr(args, "confirm", None)
    attestation = getattr(args, "attestation", None)
    plan = resolved_services.load_plan()
    stages = plan.get("epic_triage_meta", {}).get("triage_stages", {})

    handlers = {
        "strategize": confirm_strategize,
        "observe": confirm_observe,
        "reflect": confirm_reflect,
        "organize": confirm_organize,
        "enrich": confirm_enrich,
        "sense-check": confirm_sense_check,
    }
    handler = handlers.get(confirm_stage)
    if handler is None:
        return
    handler(args, plan, stages, attestation, services=resolved_services)


__all__ = ["MIN_ATTESTATION_LEN", "cmd_confirm_stage", "validate_attestation"]
