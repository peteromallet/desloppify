"""Organize stage command flow."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize

from ..display.dashboard import print_organize_result
from ..completion_flow import count_log_activity_since
from ..review_coverage import open_review_ids_from_state
from ..stage_queue import has_triage_in_queue
from ..services import TriageServices, default_triage_services
from ..validation.stage_policy import (
    ReflectAutoConfirmDeps,
    auto_confirm_reflect_for_organize,
)
from ..validation.organize_policy import (
    _clusters_enriched_or_error,
    _manual_clusters_or_error,
    _organize_report_or_error,
    _unclustered_review_issues_or_error,
    _validate_organize_against_ledger_or_error,
    validate_backlog_promotions_executed,
)
from ..validation.stage_policy import require_prerequisite
from .records import record_organize_stage


def _require_reflect_stage_for_organize(stages: dict) -> bool:
    return require_prerequisite(
        stages,
        flow="organize",
        messages={
            "observe": (
                "  Cannot organize: observe stage not complete.",
                '  Run: desloppify plan triage --stage observe --report "..."',
            ),
            "reflect": (
                "  Cannot organize: reflect stage not complete.",
                '  Run: desloppify plan triage --stage reflect --report "..."',
            ),
        },
    )


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
    min_ops = max(3, len(manual_clusters))
    if cluster_ops >= min_ops:
        return True
    if attestation and len(attestation.strip()) >= 40:
        print(
            colorize(
                f"  Note: only {cluster_ops} cluster op(s) logged (expected {min_ops}+). "
                "Proceeding with attestation override.",
                "yellow",
            )
        )
        return True
    print(
        colorize(
            f"  Cannot organize: only {cluster_ops} cluster operation(s) logged "
            f"since reflect (need {min_ops}+).",
            "red",
        )
    )
    print(
        colorize(
            "  Cluster operations (create/add/update/remove) are logged automatically\n"
            "  when you use the CLI. Did you create clusters, add issues, and enrich them?",
            "dim",
        )
    )
    print(
        colorize(
            '  Override: pass --attestation "reason why fewer ops are expected" (40+ chars).',
            "dim",
        )
    )
    return False


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
    if not auto_confirm_reflect_for_organize(
        args=args,
        plan=plan,
        stages=stages,
        attestation=attestation,
        deps=ReflectAutoConfirmDeps(
            triage_input=triage_input,
            detect_recurring_patterns_fn=services.detect_recurring_patterns,
            save_plan_fn=services.save_plan,
        ),
    ):
        return None

    manual_clusters = _manual_clusters_or_error(plan, open_review_ids=open_review_ids)
    if manual_clusters is None:
        return None
    if not _clusters_enriched_or_error(plan):
        return None
    if not _unclustered_review_issues_or_error(plan, state):
        return None
    if not _validate_organize_against_ledger_or_error(
        plan=plan, stages=stages,
    ):
        return None

    # Warn (non-blocking) when reflect requested backlog promotions that weren't executed
    backlog_warnings = validate_backlog_promotions_executed(plan=plan, stages=stages)
    for warning in backlog_warnings:
        print(colorize(f"  Warning: {warning}", "yellow"))

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

    from .evidence_parsing import (
        format_evidence_failures,
        validate_report_references_clusters,
    )

    cluster_ref_failures = validate_report_references_clusters(normalized_report, manual_clusters)
    if cluster_ref_failures:
        print(
            colorize(
                format_evidence_failures(cluster_ref_failures, stage_label="organize"),
                "red",
            )
        )
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
    manual_clusters, normalized_report = validated
    cleared, stages = _persist_organize_stage(
        plan=plan,
        meta=meta,
        report=normalized_report,
        open_review_ids=open_review_ids,
        existing_stage=existing_stage,
        is_reuse=is_reuse,
        manual_clusters=manual_clusters,
        services=resolved_services,
    )

    print_organize_result(
        manual_clusters=manual_clusters,
        plan=plan,
        report=normalized_report,
        is_reuse=is_reuse,
        cleared=cleared,
        stages=stages,
    )


def cmd_stage_organize(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for organize stage recording."""
    _cmd_stage_organize(args, services=services)


__all__ = [
    "_cmd_stage_organize",
    "cmd_stage_organize",
]
