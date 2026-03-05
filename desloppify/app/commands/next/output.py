"""Output helpers for the `next` command."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from desloppify.base.output.fallbacks import print_write_error

_CLUSTER_MEMBER_SAMPLE_LIMIT = 25


def _serialize_cluster_member(member: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a cluster member without nested plan metadata."""
    return {
        "id": member.get("id"),
        "kind": member.get("kind", "issue"),
        "confidence": member.get("confidence"),
        "detector": member.get("detector"),
        "file": member.get("file"),
        "summary": member.get("summary"),
        "status": member.get("status"),
        "primary_command": member.get("primary_command"),
    }


def serialize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Build a serializable output dict from a queue item."""
    # Cluster meta-items get their own serialization
    if item.get("kind") == "cluster":
        members_raw = item.get("members", [])
        serialized_members = [
            _serialize_cluster_member(member)
            for member in members_raw[:_CLUSTER_MEMBER_SAMPLE_LIMIT]
        ]
        member_count = int(item.get("member_count", len(members_raw)))
        serialized_cluster: dict[str, Any] = {
            "id": item.get("id"),
            "kind": "cluster",
            "action_type": item.get("action_type", "manual_fix"),
            "summary": item.get("summary"),
            "member_count": member_count,
            "members": serialized_members,
            "cluster_name": item.get("cluster_name", item.get("id")),
            "cluster_auto": item.get("cluster_auto", True),
            "detector": item.get("detector"),
        }
        if member_count > len(serialized_members):
            serialized_cluster["members_truncated"] = True
            serialized_cluster["members_sample_limit"] = _CLUSTER_MEMBER_SAMPLE_LIMIT
        serialized_cluster["primary_command"] = item.get("primary_command")
        action_steps = item.get("action_steps") or []
        if action_steps:
            serialized_cluster["action_steps"] = action_steps
        return serialized_cluster

    serialized: dict[str, Any] = {
        "id": item.get("id"),
        "kind": item.get("kind", "issue"),
        "confidence": item.get("confidence"),
        "detector": item.get("detector"),
        "file": item.get("file"),
        "summary": item.get("summary"),
        "detail": item.get("detail", {}),
        "status": item.get("status"),
    }
    serialized["primary_command"] = item.get("primary_command")

    # Workflow dependency state
    if item.get("blocked_by"):
        serialized["blocked_by"] = item["blocked_by"]
    if item.get("is_blocked"):
        serialized["is_blocked"] = True

    explain = item.get("explain")
    if explain is not None:
        serialized["explain"] = explain

    # Plan metadata
    if item.get("queue_position"):
        serialized["queue_position"] = item["queue_position"]
    if item.get("plan_description"):
        serialized["plan_description"] = item["plan_description"]
    if item.get("plan_note"):
        serialized["plan_note"] = item["plan_note"]
    if item.get("plan_cluster"):
        serialized["plan_cluster"] = item["plan_cluster"]
    if item.get("plan_skipped"):
        serialized["plan_skipped"] = True
        serialized["plan_skip_kind"] = item.get("plan_skip_kind", "temporary")
        if item.get("plan_skip_reason"):
            serialized["plan_skip_reason"] = item["plan_skip_reason"]

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
    queue_section: dict[str, Any] = {
        "total": queue.get("total", len(items)),
    }

    payload: dict[str, Any] = {
        "command": command,
        "items": serialized,
        "queue": queue_section,
        "narrative": narrative,
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
    lines = [
        "# Desloppify Next Queue",
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
) -> bool:
    """Persist payload to file and print success/failure hints."""
    try:
        safe_write_text_fn(output_file, json.dumps(payload, indent=2) + "\n")
        print(colorize_fn(f"Wrote {item_count} items to {output_file}", "green"))
    except OSError as exc:
        payload["output_error"] = str(exc)
        print_write_error(output_file, exc, label="next output")
        return False
    return True


def emit_non_terminal_output(
    output_format: str,
    payload: dict[str, Any],
    items: Sequence[Mapping[str, Any]],
) -> bool:
    """Render JSON/markdown output variants."""
    renderers = {
        "json": lambda: print(json.dumps(payload, indent=2)),
        "md": lambda: print(render_markdown(items)),
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
    "serialize_item",
    "write_output_file",
]
