"""Completion helpers for finishing triage planning."""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from typing import Any

from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.constants import (
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    is_synthetic_id,
)
from desloppify.engine._plan.policy.stale import review_issue_snapshot_hash
from desloppify.engine._plan.refresh_lifecycle import (
    _set_lifecycle_phase,
    current_lifecycle_phase,
    mark_postflight_scan_completed,
)
from desloppify.engine._state.progression import (
    append_progression_event,
    build_triage_complete_event,
)
from desloppify.engine.plan_ops import purge_ids, remove_queue_entries
from desloppify.engine.plan_state import Cluster, PlanModel
from desloppify.engine.plan_triage import TRIAGE_IDS
from desloppify.state_io import StateModel, utc_now

from .plan_state_access import ensure_execution_log, ensure_triage_meta
from .review_coverage import (
    clear_active_triage_issue_tracking,
    cluster_issue_ids,
    coverage_open_ids,
    triage_coverage,
)
from .services import TriageServices, default_triage_services

_logger = logging.getLogger(__name__)


def _normalize_summary_text(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip()


def _truncate_summary_text(text: str, limit: int = 360) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _effective_completion_strategy_summary(
    *,
    completion_mode: str,
    strategy: str,
    existing_strategy: str,
    completion_note: str,
) -> str:
    if strategy.lower() != "same":
        return strategy
    if completion_mode == "confirm_existing":
        summary = (
            "Reused the existing enriched cluster plan after re-review instead "
            "of materializing a new reflect blueprint."
        )
        if completion_note:
            summary += f" Reason: {completion_note}"
        elif existing_strategy:
            summary += " Prior execution sequencing remains in force."
        return _truncate_summary_text(summary)
    return existing_strategy


def _sync_completion_meta(
    *,
    plan: PlanModel,
    state: StateModel,
    strategy: str,
    completion_mode: str,
    completion_note: str,
    coverage_ids: set[str],
) -> tuple[dict[str, Any], str]:
    meta = ensure_triage_meta(plan)
    if state.get("last_scan"):
        meta["issue_snapshot_hash"] = review_issue_snapshot_hash(state)
    elif not meta.get("issue_snapshot_hash"):
        meta.pop("issue_snapshot_hash", None)

    normalized_strategy = _normalize_summary_text(strategy)
    existing_strategy = _normalize_summary_text(meta.get("strategy_summary", ""))
    normalized_note = _normalize_summary_text(completion_note)
    effective_strategy_summary = _effective_completion_strategy_summary(
        completion_mode=completion_mode,
        strategy=normalized_strategy,
        existing_strategy=existing_strategy,
        completion_note=normalized_note,
    )
    meta["triaged_ids"] = sorted(coverage_ids)
    if effective_strategy_summary:
        meta["strategy_summary"] = effective_strategy_summary
    meta["trigger"] = (
        "confirm_existing" if completion_mode == "confirm_existing" else "manual_triage"
    )
    meta["last_completion_mode"] = completion_mode
    if normalized_note:
        meta["last_completion_note"] = normalized_note
    else:
        meta.pop("last_completion_note", None)
    meta["last_completed_at"] = utc_now()
    return meta, effective_strategy_summary


def _archive_and_clear_triage_stages(
    meta: dict[str, Any],
    *,
    effective_strategy_summary: str,
    existing_strategy: str,
    completion_mode: str,
    completion_note: str,
) -> None:
    stages = meta.get("triage_stages", {})
    normalized_note = _normalize_summary_text(completion_note)
    if stages:
        last_triage = {
            "completed_at": utc_now(),
            "stages": {key: dict(value) for key, value in stages.items()},
            "strategy": effective_strategy_summary,
            "completion_mode": completion_mode,
        }
        if completion_mode == "confirm_existing":
            last_triage["reused_existing_plan"] = True
            if normalized_note:
                last_triage["completion_note"] = normalized_note
            if existing_strategy and existing_strategy != effective_strategy_summary:
                last_triage["previous_strategy_summary"] = existing_strategy
        meta["last_triage"] = last_triage
    meta["triage_stages"] = {}
    meta.pop("triage_recommended", None)
    meta.pop("stage_refresh_required", None)
    meta.pop("stage_snapshot_hash", None)
    clear_active_triage_issue_tracking(meta)


def _print_completion_summary(
    *,
    clusters: dict[str, Cluster],
    organized: int,
    total: int,
    completion_mode: str,
    effective_strategy_summary: str,
) -> None:
    cluster_count = len([cluster for cluster in clusters.values() if cluster_issue_ids(cluster)])
    print(colorize(f"  Triage complete: {organized}/{total} issues in {cluster_count} cluster(s).", "green"))
    if completion_mode == "confirm_existing":
        print(
            colorize(
                "  Completion mode: reused the current enriched cluster plan; "
                "did not materialize a new reflect blueprint.",
                "cyan",
            )
        )
    if effective_strategy_summary:
        print(colorize(f"  Strategy: {effective_strategy_summary}", "cyan"))
    print(colorize("  Run `desloppify next` to start implementation.", "green"))


def _restore_postflight_scan_completion_for_current_scan(
    *,
    plan: PlanModel,
    state: StateModel,
) -> None:
    """Keep triage completion on the current scan boundary.

    Organize/enrich can legitimately use plan skip commands on live review IDs.
    Those commands clear the postflight-scan marker because they mutate queue
    coverage for real issues. Triage completion is still operating on the same
    scan snapshot, so leaving the marker cleared incorrectly bounces `next`
    back to `workflow::run-scan` instead of the freshly triaged review work.
    """
    if not state.get("last_scan"):
        return
    mark_postflight_scan_completed(
        plan,
        scan_count=int(state.get("scan_count", 0) or 0),
    )


def apply_completion(
    args: argparse.Namespace,
    plan: PlanModel,
    strategy: str,
    *,
    services: TriageServices | None = None,
    completion_mode: str = "manual_triage",
    completion_note: str = "",
) -> None:
    """Shared completion logic: update meta, remove triage stage IDs, save."""
    resolved_services = services or default_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    phase_before = current_lifecycle_phase(plan)

    coverage_ids = coverage_open_ids(plan, state)
    organized, total, clusters = triage_coverage(plan, open_review_ids=coverage_ids)

    purge_ids(
        plan,
        [*TRIAGE_IDS, WORKFLOW_SCORE_CHECKPOINT_ID, WORKFLOW_CREATE_PLAN_ID],
    )
    existing_strategy = _normalize_summary_text(
        ensure_triage_meta(plan).get("strategy_summary", "")
    )
    meta, effective_strategy_summary = _sync_completion_meta(
        plan=plan,
        state=state,
        strategy=strategy,
        completion_mode=completion_mode,
        completion_note=completion_note,
        coverage_ids=coverage_ids,
    )
    _archive_and_clear_triage_stages(
        meta,
        effective_strategy_summary=effective_strategy_summary,
        existing_strategy=existing_strategy,
        completion_mode=completion_mode,
        completion_note=completion_note,
    )
    _restore_postflight_scan_completion_for_current_scan(
        plan=plan,
        state=state,
    )
    # Completing a valid triage board is the handoff from planning to
    # implementation. Without this persisted transition, queue snapshots
    # continue exposing postflight/objective backlog instead of the newly
    # triaged execution work.
    _set_lifecycle_phase(plan, "execute")
    remove_queue_entries(
        plan,
        [
            issue_id
            for issue_id in plan["queue_order"]
            if isinstance(issue_id, str) and is_synthetic_id(issue_id)
        ],
    )
    resolved_services.save_plan(plan)

    # --- Progression: triage_complete ---
    try:
        append_progression_event(
            build_triage_complete_event(
                plan,
                state,
                completion_mode=completion_mode,
                strategy_summary=effective_strategy_summary,
                organized=organized,
                total=total,
                clusters=clusters,
                phase_before=phase_before,
            )
        )
    except Exception:
        _logger.warning("Failed to append triage_complete progression event", exc_info=True)

    _print_completion_summary(
        clusters=clusters,
        organized=organized,
        total=total,
        completion_mode=completion_mode,
        effective_strategy_summary=effective_strategy_summary,
    )


def count_log_activity_since(plan: PlanModel, since: str | None) -> dict[str, int]:
    """Count execution-log activity by action since a timestamp, or across all history."""
    counts: dict[str, int] = defaultdict(int)
    for raw_entry in ensure_execution_log(plan):
        if "timestamp" not in raw_entry or "action" not in raw_entry:
            continue
        timestamp = raw_entry["timestamp"]
        action = raw_entry["action"]
        if not isinstance(timestamp, str) or not isinstance(action, str):
            continue
        if since is not None and timestamp < since:
            continue
        counts[action] += 1
    return dict(counts)


__all__ = [
    "apply_completion",
    "count_log_activity_since",
]
