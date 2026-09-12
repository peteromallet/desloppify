"""Compact queue table renderer for ``plan queue``."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.guardrails import print_triage_guardrail_info
from desloppify.app.commands.helpers.queue_progress import (
    QueueBreakdown,
    format_queue_headline,
)
from desloppify.app.commands.helpers.state import require_issue_inventory
from desloppify.app.commands.next.render_support import CLUSTER_TYPE_LABELS
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.output.terminal import colorize, print_table
from desloppify.engine._plan.sync.triage import compute_new_issue_ids
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
)
from desloppify.engine._work_queue.plan_order import (
    collapse_clusters,
    filter_cluster_focus,
)
from desloppify.engine.plan_state import load_plan
from desloppify.engine.planning.queue_policy import build_execution_queue


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


def _cluster_type_label(cluster_name: str, action_type: str) -> str:
    if cluster_name in CLUSTER_TYPE_LABELS.cluster_names:
        return CLUSTER_TYPE_LABELS.cluster_names[cluster_name]
    return CLUSTER_TYPE_LABELS.action_types.get(action_type, "Grouped task")


def _render_cluster_banner(item: dict, position: int, new_ids: set[str]) -> None:
    """Render a collapsed cluster as a visually distinct banner."""
    name = item.get("cluster_name", item.get("id", ""))
    member_count = item.get("member_count", 0)
    action_type = item.get("action_type", "manual_fix")
    type_label = _cluster_type_label(name, action_type)
    cluster_type_tag = "[auto]" if item.get("cluster_auto", True) else "[triage]"
    new_in_cluster = sum(
        1 for m in item.get("members", [])
        if m.get("id") in new_ids
    )
    new_tag = f"  (+{new_in_cluster} new)" if new_in_cluster else ""
    # Step progress badge
    action_steps = item.get("action_steps") or []
    step_badge = ""
    if action_steps:
        done_count = sum(1 for s in action_steps if isinstance(s, dict) and s.get("done"))
        step_badge = f"  [{done_count}/{len(action_steps)} steps]"
    summary = item.get("summary", "")
    command = item.get("primary_command", "")

    label = f"{position}. {cluster_type_tag} {type_label} — {member_count} items{step_badge}{new_tag}"
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


def _resolve_effective_cluster(plan: dict, cluster_filter: str | None) -> str | None:
    """Resolve explicit cluster filter or fallback to active cluster focus."""
    if cluster_filter:
        return cluster_filter
    active_cluster = plan.get("active_cluster")
    if active_cluster:
        return active_cluster
    return None


def _build_queue_items(
    *,
    state: dict,
    plan: dict,
    include_skipped: bool,
    effective_cluster: str | None,
    subjective_threshold: float,
) -> tuple[list[dict], dict]:
    """Build queue items with focus/collapse view transforms applied."""
    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            status="open",
            include_subjective=True,
            subjective_threshold=subjective_threshold,
            plan=plan,
            include_skipped=include_skipped,
        ),
    )
    items = queue.get("items", [])
    if effective_cluster:
        items = filter_cluster_focus(items, plan, effective_cluster)
    if plan and not effective_cluster and not plan.get("active_cluster"):
        items = collapse_clusters(items, plan)
    return items, queue


def _compute_visible_new_ids(*, queue: dict, plan: dict, state: dict, items: list[dict]) -> set[str]:
    """Compute new IDs for the current queue view, including review-driven IDs."""
    all_new_ids: set[str] = queue.get("new_ids", set())
    all_new_ids |= compute_new_issue_ids(plan, state)
    item_ids = {it.get("id") for it in items}
    return all_new_ids & item_ids


def _render_cluster_banners(display_items: list[dict], new_ids: set[str]) -> int:
    """Render collapsed cluster banners and return banner count."""
    cluster_count = 0
    for idx, item in enumerate(display_items, 1):
        if item.get("kind") != "cluster":
            continue
        _render_cluster_banner(item, idx, new_ids)
        cluster_count += 1
    return cluster_count


def _render_queue_rows(display_items: list[dict], new_ids: set[str]) -> bool:
    """Render queue rows table. Returns True when rows were printed."""
    rows = _build_rows(display_items, new_ids=new_ids)
    if not rows:
        return False
    headers = ["#", "Confidence", "Detector", "Summary", "Cluster"]
    widths = [4, 4, 12, 50, 16]
    print_table(headers, rows, widths=widths)
    return True


def cmd_plan_queue(args: argparse.Namespace) -> None:
    """Render a compact table of all upcoming queue items."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_issue_inventory(state):
        return

    top = getattr(args, "top", 30)
    cluster_filter = getattr(args, "cluster", None)
    include_skipped = bool(getattr(args, "include_skipped", False))

    plan = load_plan()
    print_triage_guardrail_info(plan=plan, state=state)

    effective_cluster = _resolve_effective_cluster(plan, cluster_filter)
    items, queue = _build_queue_items(
        state=state,
        plan=plan,
        include_skipped=include_skipped,
        effective_cluster=effective_cluster,
        subjective_threshold=target_strict_score_from_config(runtime.config),
    )

    sort_by = getattr(args, "sort", "priority")
    new_ids = _compute_visible_new_ids(queue=queue, plan=plan, state=state, items=items)

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

    print()
    cluster_count = _render_cluster_banners(display_items, new_ids)
    rows_rendered = _render_queue_rows(display_items, new_ids)

    if cluster_count and rows_rendered:
        print(colorize(
            f"  ({cluster_count} cluster banner{'s' if cluster_count != 1 else ''}"
            " shown above — table shows remaining individual items)",
            "dim",
        ))

    if top > 0 and len(items) > top:
        remaining = len(items) - top
        print(colorize(
            f"\n  ... and {remaining} more (use --top 0 to show all)", "dim"
        ))
    print()


__all__ = ["cmd_plan_queue"]
