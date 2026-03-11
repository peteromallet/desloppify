"""Shared triage lifecycle helpers used by command and runner entrypoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from desloppify.engine.plan_state import PlanModel
from desloppify.engine.plan_triage import (
    TRIAGE_STAGE_IDS,
    TriageStartDecision,
    decide_triage_start,
)
from desloppify.base.output.terminal import colorize
from desloppify.state_io import StateModel

from .helpers import has_triage_in_queue, inject_triage_stages
from .services import TriageServices

TriageStartStatus = Literal["started", "blocked", "already_active"]


@dataclass(frozen=True)
class TriageStartOutcome:
    """Lifecycle result for triage-start attempts."""

    status: TriageStartStatus
    reason: str


@dataclass(frozen=True)
class TriageStartRequest:
    """Input contract for triage-start side effects and logging."""

    state: StateModel | None = None
    attestation: str | None = None
    log_action: str | None = None
    log_actor: str = "system"
    log_detail: Mapping[str, object] | None = None
    start_message: str | None = None
    start_message_style: str = "cyan"


@dataclass(frozen=True)
class TriageLifecycleDeps:
    """Dependency seams for triage lifecycle starts (for tests/callers)."""

    has_triage_in_queue: Callable[[PlanModel], bool] = has_triage_in_queue
    inject_triage_stages: Callable[[PlanModel], None] = inject_triage_stages
    decide_triage_start: Callable[..., TriageStartDecision] = decide_triage_start
    colorize: Callable[[str, str], str] = colorize


def _print_triage_start_block(reason: str, *, deps: TriageLifecycleDeps) -> None:
    """Render reason-specific guard guidance for triage auto-start attempts."""
    if reason == "unfinished_triage_stage_records":
        print(
            deps.colorize(
                "  Cannot start triage while previous stage reports are still unconfirmed.",
                "red",
            )
        )
        print(
            deps.colorize(
                "  Confirm or complete the current triage stages first, or pass --attestation "
                "(30+ chars) to override explicitly.",
                "dim",
            )
        )
        return

    print(deps.colorize("  Cannot start triage while objective backlog is still open.", "red"))
    print(
        deps.colorize(
            "  Finish current objective work first, or pass --attestation "
            "(30+ chars) to override this guard explicitly.",
            "dim",
        )
    )


def ensure_triage_started(
    plan: PlanModel,
    *,
    services: TriageServices,
    request: TriageStartRequest | None = None,
    deps: TriageLifecycleDeps | None = None,
) -> TriageStartOutcome:
    """Ensure triage stages are injected or return a blocked/already-active outcome."""
    start_request = request or TriageStartRequest()
    resolved_deps = deps or TriageLifecycleDeps()
    meta = plan.setdefault("epic_triage_meta", {})

    if resolved_deps.has_triage_in_queue(plan):
        meta.pop("triage_start_blocked", None)
        return TriageStartOutcome(status="already_active", reason="already_active")

    decision = resolved_deps.decide_triage_start(
        plan,
        start_request.state,
        explicit_start=True,
        attested_override=bool(
            start_request.attestation and len(start_request.attestation.strip()) >= 30
        ),
    )
    if decision.action == "defer":
        meta["triage_start_blocked"] = decision.reason
        services.save_plan(plan)
        _print_triage_start_block(decision.reason, deps=resolved_deps)
        return TriageStartOutcome(status="blocked", reason=decision.reason)

    resolved_deps.inject_triage_stages(plan)
    meta.pop("triage_start_blocked", None)
    meta.setdefault("triage_stages", {})

    if start_request.log_action:
        detail = dict(start_request.log_detail or {})
        detail.setdefault("injected_stage_ids", list(TRIAGE_STAGE_IDS))
        services.append_log_entry(
            plan,
            start_request.log_action,
            actor=start_request.log_actor,
            detail=detail,
        )

    services.save_plan(plan)
    if start_request.start_message:
        print(
            resolved_deps.colorize(
                start_request.start_message,
                start_request.start_message_style,
            )
        )
    return TriageStartOutcome(status="started", reason=decision.reason)


__all__ = [
    "TriageLifecycleDeps",
    "TriageStartRequest",
    "TriageStartOutcome",
    "ensure_triage_started",
]
