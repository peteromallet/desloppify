"""Shared render helpers for ``desloppify next`` terminal output."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from desloppify.app.commands.helpers.queue_progress import format_plan_delta
from desloppify.base.output.terminal import colorize
from desloppify.engine._state.issue_semantics import is_review_finding
from desloppify.engine._work_queue.helpers import is_auto_fix_item
from desloppify.engine.work_queue import group_queue_items
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
    "auto/under-target-review": "Below-target re-review",
}


@dataclass(frozen=True)
class ClusterTypeLabels:
    action_types: dict[str, str]
    cluster_names: dict[str, str]


CLUSTER_TYPE_LABELS = ClusterTypeLabels(
    action_types=_ACTION_TYPE_LABELS,
    cluster_names=_CLUSTER_NAME_LABELS,
)


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
    if is_review_finding(item):
        return "[review]"
    if is_auto_fix_item(item):
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
    if cluster_name in CLUSTER_TYPE_LABELS.cluster_names:
        return CLUSTER_TYPE_LABELS.cluster_names[cluster_name]
    return CLUSTER_TYPE_LABELS.action_types.get(action_type, "Grouped task")


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
        summary = member.get("summary") or member.get("id", "")
        print(f"    - {summary}")
    if len(members) > 3:
        print(colorize(f"    ... and {len(members) - 3} more", "dim"))


def cluster_action_commands(cluster_name: str) -> dict[str, str]:
    """Return semantic cluster action commands independent of terminal labels."""
    return {
        "resolve_all": f'desloppify plan resolve "{cluster_name}" --note "<what>" --confirm',
        "drill_in": f"desloppify next --cluster {cluster_name} --count 10",
        "skip": f"desloppify plan skip {cluster_name}",
    }


def _render_optional_cluster_commands(cluster_name: str) -> None:
    commands = cluster_action_commands(cluster_name)
    print(colorize(f"\n  Skip:          {commands['skip']}", "dim"))
    print(colorize(f"  Drill in:      {commands['drill_in']}", "dim"))
    print(
        colorize(
            f"  Resolve all:   {commands['resolve_all']}",
            "dim",
        )
    )


def _render_required_cluster_commands(cluster_name: str) -> None:
    commands = cluster_action_commands(cluster_name)
    print(
        colorize(
            f"\n  Resolve all:   {commands['resolve_all']}",
            "dim",
        )
    )
    print(colorize(f"  Drill in:      {commands['drill_in']}", "dim"))
    print(colorize(f"  Skip cluster:  {commands['skip']}", "dim"))


def _step_display_text(step: str | dict) -> str:
    """Extract display text from an action step (string or dict with title)."""
    if isinstance(step, dict):
        return step.get("title", str(step))
    return str(step)


def _cluster_header_bits(item: dict) -> tuple[str, str, str, list[dict]]:
    cluster_name = item.get("id", "")
    action_type = item.get("action_type", "manual_fix")
    action_steps = item.get("action_steps") or []
    done_count = sum(1 for s in action_steps if isinstance(s, dict) and s.get("done"))
    step_badge = f" [{done_count}/{len(action_steps)} steps done]" if action_steps else ""
    optional_tag = " — optional" if item.get("cluster_optional") else ""
    type_label = _cluster_type_label(cluster_name, action_type)
    return cluster_name, type_label, f"{step_badge}{optional_tag}", action_steps


def _render_cluster_steps(action_steps: list[dict]) -> None:
    if not action_steps:
        return
    show_count = min(3, len(action_steps))
    for i, step in enumerate(action_steps[:show_count], 1):
        marker = "[x]" if isinstance(step, dict) and step.get("done") else "[ ]"
        print(colorize(f"    {i}. {marker} {_step_display_text(step)}", "dim"))
    remaining = len(action_steps) - show_count
    if remaining > 0:
        print(colorize(f"    ... and {remaining} more — drill in to view all", "dim"))


def _render_cluster_priority(dep_order: object) -> None:
    if dep_order is not None and dep_order <= 2:
        print(colorize("  Priority: complete before other clusters", "cyan"))


def _render_cluster_primary_action(item: dict) -> None:
    autofix_hint = item.get("autofix_hint")
    primary_command = item.get("primary_command")
    if autofix_hint:
        print(colorize(f"\n  Try auto first: {autofix_hint}", "cyan"))
        print(colorize("  If auto finds 0, drill into individual issues:", "dim"))
    if primary_command:
        print(colorize(f"  Action: {primary_command}", "cyan"))


def render_cluster_item(item: dict) -> None:
    """Render an auto-cluster task card."""
    member_count = int(item.get("member_count", 0))
    is_optional = bool(item.get("cluster_optional"))
    cluster_name, type_label, suffix, action_steps = _cluster_header_bits(item)
    print(colorize(f"  ({type_label}, {member_count} issues{suffix})", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")

    _render_cluster_steps(action_steps)
    _render_cluster_priority(item.get("dependency_order"))

    members = item.get("members", [])
    if members:
        _render_cluster_files(members)
        _render_cluster_sample(members)

    _render_cluster_primary_action(item)

    if is_optional:
        _render_optional_cluster_commands(cluster_name)
        return

    _render_required_cluster_commands(cluster_name)


def render_queue_header(queue: dict, explain: bool) -> None:
    del explain
    total = queue.get("total", 0)
    print(colorize(f"\n  Queue: {total} item{'s' if total != 1 else ''}", "bold"))
    if total > 5:
        print(colorize("  (Skip items only when explicitly requested.)", "dim"))


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
    detail = item.get("detail", {})
    location = detail.get("route") or item.get("file", "")
    print(f"  [{idx + 1}/{total}] [{confidence}]{tag_str} {item.get('summary', '')}")
    print(colorize(f"         {location}  [{short}]", "dim"))


__all__ = [
    "CLUSTER_TYPE_LABELS",
    "ClusterTypeLabels",
    "cluster_action_commands",
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
