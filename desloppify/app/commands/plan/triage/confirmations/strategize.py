"""Strategize stage confirmation handler.

The strategize stage auto-confirms on record (to avoid breaking downstream
dependency checks).  This handler allows an explicit re-confirmation with
attestation, overwriting the auto-confirmed marker with a human-reviewed one.
"""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message

from .basic import MIN_ATTESTATION_LEN
from .shared import (
    StageConfirmationRequest,
    finalize_stage_confirmation,
)
from ..services import TriageServices, default_triage_services
from ..stages.records import TriageStages


def _validate_strategize_attestation(
    attestation: str,
    stage: str,
    *,
    dimensions: list[str] | None = None,
    score_trend: str | None = None,
    **_kwargs,
) -> str | None:
    """Attestation must reference at least one dimension or the score trend."""
    text = attestation.lower()
    # Check score trend reference
    if score_trend and score_trend.lower() in text:
        return None
    # Check dimension references
    if dimensions:
        for dim in dimensions:
            if dim.lower().replace("_", " ") in text or dim.lower() in text:
                return None
    hints = []
    if dimensions:
        hints.append(f"dimensions: {', '.join(dimensions[:6])}")
    if score_trend:
        hints.append(f"score trend: {score_trend}")
    return (
        "Attestation must reference at least one focus dimension or the score trend.\n"
        f"  Valid references: {'; '.join(hints)}"
    )


def confirm_strategize(
    args: argparse.Namespace,
    plan: dict,
    stages: TriageStages,
    attestation: str | None,
    *,
    services: TriageServices | None = None,
) -> None:
    """Allow explicit re-confirmation of the strategize stage with attestation."""
    resolved_services = services or default_triage_services()

    if "strategize" not in stages:
        print(colorize("  Cannot confirm: strategize stage not recorded.", "red"))
        print(colorize('  Run: desloppify plan triage --stage strategize --report "{...}"', "dim"))
        return

    strat = stages["strategize"]
    # Allow re-confirmation even if already auto-confirmed
    if strat.get("confirmed_at") and strat.get("confirmed_text", "") != "auto-confirmed":
        print(colorize("  Strategize stage already confirmed with attestation.", "green"))
        return

    briefing = plan.get("epic_triage_meta", {}).get("strategist_briefing", {})
    focus_dims = [
        str(entry.get("name", "")).strip()
        for entry in briefing.get("focus_dimensions", [])
        if isinstance(entry, dict) and str(entry.get("name", "")).strip()
    ]
    score_trend = briefing.get("score_trend", "stable")

    print(colorize("  Stage: STRATEGIZE — Big-picture cross-cycle analysis", "bold"))
    print(colorize("  " + "-" * 53, "dim"))
    print(colorize(f"  Score trend: {score_trend}", "dim"))
    print(colorize(f"  Debt trend: {briefing.get('debt_trend', 'stable')}", "dim"))
    if focus_dims:
        print(colorize(f"  Focus dimensions: {', '.join(focus_dims)}", "dim"))

    if not finalize_stage_confirmation(
        plan=plan,
        stages=stages,
        request=StageConfirmationRequest(
            stage="strategize",
            attestation=attestation,
            min_attestation_len=MIN_ATTESTATION_LEN,
            command_hint='desloppify plan triage --confirm strategize --attestation "I have reviewed the strategic analysis..."',
            validation_stage="strategize",
            validate_attestation_fn=_validate_strategize_attestation,
            validation_kwargs={"dimensions": focus_dims, "score_trend": score_trend},
            log_action="triage_confirm_strategize",
        ),
        services=resolved_services,
    ):
        return
    print_user_message(
        "Hey -- strategize is confirmed with attestation. Run "
        "`desloppify plan triage --stage observe --report \"...\"` next."
    )


__all__ = ["confirm_strategize"]
