"""Completion and confirmation collaborators for the Codex triage pipeline."""

from __future__ import annotations

import argparse
import time
from collections.abc import Mapping
from typing import Any

from desloppify.base.output.terminal import colorize

from ..services import TriageServices
from .orchestrator_common import STAGES
from .stage_validation import build_auto_attestation, validate_stage


def is_full_stage_run(stages_to_run: list[str]) -> bool:
    """True when the pipeline was asked to run the full triage stage set."""
    requested = set(stages_to_run)
    return requested == set(STAGES) or requested == (set(STAGES) - {"strategize"})


def all_stage_results_successful(
    *,
    stages_to_run: list[str],
    stage_results: Mapping[str, Mapping[str, Any]],
) -> bool:
    """True when each requested stage is confirmed or already confirmed."""
    for stage in stages_to_run:
        status = str(stage_results.get(stage, {}).get("status", ""))
        if status not in {"confirmed", "skipped"}:
            return False
    return True


def print_not_finalized_message(reason: str) -> None:
    """Emit a consistent next-step message when auto-completion is skipped/blocked."""
    print(colorize(f"\n  Stages complete, triage not finalized ({reason}).", "yellow"))
    print(
        colorize(
            '  Finalize manually: desloppify plan triage --complete --strategy "<execution plan>"',
            "dim",
        )
    )


def validate_and_confirm_stage(
    *,
    stage: str,
    args: argparse.Namespace,
    services: TriageServices,
    triage_input: Any,
    state: Any,
    repo_root,
    stage_start: float,
    append_run_log,
) -> tuple[bool, dict, str]:
    """Run shared stage validation + confirmation flow."""
    plan = services.load_plan()

    ok, error_msg = validate_stage(
        stage,
        plan,
        state,
        repo_root,
        triage_input=triage_input,
    )
    if not ok:
        elapsed = int(time.monotonic() - stage_start)
        print(colorize(f"  Stage {stage}: validation failed: {error_msg}", "red"))
        print(colorize("  Re-run to resume.", "dim"))
        append_run_log(
            f"stage-validation-failed stage={stage} elapsed={elapsed}s error={error_msg}"
        )
        return (
            False,
            {
                "status": "validation_failed",
                "elapsed_seconds": elapsed,
                "error": error_msg,
            },
            "",
        )

    attestation = build_auto_attestation(stage, plan, triage_input)
    confirm_args = argparse.Namespace(
        confirm=stage,
        attestation=attestation,
        state=getattr(args, "state", None),
    )

    from ..confirmations.router import cmd_confirm_stage

    cmd_confirm_stage(confirm_args, services=services)

    plan = services.load_plan()
    meta = plan.get("epic_triage_meta", {})
    stages_data = meta.get("triage_stages", {})
    elapsed = int(time.monotonic() - stage_start)
    if stage in stages_data and stages_data[stage].get("confirmed_at"):
        print(colorize(f"  Stage {stage}: confirmed ({elapsed}s).", "green"))
        append_run_log(f"stage-confirmed stage={stage} elapsed={elapsed}s")
        report = stages_data.get(stage, {}).get("report", "")
        return (
            True,
            {"status": "confirmed", "elapsed_seconds": elapsed},
            report,
        )

    print(colorize(f"  Stage {stage}: auto-confirmation did not take effect.", "red"))
    print(colorize("  Re-run to resume.", "dim"))
    append_run_log(f"stage-confirm-failed stage={stage} elapsed={elapsed}s")
    return (
        False,
        {"status": "confirm_failed", "elapsed_seconds": elapsed},
        "",
    )


def build_completion_strategy(stages_data: Mapping[str, Mapping[str, Any]]) -> str:
    """Derive a completion strategy from stage reports."""
    strategy_parts: list[str] = []
    recorded_stages: list[str] = []
    for stage in STAGES:
        report = str(stages_data.get(stage, {}).get("report", ""))
        if report:
            recorded_stages.append(stage)
            strategy_parts.append(f"[{stage}] {report[:200]}")
    strategy = " ".join(strategy_parts)
    if len(strategy) < 200:
        if recorded_stages:
            stage_list = ", ".join(recorded_stages)
            summary = (
                f"Triage covered {len(recorded_stages)} stage(s): {stage_list}. "
                "Use the recorded stage reports as the execution plan, preserve the "
                "observe and reflect evidence trail, keep organize and enrich changes "
                "aligned with the recorded dispositions, and verify each cluster before completion."
            )
            strategy = f"{strategy} {summary}".strip()
        else:
            strategy = (
                "Triage completed without recorded stage reports. Before completion, capture "
                "the execution order, the cluster or skip decisions that will change plan state, "
                "and the verification steps needed to confirm the resulting queue is correct."
            )
    return strategy


def complete_pipeline(
    *,
    args: argparse.Namespace,
    services: TriageServices,
    plan: Mapping[str, Any],
    strategy: str,
    triage_input: Any,
) -> bool:
    """Run the triage completion coordinator and report success."""
    completed_before = plan.get("epic_triage_meta", {}).get("last_completed_at")

    print(colorize("\n  Completing triage...", "bold"))

    attestation = build_auto_attestation("sense-check", plan, triage_input)
    complete_args = argparse.Namespace(
        complete=True,
        strategy=strategy[:2000],
        attestation=attestation,
        state=getattr(args, "state", None),
    )

    from ..stages.completion import _cmd_triage_complete

    _cmd_triage_complete(complete_args, services=services)

    completed_after = (
        services.load_plan().get("epic_triage_meta", {}).get("last_completed_at")
    )
    return bool(completed_after and completed_after != completed_before)


__all__ = [
    "all_stage_results_successful",
    "build_completion_strategy",
    "complete_pipeline",
    "is_full_stage_run",
    "print_not_finalized_message",
    "validate_and_confirm_stage",
]
