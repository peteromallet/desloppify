"""Plan cluster subcommand handlers."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan, state_path as _state_path
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.app.commands.plan.reorder_handlers import resolve_target
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    add_to_cluster,
    append_log_entry,
    create_cluster,
    delete_cluster,
    load_plan,
    merge_clusters,
    move_items,
    plan_path_for_state,
    remove_from_cluster,
    save_plan,
)
from desloppify.state import utc_now

_LEADING_NUM_RE = re.compile(r'^\d+\.\s*')
_HEX8_RE = re.compile(r'^[0-9a-f]{8}$')


def _plan_file_from_args(args: argparse.Namespace) -> Path | None:
    sp = _state_path(args)
    if sp is None:
        return None
    return plan_path_for_state(sp)


def _suggest_close_matches(state: dict, plan: dict | None, patterns: list[str]) -> None:
    """Print fuzzy match suggestions for patterns that resolved to zero issues."""
    all_ids: list[str] = list(state.get("issues", {}).keys())
    if plan is not None:
        seen_ids: set[str] = set(all_ids)
        for fid in plan.get("queue_order", []):
            if fid not in seen_ids:
                seen_ids.add(fid)
                all_ids.append(fid)
        for cluster in plan.get("clusters", {}).values():
            for fid in cluster.get("issue_ids", []):
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    all_ids.append(fid)

    for pattern in patterns:
        segments = pattern.split("::")
        last_seg = segments[-1]
        suggestions: list[str] = []

        if _HEX8_RE.match(last_seg):
            suggestions = [fid for fid in all_ids if fid.endswith(f"::{last_seg}") or fid == last_seg]
            if suggestions:
                print(colorize(f"  No match for: {pattern!r}", "yellow"))
                print(colorize("  Did you mean:", "dim"))
                for m in suggestions[:3]:
                    print(colorize(f"    {m}", "dim"))
                print(colorize(f"  Tip: match by hash suffix alone: {last_seg}", "dim"))
            continue

        # Try last segment and second-to-last as descriptive name slugs
        slug = segments[-2] if len(segments) >= 2 else ""
        for fid in all_ids:
            if f"::{last_seg}::" in fid or fid.endswith(f"::{last_seg}"):
                suggestions.append(fid)
            elif slug and (f"::{slug}::" in fid or fid.endswith(f"::{slug}")):
                suggestions.append(fid)
        if suggestions:
            print(colorize(f"  No match for: {pattern!r}", "yellow"))
            print(colorize("  Did you mean:", "dim"))
            for m in suggestions[:3]:
                print(colorize(f"    {m}", "dim"))


def _print_pattern_hints() -> None:
    """Print valid pattern format hints after a no-match error.

    Side-effect only: prints help text to stdout when pattern resolution
    returns zero matches, guiding the user toward valid pattern syntax.
    """
    print(colorize("  Valid patterns:", "dim"))
    print(colorize("    f41b3eb7              (8-char hash suffix from dashboard)", "dim"))
    print(colorize("    review::path::name    (ID prefix)", "dim"))
    print(colorize("    review                (all issues from detector)", "dim"))
    print(colorize("    src/foo.py            (all issues in file)", "dim"))
    print(colorize("    timing_attack         (issue name — last ::segment of ID)", "dim"))
    print(colorize("    review::*naming*      (glob pattern)", "dim"))
    print(colorize("    my-cluster            (cluster name — expands to members)", "dim"))


def _cmd_cluster_create(args: argparse.Namespace) -> None:
    name: str = getattr(args, "cluster_name", "")
    description: str | None = getattr(args, "description", None)
    action: str | None = getattr(args, "action", None)
    plan_file = _plan_file_from_args(args)
    plan = load_plan(plan_file)
    try:
        create_cluster(plan, name, description, action=action)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    append_log_entry(
        plan, "cluster_create", cluster_name=name, actor="user",
        detail={"description": description, "action": action},
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Created cluster: {name}", "green"))


def _cmd_cluster_add(args: argparse.Namespace) -> None:
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    cluster_name: str = getattr(args, "cluster_name", "")
    patterns: list[str] = getattr(args, "patterns", [])
    dry_run: bool = getattr(args, "dry_run", False)

    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        _print_pattern_hints()
        _suggest_close_matches(state, plan, patterns)
        return

    if dry_run:
        print(colorize(f"  [dry-run] Would add {len(issue_ids)} item(s) to {cluster_name}:", "cyan"))
        for fid in issue_ids:
            print(colorize(f"    {fid}", "dim"))
        return

    try:
        count = add_to_cluster(plan, cluster_name, issue_ids)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return

    # Check for overlap with other manual clusters
    member_set = set(issue_ids)
    for other_name, other_cluster in plan.get("clusters", {}).items():
        if other_name == cluster_name or other_cluster.get("auto"):
            continue
        other_ids = set(other_cluster.get("issue_ids", []))
        if not other_ids:
            continue
        overlap = member_set & other_ids
        if len(overlap) > len(other_ids) * 0.5:
            print(colorize(
                f"  Warning: {len(overlap)} issue(s) also in cluster '{other_name}' "
                f"({len(overlap)}/{len(other_ids)} = {int(len(overlap)/len(other_ids)*100)}% overlap).",
                "yellow",
            ))

    append_log_entry(
        plan, "cluster_add", issue_ids=issue_ids, cluster_name=cluster_name, actor="user",
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Added {count} item(s) to cluster {cluster_name}.", "green"))


def _cmd_cluster_remove(args: argparse.Namespace) -> None:
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    cluster_name: str = getattr(args, "cluster_name", "")
    patterns: list[str] = getattr(args, "patterns", [])
    dry_run: bool = getattr(args, "dry_run", False)

    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        _print_pattern_hints()
        _suggest_close_matches(state, plan, patterns)
        return

    if dry_run:
        print(colorize(f"  [dry-run] Would remove {len(issue_ids)} item(s) from {cluster_name}:", "cyan"))
        for fid in issue_ids:
            print(colorize(f"    {fid}", "dim"))
        return

    try:
        count = remove_from_cluster(plan, cluster_name, issue_ids)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    append_log_entry(
        plan, "cluster_remove", issue_ids=issue_ids, cluster_name=cluster_name, actor="user",
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Removed {count} item(s) from cluster {cluster_name}.", "green"))


def _cmd_cluster_delete(args: argparse.Namespace) -> None:
    cluster_name: str = getattr(args, "cluster_name", "")
    plan_file = _plan_file_from_args(args)
    plan = load_plan(plan_file)
    try:
        orphaned = delete_cluster(plan, cluster_name)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    append_log_entry(
        plan, "cluster_delete", issue_ids=orphaned, cluster_name=cluster_name, actor="user",
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Deleted cluster {cluster_name} ({len(orphaned)} items orphaned).", "green"))


def _resolve_item_position(
    position: str,
    target: str | None,
    item_ids: list[str],
    ordered_slice: list[str],
    cluster_member_set: set[str],
    cluster_name: str,
    state: dict,
    plan: dict,
) -> tuple[str, str | None, int | None] | None:
    """Resolve where items should be positioned within a cluster.

    Returns (resolved_position, resolved_target, offset) on success,
    or None if an error was printed and the caller should abort.
    """
    item_set = set(item_ids)

    if position == "top":
        first_non_item = next((fid for fid in ordered_slice if fid not in item_set), None)
        if first_non_item is None or set(ordered_slice[:len(item_ids)]) == item_set:
            print(colorize("  Already at the top of the cluster.", "yellow"))
            return None
        return ("before", first_non_item, None)

    if position == "bottom":
        last_non_item = next((fid for fid in reversed(ordered_slice) if fid not in item_set), None)
        if last_non_item is None or set(ordered_slice[-len(item_ids):]) == item_set:
            print(colorize("  Already at the bottom of the cluster.", "yellow"))
            return None
        return ("after", last_non_item, None)

    if position in ("before", "after"):
        if target is None:
            print(colorize(f"  '{position}' requires a target. Example: --item PAT {position} TARGET", "red"))
            return None
        target_ids = resolve_ids_from_patterns(state, [target], plan=plan)
        if not target_ids:
            print(colorize(f"  No match for target {target!r}.", "yellow"))
            return None
        resolved_target = target_ids[0]
        if resolved_target not in cluster_member_set:
            print(colorize(f"  Target {resolved_target!r} is not in cluster {cluster_name!r}.", "red"))
            return None
        return (position, resolved_target, None)

    if position in ("up", "down"):
        if target is None:
            print(colorize(f"  '{position}' requires an offset. Example: --item PAT {position} 3", "red"))
            return None
        try:
            offset = int(target)
        except (ValueError, TypeError):
            print(colorize(f"  Invalid offset: {target}", "red"))
            return None
        return (position, None, offset)

    return (position, None, None)


def _reorder_within_cluster(
    args: argparse.Namespace,
    plan: dict,
    clusters: dict,
    cluster_names: list[str],
    position: str,
    target: str | None,
    item_pattern: str,
    plan_file: Path | None = None,
) -> None:
    """Reorder items within a single cluster."""
    if len(cluster_names) != 1:
        print(colorize("  --item requires exactly one cluster name.", "red"))
        return
    cluster_name = cluster_names[0]
    cluster_member_set = set(clusters[cluster_name].get("issue_ids", []))

    state = command_runtime(args).state
    item_ids = resolve_ids_from_patterns(state, [item_pattern], plan=plan)
    if not item_ids:
        print(colorize("  No matching issues found for --item pattern.", "yellow"))
        return
    for fid in item_ids:
        if fid not in cluster_member_set:
            print(colorize(f"  {fid!r} is not a member of cluster {cluster_name!r}.", "red"))
            return

    queue_order: list[str] = plan.get("queue_order", [])
    ordered_slice = [fid for fid in queue_order if fid in cluster_member_set]

    result = _resolve_item_position(
        position, target, item_ids, ordered_slice,
        cluster_member_set, cluster_name, state, plan,
    )
    if result is None:
        return
    resolved_position, resolved_target, offset = result

    count = move_items(plan, item_ids, resolved_position, target=resolved_target, offset=offset)
    append_log_entry(
        plan, "cluster_reorder", cluster_name=cluster_name, actor="user",
        detail={"position": resolved_position, "count": count, "item": item_pattern},
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Moved {count} item(s) to {resolved_position} within cluster {cluster_name}.", "green"))


def _reorder_whole_clusters(
    plan: dict,
    clusters: dict,
    cluster_names: list[str],
    position: str,
    target: str | None,
    plan_file: Path | None = None,
) -> None:
    """Reorder entire clusters as blocks relative to each other."""
    target = resolve_target(plan, target, position)

    offset = None
    if position in ("up", "down") and target is not None:
        try:
            offset = int(target)
        except (ValueError, TypeError):
            print(colorize(f"  Invalid offset: {target}", "red"))
            return
        target = None

    seen: set[str] = set()
    all_member_ids: list[str] = []
    for name in cluster_names:
        for fid in clusters[name].get("issue_ids", []):
            if fid not in seen:
                seen.add(fid)
                all_member_ids.append(fid)

    if not all_member_ids:
        print(colorize("  No members in the specified cluster(s).", "yellow"))
        return

    count = move_items(plan, all_member_ids, position, target=target, offset=offset)
    append_log_entry(
        plan, "cluster_reorder", cluster_name=",".join(cluster_names), actor="user",
        detail={"position": position, "count": count},
    )
    save_plan(plan, plan_file)
    label = ", ".join(cluster_names)
    print(colorize(f"  Moved cluster(s) {label} ({count} items) to {position}.", "green"))


def _cmd_cluster_reorder(args: argparse.Namespace) -> None:
    raw_names: str = getattr(args, "cluster_names", "") or getattr(args, "cluster_name", "")
    cluster_names: list[str] = [n.strip() for n in raw_names.split(",") if n.strip()]
    position: str = getattr(args, "position", "top")
    target: str | None = getattr(args, "target", None)
    item_pattern: str | None = getattr(args, "item_pattern", None)

    plan_file = _plan_file_from_args(args)
    plan = load_plan(plan_file)
    clusters = plan.get("clusters", {})

    # Validate all names exist
    for name in cluster_names:
        if name not in clusters:
            print(colorize(f"  Cluster {name!r} does not exist.", "red"))
            return

    if item_pattern is not None:
        _reorder_within_cluster(args, plan, clusters, cluster_names, position, target, item_pattern, plan_file)
    else:
        _reorder_whole_clusters(plan, clusters, cluster_names, position, target, plan_file)


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
    plan = load_plan(_plan_file_from_args(args))
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
    steps = cluster.get("action_steps") or []
    if steps:
        print(colorize(f"  Steps ({len(steps)}):", "dim"))
        for i, step in enumerate(steps, 1):
            print(colorize(f"    {i}. {step}", "dim"))

    # Members
    issue_ids = cluster.get("issue_ids", [])
    if not issue_ids:
        print(colorize("  Members: (none)", "dim"))
    else:
        issues = _load_issues_best_effort(args)
        print(colorize(f"  Members ({len(issue_ids)}):", "dim"))
        for idx, fid in enumerate(issue_ids, 1):
            _print_cluster_member(idx, fid, issues.get(fid))

    # Commands
    print()
    print(colorize("  Commands:", "dim"))
    print(colorize(f'    Resolve all:  desloppify plan resolve "{cluster_name}" --note "<what>" --attest "..."', "dim"))
    print(colorize(f"    Drill in:     desloppify next --cluster {cluster_name} --count 10", "dim"))
    print(colorize(f"    Skip:         desloppify plan skip {cluster_name}", "dim"))


def _sorted_clusters_by_queue_pos(
    clusters: dict, queue_order: list[str],
) -> tuple[list[tuple[str, dict]], dict[str, int]]:
    """Sort clusters by their earliest member's position in the queue.

    Returns (sorted_cluster_pairs, min_pos_cache) where min_pos_cache maps
    cluster name to its earliest queue position (999_999 if no members queued).
    """
    pos_map = {fid: i for i, fid in enumerate(queue_order)}

    def _min_pos(cluster_data: dict) -> int:
        positions = [pos_map[fid] for fid in cluster_data.get("issue_ids", []) if fid in pos_map]
        return min(positions) if positions else 999_999

    min_pos_cache = {name: _min_pos(c) for name, c in clusters.items()}
    sorted_clusters = sorted(clusters.items(), key=lambda kv: min_pos_cache[kv[0]])
    return sorted_clusters, min_pos_cache


def _print_cluster_list_verbose(
    sorted_clusters: list[tuple[str, dict]],
    min_pos_cache: dict[str, int],
    active: str | None,
) -> None:
    """Print the verbose table view of the cluster list."""
    name_width = max(20, min(35, max(len(n) for n, _ in sorted_clusters)))
    total = len(sorted_clusters)
    print(colorize(f"  Clusters ({total} total, sorted by queue position):", "bold"))
    print()
    header = f"  {'#pos':<5}  {'Name':<{name_width}}  {'Items':>5}  {'Steps':>5}  {'Type':<6}  Description"
    sep = f"  {'─'*4}  {'─'*name_width}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*45}"
    print(colorize(header, "dim"))
    print(colorize(sep, "dim"))
    for name, cluster in sorted_clusters:
        min_p = min_pos_cache[name]
        pos_str = f"#{min_p}" if min_p < 999_999 else "—"
        member_count = len(cluster.get("issue_ids", []))
        steps = cluster.get("action_steps") or []
        steps_str = str(len(steps)) if steps else "—"
        type_str = "auto" if cluster.get("auto") else "manual"
        desc = cluster.get("description") or ""
        if not desc and min_p == 999_999 and not member_count:
            desc = "(no queue position — no members)"
        desc_truncated = (desc[:44] + "…") if len(desc) > 45 else desc
        name_display = (name[:name_width - 1] + "…") if len(name) > name_width else name
        focused = " *" if name == active else ""
        print(f"  {pos_str:>5}  {name_display:<{name_width}}  {member_count:>5}  {steps_str:>5}  {type_str:<6}  {desc_truncated}{focused}")
    print()


def _cmd_cluster_list(args: argparse.Namespace) -> None:
    plan = load_plan(_plan_file_from_args(args))
    clusters = plan.get("clusters", {})
    active = plan.get("active_cluster")
    verbose: bool = getattr(args, "verbose", False)

    if not clusters:
        print("  No clusters defined.")
        return

    queue_order: list[str] = plan.get("queue_order", [])
    sorted_clusters, min_pos_cache = _sorted_clusters_by_queue_pos(clusters, queue_order)

    if verbose:
        _print_cluster_list_verbose(sorted_clusters, min_pos_cache, active)
        return

    print(colorize("  Clusters (ordered by queue position):", "bold"))
    for name, cluster in sorted_clusters:
        min_p = min_pos_cache[name]
        pos_str = f"#{min_p}" if min_p < 999_999 else "—"
        member_count = len(cluster.get("issue_ids", []))
        desc = cluster.get("description") or ""
        marker = " (focused)" if name == active else ""
        desc_str = f" — {desc}" if desc else ""
        auto_tag = " [auto]" if cluster.get("auto") else ""
        print(f"    {pos_str:>5}  {name}: {member_count} items{auto_tag}{desc_str}{marker}")


def _cmd_cluster_update(args: argparse.Namespace) -> None:
    """Update cluster description and/or action_steps."""
    cluster_name: str = getattr(args, "cluster_name", "")
    description: str | None = getattr(args, "description", None)
    steps: list[str] | None = getattr(args, "steps", None)

    if description is None and steps is None:
        print(colorize("  Nothing to update. Use --description and/or --steps.", "yellow"))
        return

    plan_file = _plan_file_from_args(args)
    plan = load_plan(plan_file)
    cluster = plan.get("clusters", {}).get(cluster_name)
    if cluster is None:
        print(colorize(f"  Cluster {cluster_name!r} does not exist.", "red"))
        return

    if description is not None:
        cluster["description"] = description
    if steps is not None:
        cluster["action_steps"] = list(steps)
        print(colorize(f"  Stored {len(steps)} action step(s):", "dim"))
        for i, step in enumerate(steps, 1):
            clean = _LEADING_NUM_RE.sub('', step)
            print(colorize(f"    {i}. {clean}", "dim"))
        if len(steps) == 0:
            print(colorize("  Warning: 0 steps stored. Did you forget the --steps values?", "yellow"))
        elif len(steps) == 1 and len(steps[0]) > 100:
            print(colorize("  Warning: only 1 step stored and it's quite long. Check shell quoting.", "yellow"))
    cluster["user_modified"] = True
    cluster["updated_at"] = utc_now()
    append_log_entry(
        plan, "cluster_update", cluster_name=cluster_name, actor="user",
        detail={"description": description, "steps": steps},
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Updated cluster: {cluster_name}", "green"))


def _cmd_cluster_merge(args: argparse.Namespace) -> None:
    """Merge source cluster into target cluster."""
    source: str = getattr(args, "source", "")
    target: str = getattr(args, "target", "")

    plan_file = _plan_file_from_args(args)
    plan = load_plan(plan_file)
    try:
        added, source_ids = merge_clusters(plan, source, target)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return

    append_log_entry(
        plan, "cluster_merge", issue_ids=source_ids,
        cluster_name=target, actor="user",
        detail={"source": source, "added": added},
    )
    save_plan(plan, plan_file)
    print(colorize(
        f"  Merged cluster {source!r} into {target!r}: "
        f"{added} issue(s) added, {len(source_ids)} total moved. Source deleted.",
        "green",
    ))


def cmd_cluster_dispatch(args: argparse.Namespace) -> None:
    """Route cluster subcommands."""
    cluster_action = getattr(args, "cluster_action", None)
    dispatch = {
        "create": _cmd_cluster_create,
        "add": _cmd_cluster_add,
        "remove": _cmd_cluster_remove,
        "delete": _cmd_cluster_delete,
        "reorder": _cmd_cluster_reorder,
        "show": _cmd_cluster_show,
        "list": _cmd_cluster_list,
        "update": _cmd_cluster_update,
        "merge": _cmd_cluster_merge,
    }
    handler = dispatch.get(cluster_action)
    if handler is None:
        _cmd_cluster_list(args)
        return
    handler(args)


__all__ = ["cmd_cluster_dispatch"]
