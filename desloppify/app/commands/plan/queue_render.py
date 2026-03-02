"""Compact queue table renderer for ``plan queue``."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.core.output_api import colorize, print_table
from desloppify.engine.plan import load_plan
from desloppify.engine.work_queue import QueueBuildOptions, build_work_queue


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "\u2026"


def _cluster_tier_label(item: dict) -> str:
    """Compute a tier label from cluster members, e.g. 'T2' or 'T1-T3'."""
    members = item.get("members", [])
    if not members:
        return ""
    tiers = {int(m.get("effective_tier", m.get("tier", 3))) for m in members}
    lo, hi = min(tiers), max(tiers)
    if lo == hi:
        return f"T{lo}"
    return f"T{lo}-T{hi}"


def _resolve_plan_context(plan: dict, cluster_filter: str | None) -> tuple[dict | None, str | None]:
    plan_data: dict | None = None
    if plan.get("queue_order") or plan.get("overrides") or plan.get("clusters"):
        plan_data = plan

    effective_cluster = cluster_filter
    if plan_data and not cluster_filter:
        active_cluster = plan_data.get("active_cluster")
        if active_cluster:
            effective_cluster = active_cluster
    return plan_data, effective_cluster


def _print_queue_header(
    *,
    items: list[dict],
    tier_counts: dict,
    include_skipped: bool,
    plan: dict,
    plan_data: dict | None,
) -> None:
    total = len(items)
    skipped_count = sum(1 for it in items if it.get("plan_skipped"))
    non_skipped = total - skipped_count
    tc_parts = " ".join(f"T{t}:{tier_counts.get(t, 0)}" for t in (1, 2, 3, 4))
    finding_total = sum(tier_counts.get(t, 0) for t in (1, 2, 3, 4))
    if finding_total != non_skipped:
        print(colorize(f"\n  Queue: {non_skipped} entries  ({finding_total} findings: {tc_parts})", "bold"))
    else:
        print(colorize(f"\n  Queue: {non_skipped} items  ({tc_parts})", "bold"))

    focus = plan.get("active_cluster") if plan_data else None
    if focus:
        print(colorize(f"  Focus: {focus}", "cyan"))

    if include_skipped or skipped_count != 0:
        return
    plan_skipped_count = len(plan.get("skipped", {})) if plan_data else 0
    if not plan_skipped_count:
        return
    print(
        colorize(
            f"  ({plan_skipped_count} skipped item{'s' if plan_skipped_count != 1 else ''}"
            " hidden — use --include-skipped)",
            "dim",
        )
    )


def _queue_display_items(items: list[dict], *, top: int) -> list[dict]:
    if top > 0 and len(items) > top:
        return items[:top]
    return items


def _build_rows(display_items: list[dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    for idx, item in enumerate(display_items, 1):
        pos = str(idx)
        kind = item.get("kind", "finding")

        if kind == "cluster":
            tier_str = _cluster_tier_label(item)
            member_count = item.get("member_count", 0)
            detector = item.get("detector", "cluster")
            summary = f"[{member_count} items] {item.get('summary', '')}"
            cluster_name = item.get("cluster_name", item.get("id", ""))
        else:
            tier_val = int(item.get("effective_tier", item.get("tier", 3)))
            tier_str = f"T{tier_val}"
            detector = item.get("detector", "")
            summary = item.get("summary", "")
            plan_cluster = item.get("plan_cluster")
            cluster_name = plan_cluster.get("name", "") if isinstance(plan_cluster, dict) else ""

        suffix = " [skip]" if item.get("plan_skipped") else ""
        summary_display = _truncate(summary, 48) + suffix
        rows.append([pos, tier_str, detector, summary_display, cluster_name])
    return rows


def cmd_plan_queue(args: argparse.Namespace) -> None:
    """Render a compact table of all upcoming queue items."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    top = getattr(args, "top", 30)
    tier_filter = getattr(args, "tier", None)
    cluster_filter = getattr(args, "cluster", None)
    include_skipped = bool(getattr(args, "include_skipped", False))

    plan = load_plan()
    plan_data, effective_cluster = _resolve_plan_context(plan, cluster_filter)

    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            tier=tier_filter,
            count=None,
            scan_path=state.get("scan_path"),
            status="open",
            include_subjective=True,
            plan=plan_data,
            include_skipped=include_skipped,
            cluster=effective_cluster,
            collapse_clusters=True,
        ),
    )
    items = queue.get("items", [])
    tier_counts = queue.get("tier_counts", {})

    _print_queue_header(
        items=items,
        tier_counts=tier_counts,
        include_skipped=include_skipped,
        plan=plan,
        plan_data=plan_data,
    )

    if not items:
        print(colorize("\n  Queue is empty.", "green"))
        return

    # Determine which items to show
    display_items = _queue_display_items(items, top=top)
    headers = ["#", "Tier", "Detector", "Summary", "Cluster"]
    rows = _build_rows(display_items)

    print()
    widths = [4, 4, 12, 50, 16]
    print_table(headers, rows, widths=widths)

    if top > 0 and len(items) > top:
        remaining = len(items) - top
        print(colorize(
            f"\n  ... and {remaining} more (use --top 0 to show all)", "dim"
        ))
    print()


__all__ = ["cmd_plan_queue"]
