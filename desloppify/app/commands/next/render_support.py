"""Shared render helpers for ``desloppify next`` terminal output."""

from __future__ import annotations

from collections import Counter

from desloppify.app.commands.helpers.queue_progress import format_plan_delta
from desloppify.base.output.terminal import colorize
from desloppify.engine._work_queue.core import group_queue_items
from desloppify.engine.planning.scorecard_projection import (
    scorecard_subjective_entries,
)
from desloppify.intelligence.integrity import subjective_review_open_breakdown

_ACTION_TYPE_LABELS = {
    "auto_fix": "Auto-fixable batch",
    "reorganize": "Reorganize batch",
    "refactor": "Refactor batch",
    "manual_fix": "Grouped task",
}
_CLUSTER_NAME_LABELS = {
    "auto/initial-review": "Initial subjective review",
    "auto/stale-review": "Stale subjective review",
    "auto/under-target-review": "Optional re-review",
}


def scorecard_subjective(
    state: dict,
    dim_scores: dict,
) -> list[dict]:
    """Return scorecard-aligned subjective entries for current dimension scores."""
    if not dim_scores:
        return []
    return scorecard_subjective_entries(
        state,
        dim_scores=dim_scores,
    )


def subjective_coverage_breakdown(
    issues_scoped: dict,
) -> tuple[int, dict[str, int], dict[str, int]]:
    """Return open subjective-review count plus reason and holistic-reason breakdowns."""
    return subjective_review_open_breakdown(issues_scoped)


def is_auto_fix_command(command: str | None) -> bool:
    cmd = (command or "").strip()
    return cmd.startswith("desloppify autofix ") and "--dry-run" in cmd


def effort_tag(item: dict) -> str:
    """Return a short effort/type tag for a queue item."""
    if item.get("detector") == "review":
        return "[review]"
    if is_auto_fix_command(item.get("primary_command")):
        return "[auto]"
    return ""


def render_grouped(items: list[dict], group: str) -> None:
    grouped = group_queue_items(items, group)
    for key, grouped_items in grouped.items():
        print(colorize(f"\n  {key} ({len(grouped_items)})", "cyan"))
        for item in grouped_items:
            confidence = item.get("confidence", "medium")
            tag = effort_tag(item)
            tag_str = f" {tag}" if tag else ""
            print(
                f"    [{confidence}]{tag_str} {item.get('summary', '')}"
            )


def _cluster_type_label(cluster_name: str, action_type: str) -> str:
    if cluster_name in _CLUSTER_NAME_LABELS:
        return _CLUSTER_NAME_LABELS[cluster_name]
    return _ACTION_TYPE_LABELS.get(action_type, "Grouped task")


def _render_cluster_files(members: list[dict]) -> None:
    file_counts = Counter(m.get("file", "?") for m in members)
    if len(file_counts) <= 5:
        print(colorize("\n  Files:", "dim"))
        for filename, count in file_counts.most_common():
            print(f"    {filename} ({count})")
        return

    print(colorize(f"\n  Spread across {len(file_counts)} files:", "dim"))
    for filename, count in file_counts.most_common(3):
        print(f"    {filename} ({count})")
    remaining = len(file_counts) - 3
    print(colorize(f"    ... and {remaining} more files", "dim"))


def _render_cluster_sample(members: list[dict]) -> None:
    print(colorize("\n  Sample:", "dim"))
    for member in members[:3]:
        print(f"    - {member.get('id', '')}")
    if len(members) > 3:
        print(colorize(f"    ... and {len(members) - 3} more", "dim"))


def _render_optional_cluster_commands(cluster_name: str) -> None:
    print(colorize(f"\n  Skip:          desloppify plan skip {cluster_name}", "dim"))
    print(colorize(f"  Drill in:      desloppify next --cluster {cluster_name} --count 10", "dim"))
    print(
        colorize(
            f'  Resolve all:   desloppify plan resolve "{cluster_name}" --note "<what>" --confirm',
            "dim",
        )
    )


def _render_required_cluster_commands(cluster_name: str) -> None:
    print(
        colorize(
            f'\n  Resolve all:   desloppify plan resolve "{cluster_name}" --note "<what>" --confirm',
            "dim",
        )
    )
    print(colorize(f"  Drill in:      desloppify next --cluster {cluster_name} --count 10", "dim"))
    print(colorize(f"  Skip cluster:  desloppify plan skip {cluster_name}", "dim"))


def render_cluster_item(item: dict) -> None:
    """Render an auto-cluster task card."""
    member_count = int(item.get("member_count", 0))
    action_type = item.get("action_type", "manual_fix")
    cluster_name = item.get("id", "")
    is_optional = bool(item.get("cluster_optional"))
    type_label = _cluster_type_label(cluster_name, action_type)
    optional_tag = " — optional" if is_optional else ""
    print(colorize(f"  ({type_label}, {member_count} issues{optional_tag})", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")

    action_steps = item.get("action_steps") or []
    if action_steps:
        print(colorize(
            f"  [plan: {len(action_steps)} steps] drill in to view",
            "dim",
        ))

    members = item.get("members", [])
    if members:
        _render_cluster_files(members)
        _render_cluster_sample(members)

    primary_command = item.get("primary_command")
    if primary_command:
        print(colorize(f"\n  Action: {primary_command}", "cyan"))

    if is_optional:
        _render_optional_cluster_commands(cluster_name)
        return

    _render_required_cluster_commands(cluster_name)


def render_queue_header(queue: dict, explain: bool) -> None:
    del explain
    total = queue.get("total", 0)
    items = queue.get("items", [])
    # When the only item is the "run scan" workflow action, show "Queue cleared"
    # instead of a misleading "1 items" count.
    if (
        total == 1
        and len(items) == 1
        and items[0].get("id") == "workflow::run-scan"
    ):
        print(colorize("\n  Queue cleared (1 workflow step)", "bold"))
    else:
        print(colorize(f"\n  Queue: {total} item{'s' if total != 1 else ''}", "bold"))


def show_empty_queue(
    queue: dict,
    strict: float | None,
    *,
    plan_start_strict: float | None = None,
    target_strict: float | None = None,
) -> bool:
    del target_strict
    if queue.get("items"):
        return False
    if plan_start_strict is not None and strict is not None:
        delta = format_plan_delta(strict, plan_start_strict)
        delta_str = f" ({delta})" if delta else ""
        print(colorize("\n  Queue cleared!", "green"))
        print(colorize(
            f"  Frozen plan-start: strict {plan_start_strict:.1f} → Live estimate: strict {strict:.1f}{delta_str}",
            "cyan",
        ))
        print(colorize(
            "  Run `desloppify scan` now to finalize and reveal your updated score.",
            "dim",
        ))
        return True

    suffix = f" Strict score: {strict:.1f}/100" if strict is not None else ""
    print(colorize(f"\n  Nothing to do!{suffix}", "green"))
    return True


def render_compact_item(item: dict, idx: int, total: int) -> None:
    """One-line summary for cluster drill-in items after the first."""
    confidence = item.get("confidence", "medium")
    tag = effort_tag(item)
    tag_str = f" {tag}" if tag else ""
    plan_cluster = item.get("plan_cluster")
    if isinstance(plan_cluster, dict) and (plan_cluster.get("action_steps") or []):
        tag_str += " [plan]"
    fid = item.get("id", "")
    short = fid.rsplit("::", 1)[-1][:8] if "::" in fid else fid
    print(f"  [{idx + 1}/{total}] [{confidence}]{tag_str} {item.get('summary', '')}")
    print(colorize(f"         {item.get('file', '')}  [{short}]", "dim"))


__all__ = [
    "effort_tag",
    "is_auto_fix_command",
    "render_cluster_item",
    "render_compact_item",
    "render_grouped",
    "render_queue_header",
    "scorecard_subjective",
    "show_empty_queue",
    "subjective_coverage_breakdown",
]
