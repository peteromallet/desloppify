"""Shared helpers for triage stage confirmation flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from desloppify.base.output.terminal import colorize
from desloppify.state_io import utc_now

from ..stage_queue import purge_triage_stage

_STAGE_LABELS = {
    "strategize": "Strategize",
    "observe": "Observe",
    "reflect": "Reflect",
    "organize": "Organize",
    "enrich": "Enrich",
    "sense-check": "Sense-check",
}


@dataclass(frozen=True)
class StageConfirmationRequest:
    """Input contract for shared stage-confirmation behavior."""

    stage: str
    attestation: str | None
    min_attestation_len: int
    command_hint: str
    validation_stage: str
    validate_attestation_fn: Callable[..., str | None]
    log_action: str
    validation_kwargs: dict[str, object] | None = None
    log_detail: dict[str, object] | None = None
    not_satisfied_hint: str | None = None


def ensure_stage_is_confirmable(stages: dict, *, stage: str) -> bool:
    """Validate stage presence/confirmation status before confirm flow runs."""
    if stage not in stages:
        print(colorize(f"  Cannot confirm: {stage} stage not recorded.", "red"))
        print(colorize(f'  Run: desloppify plan triage --stage {stage} --report "..."', "dim"))
        return False
    if stages[stage].get("confirmed_at"):
        label = _STAGE_LABELS.get(stage, stage.title())
        print(colorize(f"  {label} stage already confirmed.", "green"))
        return False
    return True


def finalize_stage_confirmation(
    *,
    plan: dict,
    stages: dict,
    request: StageConfirmationRequest,
    services,
) -> bool:
    """Apply shared attestation validation + state mutation + log/save flow."""
    attestation_text = (request.attestation or "").strip()
    if len(attestation_text) < request.min_attestation_len:
        if attestation_text:
            print(
                colorize(
                    (
                        "\n  Attestation too short "
                        f"({len(attestation_text)} chars, min {request.min_attestation_len})."
                    ),
                    "red",
                )
            )
        print(colorize("\n  If satisfied, confirm:", "dim"))
        print(colorize(f"    {request.command_hint}", "dim"))
        if request.not_satisfied_hint:
            print(colorize(f"  {request.not_satisfied_hint}", "dim"))
        return False

    err = request.validate_attestation_fn(
        attestation_text,
        request.validation_stage,
        **(request.validation_kwargs or {}),
    )
    if err:
        print(colorize(f"\n  {err}", "red"))
        return False

    stages[request.stage]["confirmed_at"] = utc_now()
    stages[request.stage]["confirmed_text"] = attestation_text
    purge_triage_stage(plan, request.stage)

    detail = {"attestation": attestation_text}
    if request.log_detail:
        detail.update(request.log_detail)
    services.append_log_entry(
        plan,
        request.log_action,
        actor="user",
        detail=detail,
    )
    services.save_plan(plan)
    label = _STAGE_LABELS.get(request.stage, request.stage.title())
    print(colorize(f'  ✓ {label} confirmed: "{attestation_text}"', "green"))
    return True


__all__ = [
    "StageConfirmationRequest",
    "ensure_stage_is_confirmable",
    "finalize_stage_confirmation",
]
