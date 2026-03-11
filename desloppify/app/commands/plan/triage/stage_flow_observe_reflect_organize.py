"""Observe/reflect/organize stage command flow."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.state_io import utc_now

from .lifecycle import TriageLifecycleDeps, TriageStartRequest, ensure_triage_started
from .stages.records import (
    record_observe_stage,
    record_organize_stage,
    resolve_reusable_report,
)
from .stages.rendering import (
    _print_observe_report_requirement,
    _print_reflect_report_requirement,
)
from .validation.core import (
    _auto_confirm_observe_if_attested,
    _auto_confirm_reflect_for_organize,
    _clusters_enriched_or_error,
    _manual_clusters_or_error,
    _organize_report_or_error,
    _require_reflect_stage_for_organize,
    _unclustered_review_issues_or_error,
    _validate_recurring_dimension_mentions,
    _validate_reflect_issue_accounting,
)
from .display.dashboard import print_organize_result, print_reflect_result
from .helpers import (
    cascade_clear_later_confirmations,
    count_log_activity_since,
    has_triage_in_queue,
    inject_triage_stages,
    open_review_ids_from_state,
    print_cascade_clear_feedback,
)
from .services import TriageServices, default_triage_services


# -- Shared helpers (used by multiple stage commands) --


def _validate_stage_report_length(
    *,
    report: str,
    issue_count: int,
    guidance: str,
) -> bool:
    """Return whether the report is long enough for the issue volume."""
    min_chars = 50 if issue_count <= 3 else 100
    if len(report) >= min_chars:
        return True
    print(colorize(f"  Report too short: {len(report)} chars (minimum {min_chars}).", "red"))
    print(colorize(guidance, "dim"))
    return False


def _enforce_cluster_activity_for_organize(
    *,
    plan: dict,
    stages: dict,
    manual_clusters: list[str],
    open_review_ids: set[str],
    is_reuse: bool,
    attestation: str | None,
) -> bool:
    """Require enough cluster operations after reflect unless explicitly attested."""
    if not open_review_ids:
        return True
    reflect_ts = stages.get("reflect", {}).get("timestamp", "")
    if not reflect_ts or is_reuse:
        return True
    activity = count_log_activity_since(plan, reflect_ts)
    cluster_ops = sum(
        activity.get(key, 0)
        for key in ("cluster_create", "cluster_add", "cluster_update", "cluster_remove")
    )
    cluster_count = len(manual_clusters)
    min_ops = max(3, cluster_count)
    if cluster_ops >= min_ops:
        return True
    if attestation and len(attestation.strip()) >= 40:
        print(colorize(
            f"  Note: only {cluster_ops} cluster op(s) logged (expected {min_ops}+). "
            "Proceeding with attestation override.",
            "yellow",
        ))
        return True
    print(colorize(
        f"  Cannot organize: only {cluster_ops} cluster operation(s) logged "
        f"since reflect (need {min_ops}+).",
        "red",
    ))
    print(colorize(
        "  Cluster operations (create/add/update/remove) are logged automatically\n"
        "  when you use the CLI. Did you create clusters, add issues, and enrich them?",
        "dim",
    ))
    print(colorize(
        '  Override: pass --attestation "reason why fewer ops are expected" (40+ chars).',
        "dim",
    ))
    return False


def _validate_reflect_submission(
    *,
    report: str,
    plan: dict,
    state: dict,
    stages: dict,
    attestation: str | None,
    services: TriageServices,
):
    if "observe" not in stages:
        print(colorize("  Cannot reflect: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return None

    si = services.collect_triage_input(plan, state)
    if not _auto_confirm_observe_if_attested(
        plan=plan,
        stages=stages,
        attestation=attestation,
        triage_input=si,
        save_plan_fn=services.save_plan,
    ):
        return None

    issue_count = len(si.open_issues)
    if not _validate_stage_report_length(
        report=report,
        issue_count=issue_count,
        guidance="  Describe how current issues relate to previously completed work.",
    ):
        return None

    recurring = services.detect_recurring_patterns(
        si.open_issues,
        si.resolved_issues,
    )
    recurring_dims = sorted(recurring.keys())
    if not _validate_recurring_dimension_mentions(
        report=report,
        recurring_dims=recurring_dims,
        recurring=recurring,
    ):
        return None

    accounting_ok, cited_ids, missing_ids, duplicate_ids = _validate_reflect_issue_accounting(
        report=report,
        valid_ids=set(si.open_issues.keys()),
    )
    if not accounting_ok:
        return None

    from .stages.evidence_parsing import (
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

    return si, issue_count, recurring, recurring_dims, cited_ids, missing_ids, duplicate_ids


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
    existing_stage: dict | None,
    is_reuse: bool,
    services: TriageServices,
) -> tuple[dict, list[str]]:
    stages = meta.setdefault("triage_stages", {})
    reflect_stage = {
        "stage": "reflect",
        "report": report,
        "cited_ids": sorted(cited_ids),
        "timestamp": utc_now(),
        "issue_count": issue_count,
        "missing_issue_ids": missing_ids,
        "duplicate_issue_ids": duplicate_ids,
        "recurring_dims": recurring_dims,
    }
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


def _validate_organize_submission(
    *,
    args: argparse.Namespace,
    plan: dict,
    state: dict,
    stages: dict,
    report: str | None,
    attestation: str | None,
    is_reuse: bool,
    services: TriageServices,
) -> tuple[list[str], str] | None:
    open_review_ids = open_review_ids_from_state(state)
    triage_input = services.collect_triage_input(plan, state)

    if not _auto_confirm_reflect_for_organize(
        args=args,
        plan=plan,
        stages=stages,
        attestation=attestation,
        triage_input=triage_input,
        detect_recurring_patterns_fn=services.detect_recurring_patterns,
        save_plan_fn=services.save_plan,
    ):
        return None

    manual_clusters = _manual_clusters_or_error(plan, open_review_ids=open_review_ids)
    if manual_clusters is None:
        return None
    if not _clusters_enriched_or_error(plan):
        return None
    if not _unclustered_review_issues_or_error(plan, state):
        return None
    if not _enforce_cluster_activity_for_organize(
        plan=plan,
        stages=stages,
        manual_clusters=manual_clusters,
        open_review_ids=open_review_ids,
        is_reuse=is_reuse,
        attestation=attestation,
    ):
        return None

    normalized_report = _organize_report_or_error(report)
    if normalized_report is None:
        return None

    from .stages.evidence_parsing import (
        format_evidence_failures,
        validate_report_references_clusters,
    )

    cluster_ref_failures = validate_report_references_clusters(
        normalized_report,
        manual_clusters,
    )
    if cluster_ref_failures:
        print(colorize(
            format_evidence_failures(cluster_ref_failures, stage_label="organize"),
            "red",
        ))
        return None
    return manual_clusters, normalized_report


def _persist_organize_stage(
    *,
    plan: dict,
    meta: dict,
    report: str,
    open_review_ids: set[str],
    existing_stage: dict | None,
    is_reuse: bool,
    manual_clusters: list[str],
    services: TriageServices,
) -> tuple[list[str], dict]:
    stages = meta.setdefault("triage_stages", {})
    cleared = record_organize_stage(
        stages,
        report=report,
        issue_count=len(open_review_ids),
        existing_stage=existing_stage,
        is_reuse=is_reuse,
    )
    services.save_plan(plan)
    services.append_log_entry(
        plan,
        "triage_organize",
        actor="user",
        detail={"cluster_count": len(manual_clusters), "reuse": is_reuse},
    )
    services.save_plan(plan)
    return cleared, stages


# -- Stage commands --


def _cmd_stage_observe(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
    has_triage_in_queue_fn=has_triage_in_queue,
    inject_triage_stages_fn=inject_triage_stages,
) -> None:
    """Record the OBSERVE stage: agent analyses themes and root causes."""
    report: str | None = getattr(args, "report", None)
    attestation: str | None = getattr(args, "attestation", None)

    resolved_services = services or default_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    plan = resolved_services.load_plan()

    # Auto-start triage if needed
    if not has_triage_in_queue_fn(plan):
        start_outcome = ensure_triage_started(
            plan,
            services=resolved_services,
            request=TriageStartRequest(
                state=state,
                attestation=attestation,
                start_message="  Planning mode auto-started (6 stages queued).",
            ),
            deps=TriageLifecycleDeps(
                has_triage_in_queue=has_triage_in_queue_fn,
                inject_triage_stages=inject_triage_stages_fn,
            ),
        )
        if start_outcome.status == "blocked":
            return

    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    existing_stage = stages.get("observe")

    report, is_reuse = resolve_reusable_report(report, existing_stage)
    if not report:
        _print_observe_report_requirement()
        return

    si = resolved_services.collect_triage_input(plan, state)
    issue_count = len(si.open_issues)

    # Zero-issue fast path
    if issue_count == 0:
        cleared = record_observe_stage(
            stages,
            report=report,
            issue_count=0,
            cited_ids=[],
            existing_stage=existing_stage,
            is_reuse=is_reuse,
        )
        resolved_services.save_plan(plan)
        print(colorize("  Observe stage recorded (no issues to analyse).", "green"))
        if is_reuse:
            print(colorize("  Observe data preserved (no changes).", "dim"))
            if cleared:
                print_cascade_clear_feedback(cleared, stages)
        return

    if not _validate_stage_report_length(
        report=report,
        issue_count=issue_count,
        guidance="  Describe themes, root causes, contradictions, and how issues relate.",
    ):
        return

    # Validate structured evidence
    from .stages.evidence_parsing import (
        format_evidence_failures,
        parse_observe_evidence,
        validate_observe_evidence,
    )

    valid_ids = set(si.open_issues.keys())
    cited = resolved_services.extract_issue_citations(report, valid_ids)

    evidence = parse_observe_evidence(report, valid_ids)
    evidence_failures = validate_observe_evidence(evidence, issue_count)
    blocking = [f for f in evidence_failures if f.blocking]
    advisory = [f for f in evidence_failures if not f.blocking]
    if blocking:
        print(colorize(format_evidence_failures(blocking, stage_label="observe"), "red"))
        return
    if advisory:
        print(colorize(format_evidence_failures(advisory, stage_label="observe"), "yellow"))

    assessments = [
        {
            "hash": entry.issue_hash,
            "verdict": entry.verdict,
            "verdict_reasoning": entry.verdict_reasoning,
            "files_read": entry.files_read,
            "recommendation": entry.recommendation,
        }
        for entry in evidence.entries
    ]

    # Persist
    cleared = record_observe_stage(
        stages,
        report=report,
        issue_count=issue_count,
        cited_ids=sorted(cited),
        existing_stage=existing_stage,
        is_reuse=is_reuse,
        assessments=assessments,
    )
    resolved_services.save_plan(plan)
    resolved_services.append_log_entry(
        plan,
        "triage_observe",
        actor="user",
        detail={"issue_count": issue_count, "cited_ids": sorted(cited), "reuse": is_reuse},
    )
    resolved_services.save_plan(plan)

    print(colorize(f"  Observe stage recorded: {issue_count} issues analysed.", "green"))
    if is_reuse:
        print(colorize("  Observe data preserved (no changes).", "dim"))
        if cleared:
            print_cascade_clear_feedback(cleared, stages)
        return

    print(colorize("  Now confirm your analysis.", "yellow"))
    print(colorize("    desloppify plan triage --confirm observe", "dim"))
    print_user_message(
        "Observe recorded. Before confirming — did the subagent"
        " verify every issue with code reads? Check: are there"
        " specific file/line citations in the report, or just"
        " restated issue titles? Each issue needs a verdict:"
        " genuine / false positive / exaggerated. Don't confirm"
        " until the analysis is backed by actual code evidence."
    )


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
    si, issue_count, recurring, recurring_dims, cited_ids, missing_ids, duplicate_ids = submission
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


def _cmd_stage_organize(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Record the ORGANIZE stage: validates cluster enrichment."""
    report: str | None = getattr(args, "report", None)
    attestation: str | None = getattr(args, "attestation", None)

    resolved_services = services or default_triage_services()
    plan = resolved_services.load_plan()

    if not has_triage_in_queue(plan):
        print(colorize("  No planning stages in the queue — nothing to organize.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})

    existing_stage = stages.get("organize")
    is_reuse = False
    if not report and existing_stage and existing_stage.get("report"):
        report = existing_stage["report"]
        is_reuse = True

    if not _require_reflect_stage_for_organize(stages):
        return

    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    open_review_ids = open_review_ids_from_state(state)

    validated = _validate_organize_submission(
        args=args,
        plan=plan,
        state=state,
        stages=stages,
        report=report,
        attestation=attestation,
        is_reuse=is_reuse,
        services=resolved_services,
    )
    if validated is None:
        return
    manual_clusters, report = validated
    cleared, stages = _persist_organize_stage(
        plan=plan,
        meta=meta,
        report=report,
        open_review_ids=open_review_ids,
        existing_stage=existing_stage,
        is_reuse=is_reuse,
        manual_clusters=manual_clusters,
        services=resolved_services,
    )

    print_organize_result(
        manual_clusters=manual_clusters,
        plan=plan,
        report=report,
        is_reuse=is_reuse,
        cleared=cleared,
        stages=stages,
    )


def cmd_stage_observe(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for observe stage recording."""
    _cmd_stage_observe(args, services=services)


def cmd_stage_reflect(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for reflect stage recording."""
    _cmd_stage_reflect(args, services=services)


def cmd_stage_organize(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for organize stage recording."""
    _cmd_stage_organize(args, services=services)


__all__ = [
    "cmd_stage_observe",
    "cmd_stage_organize",
    "cmd_stage_reflect",
    "_cmd_stage_observe",
    "_cmd_stage_organize",
    "_cmd_stage_reflect",
]
