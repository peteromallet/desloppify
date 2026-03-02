"""Plan cluster subcommand handlers."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.core.output_api import colorize
from desloppify.engine.plan import (
    add_to_cluster,
    create_cluster,
    delete_cluster,
    load_plan,
    move_cluster,
    remove_from_cluster,
    save_plan,
)


def _cmd_cluster_create(args: argparse.Namespace) -> None:
    name: str = getattr(args, "cluster_name", "")
    description: str | None = getattr(args, "description", None)
    action: str | None = getattr(args, "action", None)
    plan = load_plan()
    try:
        create_cluster(plan, name, description, action=action)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    save_plan(plan)
    print(colorize(f"  Created cluster: {name}", "green"))


def _cmd_cluster_add(args: argparse.Namespace) -> None:
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    cluster_name: str = getattr(args, "cluster_name", "")
    patterns: list[str] = getattr(args, "patterns", [])

    plan = load_plan()
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return
    try:
        count = add_to_cluster(plan, cluster_name, finding_ids)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    save_plan(plan)
    print(colorize(f"  Added {count} item(s) to cluster {cluster_name}.", "green"))


def _cmd_cluster_remove(args: argparse.Namespace) -> None:
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    cluster_name: str = getattr(args, "cluster_name", "")
    patterns: list[str] = getattr(args, "patterns", [])

    plan = load_plan()
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return
    try:
        count = remove_from_cluster(plan, cluster_name, finding_ids)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    save_plan(plan)
    print(colorize(f"  Removed {count} item(s) from cluster {cluster_name}.", "green"))


def _cmd_cluster_delete(args: argparse.Namespace) -> None:
    cluster_name: str = getattr(args, "cluster_name", "")
    plan = load_plan()
    try:
        orphaned = delete_cluster(plan, cluster_name)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    save_plan(plan)
    print(colorize(f"  Deleted cluster {cluster_name} ({len(orphaned)} items orphaned).", "green"))


def _cmd_cluster_move(args: argparse.Namespace) -> None:
    cluster_name: str = getattr(args, "cluster_name", "")
    position: str = getattr(args, "position", "top")
    target: str | None = getattr(args, "target", None)

    plan = load_plan()

    offset: int | None = None
    if position in ("up", "down") and target is not None:
        try:
            offset = int(target)
        except (ValueError, TypeError):
            print(colorize(f"  Invalid offset: {target}", "red"))
            return
        target = None

    try:
        count = move_cluster(plan, cluster_name, position, target=target, offset=offset)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    save_plan(plan)
    print(colorize(f"  Moved cluster {cluster_name} ({count} items) to {position}.", "green"))


def _print_cluster_member(idx: int, fid: str, finding: dict | None) -> None:
    """Print a single cluster member line with optional finding details."""
    print(f"    {idx}. {fid}")
    if not finding:
        return
    file = finding.get("file", "")
    lines = finding.get("detail", {}).get("lines", [])
    line_str = f" at lines: {', '.join(str(ln) for ln in lines)}" if lines else ""
    if file:
        print(colorize(f"       File: {file}{line_str}", "dim"))
    summary = finding.get("summary", "")
    if summary:
        print(colorize(f"       {summary}", "dim"))


def _load_findings_best_effort(args: argparse.Namespace) -> dict:
    """Load findings from state, returning empty dict on failure."""
    rt = command_runtime(args)
    return rt.state.get("findings", {})


def _cmd_cluster_show(args: argparse.Namespace) -> None:
    cluster_name: str = getattr(args, "cluster_name", "")
    plan = load_plan()
    cluster = plan.get("clusters", {}).get(cluster_name)
    if cluster is None:
        print(colorize(f"  Cluster {cluster_name!r} does not exist.", "red"))
        return

    # Header
    auto_tag = "Auto-generated" if cluster.get("auto") else "Manual"
    cluster_key = cluster.get("cluster_key", "")
    key_type = f" ({cluster_key.split('::', 1)[0]})" if cluster_key else ""
    print(colorize(f"  Cluster: {cluster_name}", "bold"))
    print(colorize(f"  Type: {auto_tag}{key_type}", "dim"))
    desc = cluster.get("description") or ""
    if desc:
        print(colorize(f"  Description: {desc}", "dim"))
    action = cluster.get("action") or ""
    if action:
        print(colorize(f"  Action: {action}", "dim"))

    # Members
    finding_ids = cluster.get("finding_ids", [])
    if not finding_ids:
        print(colorize("  Members: (none)", "dim"))
    else:
        findings = _load_findings_best_effort(args)
        print(colorize(f"  Members ({len(finding_ids)}):", "dim"))
        for idx, fid in enumerate(finding_ids, 1):
            _print_cluster_member(idx, fid, findings.get(fid))

    # Commands
    print()
    print(colorize("  Commands:", "dim"))
    print(colorize(f'    Resolve all:  desloppify plan done "{cluster_name}" --note "<what>" --attest "..."', "dim"))
    print(colorize(f"    Drill in:     desloppify next --cluster {cluster_name} --count 10", "dim"))
    print(colorize(f"    Skip:         desloppify plan skip {cluster_name}", "dim"))


def _cmd_cluster_list(args: argparse.Namespace) -> None:
    plan = load_plan()
    clusters = plan.get("clusters", {})
    active = plan.get("active_cluster")
    if not clusters:
        print("  No clusters defined.")
        return
    print(colorize("  Clusters:", "bold"))
    for name, cluster in clusters.items():
        member_count = len(cluster.get("finding_ids", []))
        desc = cluster.get("description") or ""
        marker = " (focused)" if name == active else ""
        desc_str = f" — {desc}" if desc else ""
        auto_tag = " [auto]" if cluster.get("auto") else ""
        print(f"    {name}: {member_count} items{auto_tag}{desc_str}{marker}")


def _cmd_cluster_update(args: argparse.Namespace) -> None:
    """Update cluster description and/or action_steps."""
    cluster_name: str = getattr(args, "cluster_name", "")
    description: str | None = getattr(args, "description", None)
    steps: list[str] | None = getattr(args, "steps", None)

    if description is None and steps is None:
        print(colorize("  Nothing to update. Use --description and/or --steps.", "yellow"))
        return

    plan = load_plan()
    cluster = plan.get("clusters", {}).get(cluster_name)
    if cluster is None:
        print(colorize(f"  Cluster {cluster_name!r} does not exist.", "red"))
        return

    if description is not None:
        cluster["description"] = description
    if steps is not None:
        cluster["action_steps"] = list(steps)
    cluster["user_modified"] = True

    from desloppify.engine._state.schema import utc_now

    cluster["updated_at"] = utc_now()
    save_plan(plan)
    print(colorize(f"  Updated cluster: {cluster_name}", "green"))


def cmd_cluster_dispatch(args: argparse.Namespace) -> None:
    """Route cluster subcommands."""
    cluster_action = getattr(args, "cluster_action", None)
    dispatch = {
        "create": _cmd_cluster_create,
        "add": _cmd_cluster_add,
        "remove": _cmd_cluster_remove,
        "delete": _cmd_cluster_delete,
        "move": _cmd_cluster_move,
        "show": _cmd_cluster_show,
        "list": _cmd_cluster_list,
        "update": _cmd_cluster_update,
    }
    handler = dispatch.get(cluster_action)
    if handler is None:
        _cmd_cluster_list(args)
        return
    handler(args)


__all__ = ["cmd_cluster_dispatch"]
