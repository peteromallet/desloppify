"""Sense-check stage command flow."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.output.terminal import colorize

from .records import record_sense_check_stage, resolve_reusable_report
from .helpers import active_triage_issue_scope, value_check_targets
from ..validation.enrich_quality import evaluate_enrich_quality
from ..validation.enrich_checks import (
    _steps_missing_issue_refs,
    _steps_with_bad_paths,
    _steps_with_vague_detail,
    _steps_without_effort,
    _underspecified_steps,
)
from ..review_coverage import open_review_ids_from_state
from ..stage_queue import has_triage_in_queue, print_cascade_clear_feedback
from ..services import TriageServices, default_triage_services
from .enrich import ColorizeFn


@dataclass(frozen=True)
class SenseCheckStageDeps:
    has_triage_in_queue: Callable[[dict], bool] = has_triage_in_queue
    resolve_reusable_report: Callable[[str | None, dict | None], tuple[str | None, bool]] = (
        resolve_reusable_report
    )
    record_sense_check_stage: Callable[..., list[str]] = record_sense_check_stage
    colorize: ColorizeFn = colorize
    default_triage_services: Callable[[], TriageServices] = default_triage_services
    print_cascade_clear_feedback: Callable[[list[str], dict], None] = print_cascade_clear_feedback
    get_project_root: Callable[[], Path] | None = None
    underspecified_steps: Callable[[dict], list[tuple[str, int, int]]] = _underspecified_steps
    steps_missing_issue_refs: Callable[[dict], list[tuple[str, int, int]]] = _steps_missing_issue_refs
    steps_with_bad_paths: Callable[[dict, Path], list[tuple[str, int, list[str]]]] = _steps_with_bad_paths
    steps_with_vague_detail: Callable[[dict, Path], list[tuple[str, int, str]]] = _steps_with_vague_detail
    steps_without_effort: Callable[[dict], list[tuple[str, int, int]]] = _steps_without_effort


def _sense_check_report(
    args: argparse.Namespace,
    stages: dict,
    *,
    deps: SenseCheckStageDeps,
) -> tuple[str | None, bool, dict | None]:
    existing_stage = stages.get("sense-check")
    report = getattr(args, "report", None)
    report, is_reuse = deps.resolve_reusable_report(report, existing_stage)
    return report, is_reuse, existing_stage


def _sense_check_quality_problems(
    plan: dict,
    state: dict,
    *,
    deps: SenseCheckStageDeps,
) -> list[str]:
    get_project_root = deps.get_project_root
    if get_project_root is None:
        from desloppify.base.discovery.paths import get_project_root

    repo_root = get_project_root()
    triage_ids = active_triage_issue_scope(plan, state)
    quality_report = evaluate_enrich_quality(
        plan,
        repo_root,
        phase_label="sense-check",
        bad_paths_severity="warning",
        missing_effort_severity="failure",
        include_missing_issue_refs=True,
        include_vague_detail=True,
        stale_issue_refs_severity=None,
        triage_issue_ids=triage_ids,
    )
    return [issue.message for issue in quality_report.failures]


def _print_sense_check_problems(
    problems: list[str],
    *,
    colorize_fn: ColorizeFn,
) -> None:
    print(colorize_fn("  Cannot record sense-check — plan still has issues:", "red"))
    for problem in problems:
        print(colorize_fn(f"    • {problem}", "yellow"))
    print(colorize_fn("  Fix these before recording the sense-check stage.", "dim"))


def _report_length_ok(report: str | None, *, colorize_fn: ColorizeFn) -> bool:
    if not report:
        print(colorize_fn("  --report is required for --stage sense-check.", "red"))
        print(
            colorize_fn(
                "  Describe what the content and structure subagents found and fixed.",
                "dim",
            )
        )
        return False
    if len(report) < 100:
        print(colorize_fn(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        return False
    return True


def _sense_check_evidence_failures(
    report: str,
    *,
    plan: dict,
    state: dict,
) -> tuple[list[object], list[object]]:
    from .evidence_parsing import (
        validate_report_has_file_paths,
        validate_report_references_clusters,
    )
    from .helpers import scoped_manual_clusters_with_issues

    failures: list[object] = []
    triage_scope = active_triage_issue_scope(plan, state)
    open_review_ids = (
        open_review_ids_from_state(state) if triage_scope is None else triage_scope
    )
    if open_review_ids:
        failures.extend(validate_report_has_file_paths(report) or [])

    cluster_names = scoped_manual_clusters_with_issues(plan, state)
    if cluster_names:
        failures.extend(validate_report_references_clusters(report, cluster_names) or [])

    blocking = [failure for failure in failures if failure.blocking]
    advisory = [failure for failure in failures if not failure.blocking]
    return blocking, advisory


def _print_evidence_failures(
    failures: list[object],
    *,
    stage_label: str,
    colorize_fn: ColorizeFn,
    style: str,
) -> None:
    from .evidence_parsing import format_evidence_failures

    if not failures:
        return
    print(colorize_fn(format_evidence_failures(failures, stage_label=stage_label), style))


def run_stage_sense_check(
    args: argparse.Namespace,
    *,
    services: TriageServices | None,
    deps: SenseCheckStageDeps | None = None,
) -> None:
    """Record the SENSE-CHECK stage after rerunning enrich-level validations."""
    resolved_deps = deps or SenseCheckStageDeps()
    report: str | None = getattr(args, "report", None)

    resolved_services = services or resolved_deps.default_triage_services()
    plan = resolved_services.load_plan()
    state = resolved_services.command_runtime(args).state

    if not resolved_deps.has_triage_in_queue(plan):
        print(resolved_deps.colorize("  No planning stages in the queue — nothing to sense-check.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    report, is_reuse, existing_stage = _sense_check_report(
        args,
        stages,
        deps=resolved_deps,
    )

    if not stages.get("enrich", {}).get("confirmed_at"):
        print(resolved_deps.colorize("  Cannot sense-check: enrich stage not confirmed.", "red"))
        print(resolved_deps.colorize("  Run: desloppify plan triage --confirm enrich", "dim"))
        return

    problems = _sense_check_quality_problems(plan, state, deps=resolved_deps)
    if problems:
        _print_sense_check_problems(problems, colorize_fn=resolved_deps.colorize)
        return

    print(resolved_deps.colorize("  All enrich-level checks pass after sense-check.", "green"))

    if not _report_length_ok(report, colorize_fn=resolved_deps.colorize):
        return

    blocking_ev, advisory_ev = _sense_check_evidence_failures(report, plan=plan, state=state)
    if blocking_ev:
        _print_evidence_failures(
            blocking_ev,
            stage_label="sense-check",
            colorize_fn=resolved_deps.colorize,
            style="red",
        )
        return
    if advisory_ev:
        _print_evidence_failures(
            advisory_ev,
            stage_label="sense-check",
            colorize_fn=resolved_deps.colorize,
            style="yellow",
        )

    stages = meta.setdefault("triage_stages", {})
    frozen_value_targets = getattr(args, "value_targets", None)
    if not isinstance(frozen_value_targets, list):
        if existing_stage and isinstance(existing_stage.get("value_targets"), list):
            frozen_value_targets = list(existing_stage["value_targets"])
        else:
            frozen_value_targets = value_check_targets(plan, state)
    cleared = resolved_deps.record_sense_check_stage(
        stages,
        report=report,
        existing_stage=existing_stage,
        is_reuse=is_reuse,
        value_targets=frozen_value_targets,
    )

    resolved_services.save_plan(plan)

    resolved_services.append_log_entry(
        plan,
        "triage_sense_check",
        actor="user",
        detail={"reuse": is_reuse},
    )
    resolved_services.save_plan(plan)

    print(resolved_deps.colorize("  Sense-check stage recorded.", "green"))
    if is_reuse:
        print(resolved_deps.colorize("  Sense-check data preserved (no changes).", "dim"))
        if cleared:
            resolved_deps.print_cascade_clear_feedback(cleared, stages)
    else:
        print(resolved_deps.colorize("  Now confirm the sense-check.", "yellow"))
        print(resolved_deps.colorize("    desloppify plan triage --confirm sense-check", "dim"))


def cmd_stage_sense_check(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for sense-check stage recording."""
    run_stage_sense_check(args, services=services)


__all__ = [
    "SenseCheckStageDeps",
    "cmd_stage_sense_check",
    "record_sense_check_stage",
    "run_stage_sense_check",
]
