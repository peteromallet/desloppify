"""Output helpers for the `next` command."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from desloppify.base.output.fallbacks import print_write_error

_CLUSTER_MEMBER_SAMPLE_LIMIT = 25


def _serialize_cluster_member(member: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a cluster member without nested plan metadata."""
    serialized: dict[str, Any] = {
        "id": member.get("id"),
        "confidence": member.get("confidence"),
        "detector": member.get("detector"),
        "file": member.get("file"),
        "summary": member.get("summary"),
        "status": member.get("status"),
    }
    serialized["kind"] = member.get("kind", "issue")
    serialized["primary_command"] = member.get("primary_command")
    return serialized


def _serialize_cluster_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize cluster queue meta-items with sampled members."""
    members_raw = item.get("members", [])
    serialized_members = [
        _serialize_cluster_member(member)
        for member in members_raw[:_CLUSTER_MEMBER_SAMPLE_LIMIT]
    ]
    member_count = int(item.get("member_count", len(members_raw)))
    serialized_cluster: dict[str, Any] = {
        "id": item.get("id"),
        "action_type": item.get("action_type", "manual_fix"),
        "summary": item.get("summary"),
        "member_count": member_count,
        "members": serialized_members,
        "cluster_name": item.get("cluster_name", item.get("id")),
        "cluster_auto": item.get("cluster_auto", True),
        "detector": item.get("detector"),
    }
    serialized_cluster["kind"] = "cluster"
    serialized_cluster["primary_command"] = item.get("primary_command")
    if member_count > len(serialized_members):
        serialized_cluster["members_truncated"] = True
        serialized_cluster["members_sample_limit"] = _CLUSTER_MEMBER_SAMPLE_LIMIT

    autofix_hint = item.get("autofix_hint")
    if autofix_hint:
        serialized_cluster["autofix_hint"] = autofix_hint
    action_steps = item.get("action_steps") or []
    if action_steps:
        serialized_cluster["action_steps"] = action_steps
    return serialized_cluster


def _serialize_issue_item_base(item: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize core issue fields shared across output modes."""
    serialized: dict[str, Any] = {
        "id": item.get("id"),
        "confidence": item.get("confidence"),
        "detector": item.get("detector"),
        "file": item.get("file"),
        "summary": item.get("summary"),
        "detail": item.get("detail", {}),
        "status": item.get("status"),
    }
    serialized["kind"] = item.get("kind", "issue")
    serialized["primary_command"] = item.get("primary_command")
    return serialized


def serialize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Build a serializable output dict from a queue item."""
    if item.get("kind") == "cluster":
        return _serialize_cluster_item(item)

    serialized = _serialize_issue_item_base(item)

    # Workflow state
    blocked_by = item.get("blocked_by")
    if blocked_by:
        serialized["blocked_by"] = blocked_by
    if item.get("is_blocked"):
        serialized["is_blocked"] = True
    explain = item.get("explain")
    if explain is not None:
        serialized["explain"] = explain

    # Plan metadata
    for key in ("queue_position", "plan_description", "plan_note", "plan_cluster"):
        value = item.get(key)
        if value:
            serialized[key] = value
    if item.get("plan_skipped"):
        serialized["plan_skipped"] = True
        serialized["plan_skip_kind"] = item.get("plan_skip_kind", "temporary")
        skip_reason = item.get("plan_skip_reason")
        if skip_reason:
            serialized["plan_skip_reason"] = skip_reason

    return serialized


def build_query_payload(
    queue: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    command: str,
    narrative: Mapping[str, Any] | None,
    plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build JSON payload for query.json and non-terminal output modes."""
    serialized = [serialize_item(item) for item in items]
    mode = "execution" if command == "next" else command
    queue_section: dict[str, Any] = {
        "total": queue.get("total", len(items)),
        "mode": mode,
    }

    agent_notes = [
        "Do NOT use `desloppify plan skip` unless the user explicitly asks you to skip an item.",
        "If you cannot fix an item, report it and move to the next one.",
        "For cluster items: if the autofix_hint finds 0 results, drill into individual issues with the primary_command.",
    ]
    if command == "backlog":
        agent_notes = [
            "This is backlog discovery, not the active execution queue.",
            "Use `desloppify next` for the current execution item.",
            "Do NOT treat backlog rank as permission to bypass the living plan.",
        ]

    payload: dict[str, Any] = {
        "command": command,
        "items": serialized,
        "queue": queue_section,
        "narrative": narrative,
        "agent_notes": agent_notes,
    }

    if plan and (
        plan.get("queue_order")
        or plan.get("skipped")
        or plan.get("clusters")
    ):
        clusters_summary = []
        for name, cluster in plan.get("clusters", {}).items():
            member_ids = set(cluster.get("issue_ids", []))
            clusters_summary.append({
                "name": name,
                "description": cluster.get("description"),
                "item_count": len(member_ids),
            })
        payload["plan"] = {
            "active": True,
            "focus": plan.get("active_cluster"),
            "clusters": clusters_summary,
            "total_ordered": len(plan.get("queue_order", [])),
            "total_skipped": len(plan.get("skipped", {})),
            "plan_overrides_narrative": True,
        }

    return payload


def render_markdown(items: Sequence[Mapping[str, Any]]) -> str:
    """Render queue items as markdown."""
    return render_markdown_for_command(items, command="next")


def render_markdown_for_command(
    items: Sequence[Mapping[str, Any]],
    *,
    command: str,
) -> str:
    """Render queue items as markdown for the given queue surface."""
    heading = "# Desloppify Execution Queue"
    if command == "backlog":
        heading = "# Desloppify Backlog"
    lines = [
        heading,
        "",
        "| Kind | Confidence | Summary | Command |",
        "|------|------------|---------|---------|",
    ]
    for item in items:
        kind = item.get("kind", "issue")
        conf = item.get("confidence", "medium")
        summary = item.get("summary", "").replace("|", "\\|")
        command = (item.get("primary_command", "") or "").replace("|", "\\|")
        lines.append(f"| {kind} | {conf} | {summary} | {command} |")
    lines.append("")
    return "\n".join(lines)


def write_output_file(
    output_file: str,
    payload: dict[str, Any],
    item_count: int,
    *,
    safe_write_text_fn,
    colorize_fn,
    label: str = "queue output",
) -> bool:
    """Persist payload to file and print success/failure hints."""
    try:
        safe_write_text_fn(output_file, json.dumps(payload, indent=2) + "\n")
        print(colorize_fn(f"Wrote {item_count} items to {output_file}", "green"))
    except OSError as exc:
        payload["output_error"] = str(exc)
        print_write_error(output_file, exc, label=label)
        return False
    return True


def emit_non_terminal_output(
    output_format: str,
    payload: dict[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    command: str = "next",
) -> bool:
    """Render JSON/markdown output variants."""
    renderers = {
        "json": lambda: print(json.dumps(payload, indent=2)),
        "md": lambda: print(render_markdown_for_command(items, command=command)),
    }
    renderer = renderers.get(output_format)
    if renderer is None:
        return False
    renderer()
    return True


__all__ = [
    "build_query_payload",
    "emit_non_terminal_output",
    "render_markdown",
    "render_markdown_for_command",
    "serialize_item",
    "write_output_file",
]
