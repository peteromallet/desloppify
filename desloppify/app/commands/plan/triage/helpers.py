"""Helper utilities for plan triage workflow."""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any, cast

from desloppify.base.output.terminal import colorize
from desloppify.engine._state.schema import Issue, StateModel
from desloppify.engine.plan_state import (
    Cluster,
    PlanModel,
)
from desloppify.engine.plan_ops import purge_ids
from desloppify.engine.plan_queue import (
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    normalize_queue_workflow_and_triage_prefix,
    open_review_ids,
    review_issue_snapshot_hash,
)
from desloppify.engine.plan_triage import (
    TRIAGE_IDS,
    TRIAGE_STAGE_IDS,
    TriageInput,
)
from desloppify.state_io import utc_now

from .services import TriageServices, default_triage_services

_STAGE_ORDER = ["observe", "reflect", "organize", "enrich", "sense-check"]


def _queue_order(plan: PlanModel) -> list[str]:
    """Return normalized queue order list, seeding default if missing."""
    order = plan.get("queue_order")
    if isinstance(order, list):
        return order
    normalized: list[str] = []
    plan["queue_order"] = normalized
    return normalized


def _skipped_map(plan: PlanModel) -> dict[str, Any]:
    """Return normalized skipped map, seeding default if missing."""
    skipped = plan.get("skipped")
    if isinstance(skipped, dict):
        return cast(dict[str, Any], skipped)
    normalized: dict[str, Any] = {}
    plan["skipped"] = normalized
    return normalized


def _cluster_map(plan: PlanModel) -> dict[str, Cluster]:
    """Return normalized cluster map, seeding default if missing."""
    clusters = plan.get("clusters")
    if isinstance(clusters, dict):
        return cast(dict[str, Cluster], clusters)
    normalized: dict[str, Cluster] = {}
    plan["clusters"] = normalized
    return normalized


def _triage_meta(plan: PlanModel) -> dict[str, Any]:
    """Return normalized triage metadata map, seeding default if missing."""
    meta = plan.get("epic_triage_meta")
    if isinstance(meta, dict):
        return cast(dict[str, Any], meta)
    normalized: dict[str, Any] = {}
    plan["epic_triage_meta"] = normalized
    return normalized


def _execution_log(plan: PlanModel) -> list[dict[str, Any]]:
    """Return normalized execution log list, seeding default if missing."""
    log = plan.get("execution_log")
    if isinstance(log, list):
        return [entry for entry in log if isinstance(entry, dict)]
    normalized: list[dict[str, Any]] = []
    plan["execution_log"] = normalized
    return normalized


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
    """Return the strategy summary that should be stored after completion.

    All text arguments should already be normalised via ``_normalize_summary_text``.
    """
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


def has_triage_in_queue(plan: PlanModel) -> bool:
    order = set(_queue_order(plan))
    return bool(order & TRIAGE_IDS)


def _clear_triage_stage_skips(plan: PlanModel) -> None:
    skipped = _skipped_map(plan)
    for sid in TRIAGE_STAGE_IDS:
        skipped.pop(sid, None)


def inject_triage_stages(plan: PlanModel) -> None:
    order = _queue_order(plan)
    _clear_triage_stage_skips(plan)
    remaining = [issue_id for issue_id in order if issue_id not in TRIAGE_IDS]
    order[:] = [*remaining, *TRIAGE_STAGE_IDS]
    normalize_queue_workflow_and_triage_prefix(order)


def purge_triage_stage(plan: PlanModel, stage_name: str) -> None:
    sid = f"triage::{stage_name}"
    purge_ids(plan, [sid])


def cascade_clear_later_confirmations(
    stages: dict[str, dict[str, Any]],
    from_stage: str,
) -> list[str]:
    try:
        idx = _STAGE_ORDER.index(from_stage)
    except ValueError:
        return []
    cleared: list[str] = []
    for later in _STAGE_ORDER[idx + 1:]:
        if later in stages and stages[later].get("confirmed_at"):
            stages[later].pop("confirmed_at", None)
            stages[later].pop("confirmed_text", None)
            cleared.append(later)
    return cleared


def print_cascade_clear_feedback(
    cleared: list[str],
    stages: dict[str, dict[str, Any]],
) -> None:
    if not cleared:
        return
    print(colorize(f"  Cleared confirmations on: {', '.join(cleared)}", "yellow"))
    next_unconfirmed = next(
        (s for s in _STAGE_ORDER if s in stages and not stages[s].get("confirmed_at")),
        None,
    )
    if next_unconfirmed:
        print(colorize(
            f"  Re-confirm with: desloppify plan triage --confirm {next_unconfirmed}",
            "dim",
        ))


def observe_dimension_breakdown(si: TriageInput) -> tuple[dict[str, int], list[str]]:
    by_dim: dict[str, int] = defaultdict(int)
    for _fid, issue in si.open_issues.items():
        detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        by_dim[dim] += 1
    dim_names = sorted(by_dim, key=lambda d: (-by_dim[d], d))
    return dict(by_dim), dim_names


def group_issues_into_observe_batches(
    si: TriageInput,
    max_batches: int = 5,
) -> list[tuple[list[str], dict[str, Issue]]]:
    """Group observe issues into dimension-balanced batches."""
    by_dim, dim_names = observe_dimension_breakdown(si)

    if len(dim_names) <= 1:
        return [(dim_names, dict(si.open_issues))]

    num_batches = min(max_batches, len(dim_names))
    batch_dims: list[list[str]] = [[] for _ in range(num_batches)]
    batch_counts: list[int] = [0] * num_batches

    for dim in dim_names:
        lightest = min(range(num_batches), key=lambda i: batch_counts[i])
        batch_dims[lightest].append(dim)
        batch_counts[lightest] += by_dim[dim]

    dim_to_issues: dict[str, dict[str, Issue]] = defaultdict(dict)
    for fid, issue in si.open_issues.items():
        detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        dim_to_issues[dim][fid] = issue

    result: list[tuple[list[str], dict[str, Issue]]] = []
    for dims in batch_dims:
        if not dims:
            continue
        subset: dict[str, Issue] = {}
        for dim in dims:
            subset.update(dim_to_issues.get(dim, {}))
        if subset:
            result.append((dims, subset))

    return result


def open_review_ids_from_state(state: StateModel) -> set[str]:
    return open_review_ids(state)


def has_open_review_issues(state: StateModel | dict | None) -> bool:
    return bool(open_review_ids_from_state(state or {}))


def cluster_issue_ids(cluster: Cluster) -> list[str]:
    """Return the effective issue IDs for a cluster.

    Falls back to ``action_steps[*].issue_refs`` when ``issue_ids`` is empty,
    since some saved plans retain membership only in step refs.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _append(raw_ids: object) -> None:
        if not isinstance(raw_ids, list):
            return
        for raw_id in raw_ids:
            if not isinstance(raw_id, str):
                continue
            issue_id = raw_id.strip()
            if not issue_id or issue_id in seen:
                continue
            seen.add(issue_id)
            ordered.append(issue_id)

    _append(cluster.get("issue_ids"))

    steps = cluster.get("action_steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            _append(step.get("issue_refs"))

    return ordered



def plan_review_ids(plan: PlanModel) -> list[str]:
    """Return review/concerns IDs currently represented in queue_order."""
    return [
        fid for fid in _queue_order(plan)
        if not fid.startswith("triage::")
        and not fid.startswith("workflow::")
        and (fid.startswith("review::") or fid.startswith("concerns::"))
    ]


def triage_coverage(
    plan: PlanModel,
    open_review_ids: set[str] | None = None,
) -> tuple[int, int, dict[str, Cluster]]:
    """Return (organized, total, clusters) for review issues in triage.

    When *open_review_ids* is provided, use it as the full set of review
    issues (from state) instead of falling back to queue_order.
    """
    clusters = _cluster_map(plan)
    all_cluster_ids: set[str] = set()
    for c in clusters.values():
        all_cluster_ids.update(cluster_issue_ids(c))
    if open_review_ids is not None:
        review_ids = list(open_review_ids)
    else:
        review_ids = plan_review_ids(plan)
    organized = sum(1 for fid in review_ids if fid in all_cluster_ids)
    return organized, len(review_ids), clusters


def manual_clusters_with_issues(plan: PlanModel) -> list[str]:
    return [
        name for name, c in _cluster_map(plan).items()
        if cluster_issue_ids(c) and not c.get("auto")
    ]

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

    has_completed_scan = bool(state.get("last_scan"))
    coverage_open_ids = open_review_ids_from_state(state)
    if not has_completed_scan and not coverage_open_ids:
        coverage_open_ids = set(plan_review_ids(plan))

    organized, total, clusters = triage_coverage(
        plan, open_review_ids=coverage_open_ids,
    )

    purge_ids(plan, [
        *TRIAGE_IDS,
        WORKFLOW_SCORE_CHECKPOINT_ID,
        WORKFLOW_CREATE_PLAN_ID,
    ])

    meta = _triage_meta(plan)
    if has_completed_scan:
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
    open_ids = sorted(coverage_open_ids)
    meta["triaged_ids"] = open_ids
    if effective_strategy_summary:
        meta["strategy_summary"] = effective_strategy_summary
    meta["trigger"] = "confirm_existing" if completion_mode == "confirm_existing" else "manual_triage"
    meta["last_completion_mode"] = completion_mode
    if normalized_note:
        meta["last_completion_note"] = normalized_note
    else:
        meta.pop("last_completion_note", None)
    meta["last_completed_at"] = utc_now()
    # Archive stages before clearing so previous analysis is preserved
    stages = meta.get("triage_stages", {})
    if stages:
        last_triage = {
            "completed_at": utc_now(),
            "stages": {k: dict(v) for k, v in stages.items()},
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

    resolved_services.save_plan(plan)

    cluster_count = len([c for c in clusters.values() if cluster_issue_ids(c)])
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


def find_cluster_for(fid: str, clusters: dict[str, Cluster]) -> str | None:
    for name, c in clusters.items():
        if fid in cluster_issue_ids(c):
            return name
    return None


def count_log_activity_since(plan: PlanModel, since: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for raw_entry in _execution_log(plan):
        if "timestamp" not in raw_entry or "action" not in raw_entry:
            continue
        timestamp = raw_entry["timestamp"]
        action = raw_entry["action"]
        if not isinstance(timestamp, str) or not isinstance(action, str):
            continue
        if timestamp >= since:
            counts[action] += 1
    return dict(counts)

__all__ = [
    "apply_completion",
    "cascade_clear_later_confirmations",
    "cluster_issue_ids",
    "count_log_activity_since",
    "find_cluster_for",
    "group_issues_into_observe_batches",
    "has_open_review_issues",
    "has_triage_in_queue",
    "inject_triage_stages",
    "manual_clusters_with_issues",
    "observe_dimension_breakdown",
    "open_review_ids_from_state",
    "plan_review_ids",
    "print_cascade_clear_feedback",
    "purge_triage_stage",
    "triage_coverage",
]
