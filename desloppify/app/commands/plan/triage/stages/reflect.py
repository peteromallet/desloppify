"""Reflect stage command flow."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.state_io import utc_now

from ..display.dashboard import print_reflect_result
from ..stage_queue import cascade_clear_dispositions, cascade_clear_later_confirmations, has_triage_in_queue
from ..services import TriageServices, default_triage_services
from ..validation.reflect_accounting import (
    BacklogDecision,
    ReflectDisposition,
    parse_backlog_decisions,
    parse_reflect_dispositions,
    validate_backlog_decisions,
    validate_reflect_accounting,
)
from ..validation.stage_policy import auto_confirm_observe_if_attested
from .flow_helpers import validate_stage_report_length
from .records import resolve_reusable_report
from .rendering import _print_reflect_report_requirement


def _validate_recurring_dimension_mentions(
    *,
    report: str,
    recurring_dims: list[str],
    recurring: dict[str, dict[str, list[str]]],
) -> bool:
    if not recurring_dims:
        return True
    report_lower = report.lower()
    mentioned = [dim for dim in recurring_dims if dim.lower() in report_lower]
    if mentioned:
        return True
    print(colorize("  Recurring patterns detected but not addressed in report:", "red"))
    for dim in recurring_dims:
        info = recurring[dim]
        print(
            colorize(
                f"    {dim}: {len(info['resolved'])} resolved, "
                f"{len(info['open'])} still open — potential loop",
                "yellow",
            )
        )
    print(colorize("  Your report must mention at least one recurring dimension name.", "dim"))
    return False


def _validate_reflect_submission(
    *,
    report: str,
    plan: dict,
    state: dict,
    stages: dict,
    attestation: str | None,
    services: TriageServices,
) -> tuple[object, int, dict, list[str], set[str], list[str], list[str], list[ReflectDisposition], list[BacklogDecision]] | None:
    if "observe" not in stages:
        print(colorize("  Cannot reflect: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return None

    triage_input = services.collect_triage_input(plan, state)
    if not auto_confirm_observe_if_attested(
        plan=plan,
        stages=stages,
        attestation=attestation,
        triage_input=triage_input,
        save_plan_fn=services.save_plan,
    ):
        return None

    review_issues = getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {}))
    issue_count = len(review_issues)
    if not validate_stage_report_length(
        report=report,
        issue_count=issue_count,
        guidance="  Describe how current issues relate to previously completed work.",
    ):
        return None

    recurring = services.detect_recurring_patterns(
        review_issues,
        triage_input.resolved_issues,
    )
    recurring_dims = sorted(recurring.keys())
    if not _validate_recurring_dimension_mentions(
        report=report,
        recurring_dims=recurring_dims,
        recurring=recurring,
    ):
        return None

    valid_ids = set(review_issues.keys())

    # Exclude issues already auto-skipped by observe from reflect accounting
    meta = plan.get("epic_triage_meta", {})
    dispositions = meta.get("issue_dispositions", {})
    auto_skipped_ids = {
        issue_id for issue_id, disp in dispositions.items()
        if disp.get("decision_source") == "observe_auto"
    }
    accounting_ids = valid_ids - auto_skipped_ids

    accounting_ok, cited_ids, missing_ids, duplicate_ids = validate_reflect_accounting(
        report=report,
        valid_ids=accounting_ids,
    )
    if not accounting_ok:
        return None

    from .evidence_parsing import (
        format_evidence_failures,
        validate_reflect_skip_evidence,
    )

    blocking_skips = [
        failure
        for failure in validate_reflect_skip_evidence(report)
        if failure.blocking
    ]
    if blocking_skips:
        print(colorize(format_evidence_failures(blocking_skips, stage_label="reflect"), "red"))
        return None

    # Parse structured disposition ledger from Coverage Ledger section
    disposition_ledger = parse_reflect_dispositions(report, valid_ids)

    # Validate backlog decisions for auto-clusters (warn, don't block)
    auto_clusters = getattr(triage_input, "auto_clusters", None) or {}
    auto_cluster_names = sorted(auto_clusters.keys())
    _, backlog_warnings = validate_backlog_decisions(
        report=report,
        auto_cluster_names=auto_cluster_names,
    )
    for warning in backlog_warnings:
        print(colorize(f"  Warning: {warning}", "yellow"))

    backlog_decisions = parse_backlog_decisions(report)

    return (
        triage_input,
        issue_count,
        recurring,
        recurring_dims,
        cited_ids,
        missing_ids,
        duplicate_ids,
        disposition_ledger,
        backlog_decisions,
    )


def _persist_reflect_stage(
    *,
    plan: dict,
    meta: dict,
    stages: dict,
    report: str,
    issue_count: int,
    cited_ids: set[str],
    missing_ids: list[str],
    duplicate_ids: list[str],
    recurring_dims: list[str],
    disposition_ledger: list[ReflectDisposition],
    backlog_decisions: list[BacklogDecision],
    existing_stage: dict | None,
    is_reuse: bool,
    services: TriageServices,
) -> tuple[dict, list[str]]:
    stages = meta.setdefault("triage_stages", {})

    # On fresh reflect run, cascade-clear reflect decisions from dispositions
    if not is_reuse:
        cascade_clear_dispositions(meta, "reflect")

    reflect_stage: dict = {
        "stage": "reflect",
        "report": report,
        "cited_ids": sorted(cited_ids),
        "timestamp": utc_now(),
        "issue_count": issue_count,
        "missing_issue_ids": missing_ids,
        "duplicate_issue_ids": duplicate_ids,
        "recurring_dims": recurring_dims,
    }
    if disposition_ledger:
        reflect_stage["disposition_ledger"] = [d.to_dict() for d in disposition_ledger]
        # Write reflect decisions to the disposition map
        dispositions = meta.setdefault("issue_dispositions", {})
        for d in disposition_ledger:
            entry = dispositions.setdefault(d.issue_id, {})
            decision = "skip" if d.decision == "permanent_skip" else d.decision
            entry["decision"] = decision
            entry["target"] = d.target
            entry["decision_source"] = "reflect"

    if backlog_decisions:
        reflect_stage["backlog_decisions"] = [d.to_dict() for d in backlog_decisions]

    stages["reflect"] = reflect_stage
    if is_reuse and existing_stage and existing_stage.get("confirmed_at"):
        reflect_stage["confirmed_at"] = existing_stage["confirmed_at"]
        reflect_stage["confirmed_text"] = existing_stage.get("confirmed_text", "")
    cleared = cascade_clear_later_confirmations(stages, "reflect")

    services.save_plan(plan)
    services.append_log_entry(
        plan,
        "triage_reflect",
        actor="user",
        detail={"issue_count": issue_count, "reuse": is_reuse, "recurring_dims": recurring_dims},
    )
    services.save_plan(plan)
    return reflect_stage, cleared


def _cmd_stage_reflect(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Record the REFLECT stage: compare current issues against completed work."""
    report: str | None = getattr(args, "report", None)
    attestation: str | None = getattr(args, "attestation", None)

    resolved_services = services or default_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    plan = resolved_services.load_plan()

    if not has_triage_in_queue(plan):
        print(colorize("  No planning stages in the queue — nothing to reflect on.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    existing_stage = stages.get("reflect")

    report, is_reuse = resolve_reusable_report(report, existing_stage)
    if not report:
        _print_reflect_report_requirement()
        return

    submission = _validate_reflect_submission(
        report=report,
        plan=plan,
        state=state,
        stages=stages,
        attestation=attestation,
        services=resolved_services,
    )
    if submission is None:
        return
    (
        triage_input, issue_count, recurring, recurring_dims,
        cited_ids, missing_ids, duplicate_ids, disposition_ledger,
        backlog_decisions,
    ) = submission
    reflect_stage, cleared = _persist_reflect_stage(
        plan=plan,
        meta=meta,
        stages=stages,
        report=report,
        issue_count=issue_count,
        cited_ids=cited_ids,
        missing_ids=missing_ids,
        duplicate_ids=duplicate_ids,
        recurring_dims=recurring_dims,
        disposition_ledger=disposition_ledger,
        backlog_decisions=backlog_decisions,
        existing_stage=existing_stage,
        is_reuse=is_reuse,
        services=resolved_services,
    )

    print_reflect_result(
        issue_count=issue_count,
        recurring_dims=recurring_dims,
        recurring=recurring,
        report=report,
        is_reuse=is_reuse,
        cleared=cleared,
        stages=stages,
    )


def cmd_stage_reflect(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for reflect stage recording."""
    _cmd_stage_reflect(args, services=services)


__all__ = ["_cmd_stage_reflect", "cmd_stage_reflect"]
