"""Helper utilities for plan triage workflow."""

from __future__ import annotations

import argparse
from collections import defaultdict

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    TRIAGE_IDS,
    TRIAGE_STAGE_IDS,
    open_review_ids,
    purge_ids,
    review_issue_snapshot_hash,
)
from desloppify.state import utc_now

from .services import TriageServices, default_triage_services

_STAGE_ORDER = ["observe", "reflect", "organize", "enrich", "sense-check"]


def has_triage_in_queue(plan: dict) -> bool:
    """Check if any triage stage ID is in the queue."""
    order = set(plan.get("queue_order", []))
    return bool(order & TRIAGE_IDS)

def inject_triage_stages(plan: dict) -> None:
    """Inject all triage stage IDs into the queue (fresh start)."""
    order: list[str] = plan.setdefault("queue_order", [])
    remaining = [issue_id for issue_id in order if issue_id not in TRIAGE_IDS]
    order[:] = [*TRIAGE_STAGE_IDS, *remaining]

def purge_triage_stage(plan: dict, stage_name: str) -> None:
    """Purge a single triage stage ID from the queue."""
    sid = f"triage::{stage_name}"
    purge_ids(plan, [sid])

def cascade_clear_later_confirmations(stages: dict, from_stage: str) -> list[str]:
    """Clear confirmed_at/confirmed_text on stages AFTER *from_stage*. Returns cleared names."""
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

def print_cascade_clear_feedback(cleared: list[str], stages: dict) -> None:
    """Print yellow cascade-clear message with next-step guidance."""
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

def observe_dimension_breakdown(si) -> tuple[dict[str, int], list[str]]:
    """Count issues per dimension from a TriageInput. Returns (by_dim, sorted_dim_names)."""
    by_dim: dict[str, int] = defaultdict(int)
    for _fid, f in si.open_issues.items():
        detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        by_dim[dim] += 1
    dim_names = sorted(by_dim, key=lambda d: (-by_dim[d], d))
    return dict(by_dim), dim_names

def group_issues_into_observe_batches(
    si,
    max_batches: int = 5,
) -> list[tuple[list[str], dict[str, dict]]]:
    """Group issues by dimension into batches for parallel observe.

    Returns list of (dimension_names, issues_subset) tuples.
    Single batch if only one dimension exists.
    """
    by_dim, dim_names = observe_dimension_breakdown(si)

    if len(dim_names) <= 1:
        return [(dim_names, dict(si.open_issues))]

    # Distribute dimensions into balanced batches by issue count
    num_batches = min(max_batches, len(dim_names))
    batch_dims: list[list[str]] = [[] for _ in range(num_batches)]
    batch_counts: list[int] = [0] * num_batches

    # Greedy: assign each dimension (largest first) to the lightest batch
    for dim in dim_names:
        lightest = min(range(num_batches), key=lambda i: batch_counts[i])
        batch_dims[lightest].append(dim)
        batch_counts[lightest] += by_dim[dim]

    # Build issue subsets per batch
    # Pre-index issues by dimension
    dim_to_issues: dict[str, dict[str, dict]] = defaultdict(dict)
    for fid, f in si.open_issues.items():
        detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        dim_to_issues[dim][fid] = f

    result: list[tuple[list[str], dict[str, dict]]] = []
    for dims in batch_dims:
        if not dims:
            continue
        subset: dict[str, dict] = {}
        for dim in dims:
            subset.update(dim_to_issues.get(dim, {}))
        if subset:
            result.append((dims, subset))

    return result


def open_review_ids_from_state(state: dict) -> set[str]:
    """Return IDs of open review/concerns issues (excludes subjective_review placeholders)."""
    return open_review_ids(state)

def triage_coverage(
    plan: dict,
    open_review_ids: set[str] | None = None,
) -> tuple[int, int, dict]:
    """Return (organized, total, clusters) for review issues in triage.

    When *open_review_ids* is provided, use it as the full set of review
    issues (from state) instead of falling back to queue_order.
    """
    clusters = plan.get("clusters", {})
    all_cluster_ids: set[str] = set()
    for c in clusters.values():
        all_cluster_ids.update(c.get("issue_ids", []))
    if open_review_ids is not None:
        review_ids = list(open_review_ids)
    else:
        review_ids = [
            fid for fid in plan.get("queue_order", [])
            if not fid.startswith("triage::") and not fid.startswith("workflow::") and (fid.startswith("review::") or fid.startswith("concerns::"))
        ]
    organized = sum(1 for fid in review_ids if fid in all_cluster_ids)
    return organized, len(review_ids), clusters

def manual_clusters_with_issues(plan: dict) -> list[str]:
    """Return names of non-auto clusters that have issues."""
    return [
        name for name, c in plan.get("clusters", {}).items()
        if c.get("issue_ids") and not c.get("auto")
    ]

def apply_completion(
    args: argparse.Namespace,
    plan: dict,
    strategy: str,
    *,
    services: TriageServices | None = None,
) -> None:
    """Shared completion logic: update meta, remove triage::pending, save."""
    resolved_services = services or default_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state

    organized, total, clusters = triage_coverage(
        plan, open_review_ids=open_review_ids_from_state(state),
    )

    # Purge all triage stage IDs.
    purge_ids(plan, list(TRIAGE_IDS))

    current_hash = review_issue_snapshot_hash(state)

    meta = plan.setdefault("epic_triage_meta", {})
    meta["issue_snapshot_hash"] = current_hash
    open_ids = sorted(open_review_ids(state))
    meta["triaged_ids"] = open_ids
    if strategy.strip().lower() != "same":
        meta["strategy_summary"] = strategy
    meta["trigger"] = "manual_triage"
    meta["last_completed_at"] = utc_now()
    # Archive stages before clearing so previous analysis is preserved
    stages = meta.get("triage_stages", {})
    if stages:
        meta["last_triage"] = {
            "completed_at": utc_now(),
            "stages": {k: dict(v) for k, v in stages.items()},
            "strategy": strategy if strategy.strip().lower() != "same" else meta.get("strategy_summary", ""),
        }
    meta["triage_stages"] = {}  # clear stages on completion
    meta.pop("stage_refresh_required", None)
    meta.pop("stage_snapshot_hash", None)

    resolved_services.save_plan(plan)

    cluster_count = len([c for c in clusters.values() if c.get("issue_ids")])
    print(colorize(f"  Triage complete: {organized}/{total} issues in {cluster_count} cluster(s).", "green"))
    effective_strategy = strategy if strategy.strip().lower() != "same" else meta.get("strategy_summary", "")
    if effective_strategy:
        print(colorize(f"  Strategy: {effective_strategy}", "cyan"))
    print(colorize("  Run `desloppify next` to start implementation.", "green"))

def find_cluster_for(fid: str, clusters: dict) -> str | None:
    """Return the cluster name containing *fid*, or None."""
    for name, c in clusters.items():
        if fid in c.get("issue_ids", []):
            return name
    return None

def count_log_activity_since(plan: dict, since: str) -> dict[str, int]:
    """Count execution log entries by action since *since* timestamp."""
    counts: dict[str, int] = defaultdict(int)
    for entry in plan.get("execution_log", []):
        if entry.get("timestamp", "") >= since:
            counts[entry.get("action", "unknown")] += 1
    return dict(counts)

__all__ = [
    "apply_completion",
    "cascade_clear_later_confirmations",
    "count_log_activity_since",
    "find_cluster_for",
    "group_issues_into_observe_batches",
    "has_triage_in_queue",
    "inject_triage_stages",
    "manual_clusters_with_issues",
    "observe_dimension_breakdown",
    "open_review_ids_from_state",
    "print_cascade_clear_feedback",
    "purge_triage_stage",
    "triage_coverage",
]
