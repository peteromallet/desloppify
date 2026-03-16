"""Post-import plan sync for review importing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desloppify.app.commands.helpers.issue_id_display import short_issue_id
from desloppify.app.commands.helpers.transition_messages import emit_transition_message
from desloppify.app.commands.review.importing.flags import imported_assessment_keys
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.operations.meta import append_log_entry
from desloppify.engine._plan.persistence import (
    has_living_plan,
    load_plan,
    plan_path_for_state,
    save_plan,
)
from desloppify.engine._plan.sync.review_import import (
    ReviewImportSyncResult,
    sync_plan_after_review_import,
)
from desloppify.engine._plan.sync import (
    ReconcileResult,
    live_planned_queue_empty,
    reconcile_plan,
)
from desloppify.engine._plan.sync.workflow_gates import sync_import_scores_needed
from desloppify.engine._plan.sync.workflow import clear_score_communicated_sentinel
from desloppify.engine._plan.refresh_lifecycle import mark_subjective_review_completed
from desloppify.engine.plan_triage import (
    TRIAGE_CMD_RUN_STAGES_CLAUDE,
    TRIAGE_CMD_RUN_STAGES_CODEX,
)
from desloppify.intelligence.review.importing.contracts_types import (
    NormalizedReviewImportPayload,
)


@dataclass(frozen=True)
class PlanImportSyncRequest:
    """Bundle optional inputs for post-import plan synchronization."""

    state_file: str | Path | None = None
    config: dict | None = None
    import_file: str | None = None
    import_payload: NormalizedReviewImportPayload | None = None


@dataclass(frozen=True)
class _ImportSyncInputs:
    has_review_issue_delta: bool
    assessment_keys: frozenset[str]
    covered_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlanImportSyncOutcome:
    """Visible result of post-import plan synchronization."""

    status: str
    message: str | None = None


@dataclass(frozen=True)
class _ImportPlanTransition:
    import_result: ReviewImportSyncResult | None
    covered_pruned: list[str]
    import_scores_result: object
    reconcile_result: ReconcileResult
    transition_phase: str | None = None


def _print_review_import_sync(
    state: dict,
    result: ReviewImportSyncResult,
    *,
    workflow_injected: bool,
    triage_injected: bool,
    outcome: PlanImportSyncOutcome,
) -> None:
    """Print summary of plan changes after review import sync."""
    new_ids = result.new_ids
    stale_pruned = result.stale_pruned_from_queue
    covered_pruned = getattr(result, "covered_subjective_pruned_from_queue", [])
    print()
    _print_new_review_items(state, new_ids)
    _print_stale_review_prunes(stale_pruned)
    _print_covered_subjective_prunes(covered_pruned)
    _print_review_import_footer(
        workflow_injected=workflow_injected,
        triage_injected=triage_injected,
        outcome=outcome,
    )


def _print_new_review_items(state: dict, new_ids: list[str]) -> None:
    if not new_ids:
        return
    print(
        colorize(
            f"  Plan updated: {len(new_ids)} new review work item(s) added to queue.",
            "bold",
        )
    )
    issues = (state.get("work_items") or state.get("issues", {}))
    for finding_id in sorted(new_ids)[:10]:
        finding = issues.get(finding_id, {})
        print(f"    * [{short_issue_id(finding_id)}] {finding.get('summary', '')}")
    if len(new_ids) > 10:
        print(colorize(f"    ... and {len(new_ids) - 10} more", "dim"))


def _print_stale_review_prunes(stale_pruned: list[str]) -> None:
    if not stale_pruned:
        return
    print(
        colorize(
            f"  Plan updated: {len(stale_pruned)} stale review work item(s) removed from queue.",
            "bold",
        )
    )


def _print_covered_subjective_prunes(covered_pruned: list[str]) -> None:
    if not covered_pruned:
        return
    print(
        colorize(
            f"  Plan updated: {len(covered_pruned)} covered subjective queue item(s) removed.",
            "bold",
        )
    )


def _print_review_import_footer(
    *,
    workflow_injected: bool,
    triage_injected: bool,
    outcome: PlanImportSyncOutcome,
) -> None:
    print()
    status_line = "  Review queue sync completed. Workflow follow-up may be front-loaded."
    status_tone = "dim"
    if outcome.status == "degraded" and outcome.message:
        status_line = f"  Review queue sync degraded: {outcome.message}"
        status_tone = "yellow"
    print(colorize(status_line, status_tone))
    print()
    print(colorize("  View execution queue:  desloppify plan queue", "dim"))
    print(colorize("  View newest first:     desloppify plan queue --sort recent", "dim"))
    print(colorize("  View broader backlog:  desloppify backlog", "dim"))
    print()
    print(colorize("  NEXT STEP:", "yellow"))
    print(colorize("    Run:    desloppify next", "yellow"))
    if triage_injected and not workflow_injected:
        print(colorize(f"    Codex:  {TRIAGE_CMD_RUN_STAGES_CODEX}", "dim"))
        print(colorize(f"    Claude: {TRIAGE_CMD_RUN_STAGES_CLAUDE}", "dim"))
        print(colorize("    Manual dashboard: desloppify plan triage", "dim"))
    print(
        colorize(
            "  (Follow the queue in order; score communication and planning come before triage.)",
            "dim",
        )
    )


def _review_delta_present(diff: dict) -> bool:
    return any(
        int(diff.get(key, 0) or 0) > 0
        for key in ("new", "reopened", "auto_resolved")
    )


def _print_workflow_injected_message(workflow_injected_ids: list[str]) -> None:
    if not workflow_injected_ids:
        return
    injected_parts = [f"`{workflow_id}`" for workflow_id in workflow_injected_ids]
    print(
        colorize(
            f"  Plan: {' and '.join(injected_parts)} queued. Run `desloppify next`.",
            "cyan",
        )
    )


def _build_import_sync_inputs(
    diff: dict,
    import_payload: NormalizedReviewImportPayload | None,
) -> _ImportSyncInputs:
    assessment_keys = (
        imported_assessment_keys(import_payload)
        if isinstance(import_payload, dict)
        else set()
    )
    return _ImportSyncInputs(
        has_review_issue_delta=_review_delta_present(diff),
        assessment_keys=frozenset(assessment_keys),
        covered_ids=tuple(
            f"subjective::{dim_key}"
            for dim_key in sorted(assessment_keys)
        ),
    )


def _sync_review_delta(
    plan: dict,
    state: dict,
    sync_inputs: _ImportSyncInputs,
) -> ReviewImportSyncResult | None:
    if not sync_inputs.has_review_issue_delta:
        return None
    return sync_plan_after_review_import(
        plan,
        state,
        inject_triage=False,
    )


def _apply_import_plan_transitions(
    plan: dict,
    state: dict,
    *,
    sync_inputs: _ImportSyncInputs,
    assessment_mode: str,
    trusted: bool,
    import_file: str | None,
    import_payload: NormalizedReviewImportPayload | None,
    target_strict: float,
    was_boundary_ready: bool,
) -> _ImportPlanTransition:
    """Apply plan mutations driven by a review import before persistence/output."""
    import_result = _sync_review_delta(plan, state, sync_inputs)
    covered_pruned = (
        _prune_covered_subjective_ids_from_plan(plan, covered_ids=sync_inputs.covered_ids)
        if trusted
        else []
    )
    import_scores_result = sync_import_scores_needed(
        plan,
        state,
        assessment_mode=assessment_mode,
        import_file=import_file,
        import_payload=import_payload,
    )
    if trusted:
        clear_score_communicated_sentinel(plan)
        if sync_inputs.covered_ids:
            mark_subjective_review_completed(
                plan,
                scan_count=int(state.get("scan_count", 0) or 0),
            )

    reconcile_result = ReconcileResult()
    if was_boundary_ready and (
        sync_inputs.has_review_issue_delta
        or import_scores_result.changes
        or (trusted and bool(sync_inputs.covered_ids))
    ):
        reconcile_result = reconcile_plan(plan, state, target_strict=target_strict)

    if import_result is not None and covered_pruned:
        import_result = ReviewImportSyncResult(
            new_ids=import_result.new_ids,
            added_to_queue=import_result.added_to_queue,
            triage_injected=import_result.triage_injected,
            stale_pruned_from_queue=import_result.stale_pruned_from_queue,
            covered_subjective_pruned_from_queue=covered_pruned,
            triage_injected_ids=import_result.triage_injected_ids,
            triage_deferred=import_result.triage_deferred,
        )

    transition_phase = (
        reconcile_result.lifecycle_phase
        if reconcile_result.lifecycle_phase_changed
        else None
    )
    return _ImportPlanTransition(
        import_result=import_result,
        covered_pruned=covered_pruned,
        import_scores_result=import_scores_result,
        reconcile_result=reconcile_result,
        transition_phase=transition_phase,
    )


def _prune_covered_subjective_ids_from_plan(
    plan: dict,
    *,
    covered_ids: tuple[str, ...],
) -> list[str]:
    """Prune subjective queue placeholders that were just covered by review import."""
    covered = {
        issue_id
        for issue_id in covered_ids
        if isinstance(issue_id, str) and issue_id.startswith("subjective::")
    }
    if not covered:
        return []

    order = plan.get("queue_order")
    if not isinstance(order, list):
        return []

    pruned = [issue_id for issue_id in order if issue_id in covered]
    if not pruned:
        return []

    pruned_set = set(pruned)
    order[:] = [issue_id for issue_id in order if issue_id not in pruned_set]

    overrides = plan.get("overrides")
    if isinstance(overrides, dict):
        for issue_id in pruned_set:
            overrides.pop(issue_id, None)

    for cluster in plan.get("clusters", {}).values():
        if not isinstance(cluster, dict):
            continue
        issue_ids = cluster.get("issue_ids")
        if not isinstance(issue_ids, list):
            continue
        cluster["issue_ids"] = [
            issue_id for issue_id in issue_ids if issue_id not in pruned_set
        ]

    return pruned


def _append_review_import_sync_log(
    plan: dict,
    diff: dict,
    import_result: ReviewImportSyncResult | None,
    import_scores_result,
    pipeline_result: ReconcileResult,
    *,
    covered_ids: tuple[str, ...],
    outcome: PlanImportSyncOutcome,
) -> None:
    if not (
        import_result is not None
        or import_scores_result.changes
        or pipeline_result.dirty
        or covered_ids
    ):
        return
    subjective = pipeline_result.subjective
    triage = pipeline_result.triage
    append_log_entry(
        plan,
        "review_import_sync",
        actor="system",
        detail={
            "trigger": "review_import",
            "new_ids": sorted(import_result.new_ids) if import_result is not None else [],
            "added_to_queue": import_result.added_to_queue if import_result is not None else [],
            "workflow_injected_ids": pipeline_result.workflow_injected_ids,
            "triage_injected": bool(triage and triage.injected),
            "triage_injected_ids": list(triage.injected) if triage is not None else [],
            "triage_deferred": bool(triage and triage.deferred),
            "diff_new": diff.get("new", 0),
            "diff_reopened": diff.get("reopened", 0),
            "diff_auto_resolved": diff.get("auto_resolved", 0),
            "stale_pruned_from_queue": (
                import_result.stale_pruned_from_queue if import_result is not None else []
            ),
            "covered_subjective_pruned_from_queue": (
                getattr(import_result, "covered_subjective_pruned_from_queue", [])
                if import_result is not None
                else []
            ),
            "covered_subjective": list(covered_ids),
            "stale_sync_injected": sorted(subjective.injected) if subjective is not None else [],
            "stale_sync_pruned": sorted(subjective.pruned) if subjective is not None else [],
            "auto_cluster_changes": pipeline_result.auto_cluster_changes,
            "import_scores_injected": list(getattr(import_scores_result, "injected", []) or []),
            "import_scores_pruned": list(getattr(import_scores_result, "pruned", []) or []),
            "sync_status": outcome.status,
            "sync_message": outcome.message,
        },
    )


def sync_plan_after_import(
    state: dict,
    diff: dict,
    assessment_mode: str,
    *,
    request: PlanImportSyncRequest | None = None,
) -> PlanImportSyncOutcome:
    """Apply issue/workflow syncs after import in one load/save cycle."""
    try:
        state_file = request.state_file if request is not None else None
        config = request.config if request is not None else None
        import_file = request.import_file if request is not None else None
        import_payload = request.import_payload if request is not None else None

        plan_path = None
        target_strict = target_strict_score_from_config(config)
        if state_file is not None:
            plan_path = plan_path_for_state(Path(state_file))
        if not has_living_plan(plan_path):
            return PlanImportSyncOutcome(status="skipped")

        plan = load_plan(plan_path)
        sync_inputs = _build_import_sync_inputs(diff, import_payload)
        trusted = assessment_mode in {"trusted_internal", "attested_external"}
        was_boundary_ready = live_planned_queue_empty(plan)

        transition = _apply_import_plan_transitions(
            plan,
            state,
            sync_inputs=sync_inputs,
            assessment_mode=assessment_mode,
            trusted=trusted,
            import_file=import_file,
            import_payload=import_payload,
            target_strict=target_strict,
            was_boundary_ready=was_boundary_ready,
        )
        import_result = transition.import_result
        covered_pruned = transition.covered_pruned
        import_scores_result = transition.import_scores_result
        result = transition.reconcile_result

        dirty = bool(
            import_result is not None
            or covered_pruned
            or import_scores_result.changes
            or result.dirty
        )
        outcome = PlanImportSyncOutcome(status="synced")
        if dirty:
            _append_review_import_sync_log(
                plan,
                diff,
                import_result,
                import_scores_result,
                result,
                covered_ids=sync_inputs.covered_ids,
                outcome=outcome,
            )
            save_plan(plan, plan_path)

        if import_result is not None:
            _print_review_import_sync(
                state,
                import_result,
                workflow_injected=bool(result.workflow_injected_ids),
                triage_injected=bool(result.triage and result.triage.injected),
                outcome=outcome,
            )
        _print_workflow_injected_message(result.workflow_injected_ids)
        if transition.transition_phase:
            emit_transition_message(transition.transition_phase)
        return outcome
    except PLAN_LOAD_EXCEPTIONS as exc:
        message = f"skipped plan sync after review import ({exc})"
        print(colorize(f"  Plan sync degraded: {message}.", "yellow"))
        return PlanImportSyncOutcome(status="degraded", message=message)


__all__ = [
    "PlanImportSyncOutcome",
    "PlanImportSyncRequest",
    "sync_plan_after_import",
]
