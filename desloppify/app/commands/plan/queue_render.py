"""Compact queue table renderer for ``plan queue``."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.guardrails import print_triage_guardrail_info
from desloppify.app.commands.helpers.queue_progress import (
    QueueBreakdown,
    format_queue_headline,
)
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.base.output.terminal import colorize, print_table
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    build_work_queue,
)
from desloppify.engine._work_queue.plan_order import collapse_clusters
from desloppify.engine.plan import compute_new_issue_ids, load_plan, plan_path_for_state


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "\u2026"


def _print_queue_header(
    *,
    items: list[dict],
    include_skipped: bool,
    plan: dict,
    new_count: int = 0,
) -> None:
    total = len(items)
    skipped_count = sum(1 for it in items if it.get("plan_skipped"))
    non_skipped = total - skipped_count
    plan_skipped_total = len(plan.get("skipped", {}))

    # Count subjective items in the visible list
    subjective = sum(
        1 for it in items if it.get("kind") == "subjective_dimension"
    )

    # Count plan-ordered items (minus skipped)
    queue_order = plan.get("queue_order", [])
    skipped_ids = set(plan.get("skipped", {}).keys())
    plan_ordered = sum(1 for fid in queue_order if fid not in skipped_ids)

    breakdown = QueueBreakdown(
        queue_total=non_skipped,
        plan_ordered=plan_ordered,
        skipped=plan_skipped_total,
        subjective=subjective,
    )
    headline = format_queue_headline(breakdown)
    new_suffix = f"  ({new_count} new this scan)" if new_count > 0 else ""
    print(colorize(f"\n  {headline}{new_suffix}", "bold"))

    focus = plan.get("active_cluster")
    if focus:
        print(colorize(f"  Focus: {focus}", "cyan"))

    if include_skipped or skipped_count != 0:
        return
    if not plan_skipped_total:
        return
    print(
        colorize(
            f"  ({plan_skipped_total} skipped item{'s' if plan_skipped_total != 1 else ''}"
            " hidden — use --include-skipped)",
            "dim",
        )
    )


def _queue_display_items(items: list[dict], *, top: int) -> list[dict]:
    if top > 0 and len(items) > top:
        return items[:top]
    return items


_CLUSTER_TYPE_LABELS = {
    "auto/initial-review": "Initial subjective review",
    "auto/stale-review": "Stale subjective review",
    "auto/under-target-review": "Optional re-review",
}

_ACTION_TYPE_LABELS = {
    "auto_fix": "Auto-fixable batch",
    "reorganize": "Reorganize batch",
    "refactor": "Refactor batch",
    "manual_fix": "Grouped task",
}


def _cluster_type_label(cluster_name: str, action_type: str) -> str:
    if cluster_name in _CLUSTER_TYPE_LABELS:
        return _CLUSTER_TYPE_LABELS[cluster_name]
    return _ACTION_TYPE_LABELS.get(action_type, "Grouped task")


def _render_cluster_banner(item: dict, position: int, new_ids: set[str]) -> None:
    """Render a collapsed cluster as a visually distinct banner."""
    name = item.get("cluster_name", item.get("id", ""))
    member_count = item.get("member_count", 0)
    action_type = item.get("action_type", "manual_fix")
    type_label = _cluster_type_label(name, action_type)
    new_in_cluster = sum(
        1 for m in item.get("members", [])
        if m.get("id") in new_ids
    )
    new_tag = f"  (+{new_in_cluster} new)" if new_in_cluster else ""
    summary = item.get("summary", "")
    command = item.get("primary_command", "")

    label = f"{position}. {type_label} — {member_count} items{new_tag}"
    width = max(len(label) + 4, 50)
    bar = "─" * width
    print(colorize(f"  {bar}", "dim"))
    print(colorize(f"  {label}", "bold"))
    print(colorize(f"     Cluster: {name}", "dim"))
    if summary:
        print(colorize(f"     {summary}", "dim"))
    if command:
        print(colorize(f"     Run:      {command}", "cyan"))
    print(colorize(f"     Drill in: desloppify plan queue --cluster {name}", "dim"))
    print(colorize(f"  {bar}", "dim"))


def _build_rows(display_items: list[dict], new_ids: set[str] | None = None) -> list[list[str]]:
    rows: list[list[str]] = []
    _new = new_ids or set()
    for idx, item in enumerate(display_items, 1):
        pos = str(idx)
        kind = item.get("kind", "issue")

        if kind == "workflow_stage":
            blocked = item.get("is_blocked", False)
            blocked_tag = " [blocked]" if blocked else ""
            conf_str = "—"
            detector = "planning"
            summary = f"[TRIAGE] {item.get('summary', '')}{blocked_tag}"
            cluster_name = ""
        elif kind == "workflow_action":
            conf_str = "—"
            detector = "workflow"
            summary = item.get("summary", "")
            cluster_name = ""
        elif kind == "cluster":
            # Clusters are rendered as banners, not table rows
            continue
        else:
            conf_str = item.get("confidence", "medium")
            detector = item.get("detector", "")
            summary = item.get("summary", "")
            plan_cluster = item.get("plan_cluster")
            cluster_name = plan_cluster.get("name", "") if isinstance(plan_cluster, dict) else ""

        prefix = "* " if item.get("id") in _new else ""
        suffix = " [skip]" if item.get("plan_skipped") else ""
        summary_display = _truncate(prefix + summary, 48) + suffix
        rows.append([pos, conf_str, detector, summary_display, cluster_name])
    return rows


def cmd_plan_queue(args: argparse.Namespace) -> None:
    """Render a compact table of all upcoming queue items."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    top = getattr(args, "top", 30)
    cluster_filter = getattr(args, "cluster", None)
    include_skipped = bool(getattr(args, "include_skipped", False))

    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)
    print_triage_guardrail_info(plan=plan, state=state)

    effective_cluster = cluster_filter
    if not cluster_filter:
        active_cluster = plan.get("active_cluster")
        if active_cluster:
            effective_cluster = active_cluster

    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            status="open",
            include_subjective=True,
            plan=plan,
            include_skipped=include_skipped,
            cluster=effective_cluster,
        ),
    )
    items = queue.get("items", [])
    # Collapse auto-clusters into display meta-items
    if plan and not effective_cluster and not plan.get("active_cluster"):
        items = collapse_clusters(items, plan)

    sort_by = getattr(args, "sort", "priority")
    all_new_ids: set[str] = queue.get("new_ids", set())
    # Merge review-based new issue IDs (since last triage)
    review_new_ids = compute_new_issue_ids(plan, state)
    all_new_ids = all_new_ids | review_new_ids
    item_ids = {it.get("id") for it in items}
    new_ids = all_new_ids & item_ids

    if sort_by == "recent":
        items = sorted(items, key=lambda it: it.get("first_seen", ""), reverse=True)

    _print_queue_header(
        items=items,
        include_skipped=include_skipped,
        plan=plan,
        new_count=len(new_ids),
    )

    if not items:
        print(colorize("\n  Queue is empty.", "green"))
        return

    # Determine which items to show
    display_items = _queue_display_items(items, top=top)

    # Render cluster banners first, then remaining items in the table
    print()
    for idx, item in enumerate(display_items, 1):
        if item.get("kind") == "cluster":
            _render_cluster_banner(item, idx, new_ids)

    rows = _build_rows(display_items, new_ids=new_ids)
    if rows:
        headers = ["#", "Confidence", "Detector", "Summary", "Cluster"]
        widths = [4, 4, 12, 50, 16]
        print_table(headers, rows, widths=widths)

    if top > 0 and len(items) > top:
        remaining = len(items) - top
        print(colorize(
            f"\n  ... and {remaining} more (use --top 0 to show all)", "dim"
        ))
    print()


__all__ = ["cmd_plan_queue"]
