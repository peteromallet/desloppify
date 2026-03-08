"""Cluster show/list display handlers."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import load_plan

from .cluster_steps import print_step


def _print_cluster_member(idx: int, fid: str, issue: dict | None) -> None:
    """Print a single cluster member line with optional issue details."""
    print(f"    {idx}. {fid}")
    if not issue:
        return
    file = issue.get("file", "")
    lines = issue.get("detail", {}).get("lines", [])
    line_str = f" at lines: {', '.join(str(ln) for ln in lines)}" if lines else ""
    if file:
        print(colorize(f"       File: {file}{line_str}", "dim"))
    summary = issue.get("summary", "")
    if summary:
        print(colorize(f"       {summary}", "dim"))


def _load_issues_best_effort(args: argparse.Namespace) -> dict:
    """Load issues from state, returning empty dict on failure."""
    rt = command_runtime(args)
    return rt.state.get("issues", {})


def _cmd_cluster_show(args: argparse.Namespace) -> None:
    cluster_name: str = getattr(args, "cluster_name", "")
    plan = load_plan()
    cluster = plan.get("clusters", {}).get(cluster_name)
    if cluster is None:
        print(colorize(f"  Cluster {cluster_name!r} does not exist.", "red"))
        return

    auto_tag = "Auto-generated" if cluster.get("auto") else "Manual"
    cluster_key = cluster.get("cluster_key", "")
    key_type = f" ({cluster_key.split('::', 1)[0]})" if cluster_key else ""
    print(colorize(f"  Cluster: {cluster_name}", "bold"))
    print(colorize(f"  Type: {auto_tag}{key_type}", "dim"))
    priority = cluster.get("priority")
    if priority is not None:
        print(colorize(f"  Priority: {priority}", "dim"))
    dep_order = cluster.get("dependency_order")
    if dep_order is not None:
        print(colorize(f"  Dependency order: {dep_order}", "dim"))
    desc = cluster.get("description") or ""
    if desc:
        print(colorize(f"  Description: {desc}", "dim"))
    action = cluster.get("action") or ""
    if action:
        print(colorize(f"  Action: {action}", "dim"))

    steps = cluster.get("action_steps") or []
    if steps:
        done_count = sum(1 for s in steps if isinstance(s, dict) and s.get("done", False))
        print()
        suffix = f" — {done_count}/{len(steps)} done" if done_count else ""
        print(colorize(f"  Steps ({len(steps)}){suffix}:", "dim"))
        for i, step in enumerate(steps, 1):
            print_step(i, step, colorize_fn=colorize)

    issue_ids = cluster.get("issue_ids", [])
    print()
    if not issue_ids:
        print(colorize("  Members: (none)", "dim"))
    else:
        issues = _load_issues_best_effort(args)
        print(colorize(f"  Members ({len(issue_ids)}):", "dim"))
        for idx, fid in enumerate(issue_ids, 1):
            _print_cluster_member(idx, fid, issues.get(fid))

    print()
    print(colorize("  Commands:", "dim"))
    print(colorize(f'    Resolve all:  desloppify plan resolve "{cluster_name}" --note "<what>" --attest "..."', "dim"))
    print(colorize(f"    Drill in:     desloppify next --cluster {cluster_name} --count 10", "dim"))
    print(colorize(f"    Skip:         desloppify plan skip {cluster_name}", "dim"))


def _sorted_clusters_by_queue_pos(
    clusters: dict,
    queue_order: list[str],
) -> tuple[list[tuple[str, dict]], dict[str, int]]:
    """Sort clusters by (priority, earliest queue position)."""
    pos_map = {fid: i for i, fid in enumerate(queue_order)}

    def _min_pos(cluster_data: dict) -> int:
        positions = [pos_map[fid] for fid in cluster_data.get("issue_ids", []) if fid in pos_map]
        return min(positions) if positions else 999_999

    min_pos_cache = {name: _min_pos(c) for name, c in clusters.items()}
    sorted_clusters = sorted(
        clusters.items(),
        key=lambda kv: (kv[1].get("priority", 999), min_pos_cache[kv[0]]),
    )
    return sorted_clusters, min_pos_cache


def _print_cluster_list_verbose(
    sorted_clusters: list[tuple[str, dict]],
    min_pos_cache: dict[str, int],
    active: str | None,
) -> None:
    """Print the verbose table view of the cluster list."""
    name_width = max(20, min(35, max(len(n) for n, _ in sorted_clusters)))
    total = len(sorted_clusters)
    has_dep = any(c.get("dependency_order") is not None for _, c in sorted_clusters)
    print(colorize(f"  Clusters ({total} total, sorted by priority/queue position):", "bold"))
    print()
    dep_header = f"  {'Dep':>3}" if has_dep else ""
    header = f"  {'#pos':<5}  {'Pri':>3}{dep_header}  {'Name':<{name_width}}  {'Items':>5}  {'Steps':>5}  {'Type':<6}  Description"
    dep_sep = f"  {'─'*3}" if has_dep else ""
    sep = f"  {'─'*4}  {'─'*3}{dep_sep}  {'─'*name_width}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*40}"
    print(colorize(header, "dim"))
    print(colorize(sep, "dim"))
    for name, cluster in sorted_clusters:
        min_p = min_pos_cache[name]
        pos_str = f"#{min_p}" if min_p < 999_999 else "—"
        priority = cluster.get("priority")
        pri_str = str(priority) if priority is not None else "—"
        dep_order = cluster.get("dependency_order")
        dep_str = f"  {dep_order:>3}" if has_dep and dep_order is not None else ("  {:>3}".format("—") if has_dep else "")
        member_count = len(cluster.get("issue_ids", []))
        steps = cluster.get("action_steps") or []
        steps_str = str(len(steps)) if steps else "—"
        type_str = "auto" if cluster.get("auto") else "manual"
        desc = cluster.get("description") or ""
        if not desc and min_p == 999_999 and not member_count:
            desc = "(no queue position — no members)"
        desc_truncated = (desc[:39] + "…") if len(desc) > 40 else desc
        name_display = (name[: name_width - 1] + "…") if len(name) > name_width else name
        focused = " *" if name == active else ""
        print(f"  {pos_str:>5}  {pri_str:>3}{dep_str}  {name_display:<{name_width}}  {member_count:>5}  {steps_str:>5}  {type_str:<6}  {desc_truncated}{focused}")
    print()


def _cmd_cluster_list(args: argparse.Namespace) -> None:
    plan = load_plan()
    clusters = plan.get("clusters", {})
    active = plan.get("active_cluster")
    verbose: bool = getattr(args, "verbose", False)
    missing_steps: bool = getattr(args, "missing_steps", False)

    if not clusters:
        print("  No clusters defined.")
        return

    queue_order: list[str] = plan.get("queue_order", [])
    sorted_clusters, min_pos_cache = _sorted_clusters_by_queue_pos(clusters, queue_order)

    if missing_steps:
        from desloppify.app.commands.plan.triage.stage_helpers import unenriched_clusters

        gaps = unenriched_clusters(plan)
        if not gaps:
            print(colorize("  All clusters have action steps.", "green"))
            return
        print(colorize(f"  {len(gaps)} cluster(s) need action steps:", "bold"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print()
        print(colorize("  Fix with:", "dim"))
        print(colorize('    desloppify plan cluster update <name> --description "..." --steps "step1" "step2"', "dim"))
        print(colorize('    desloppify plan cluster update <name> --add-step "step title" --detail "sub-details"', "dim"))
        return

    if verbose:
        _print_cluster_list_verbose(sorted_clusters, min_pos_cache, active)
        return

    print(colorize("  Clusters (ordered by priority/queue position):", "bold"))
    for name, cluster in sorted_clusters:
        min_p = min_pos_cache[name]
        pos_str = f"#{min_p}" if min_p < 999_999 else "—"
        priority = cluster.get("priority")
        pri_tag = f" [P{priority}]" if priority is not None else ""
        member_count = len(cluster.get("issue_ids", []))
        desc = cluster.get("description") or ""
        marker = " (focused)" if name == active else ""
        desc_str = f" — {desc}" if desc else ""
        auto_tag = " [auto]" if cluster.get("auto") else ""
        print(f"    {pos_str:>5} {pri_tag} {name}: {member_count} items{auto_tag}{desc_str}{marker}")


__all__ = ["_cmd_cluster_list", "_cmd_cluster_show"]
