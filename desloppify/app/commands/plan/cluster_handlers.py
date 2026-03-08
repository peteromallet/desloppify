"""Plan cluster subcommand handlers."""

from __future__ import annotations

import argparse
import re

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    add_to_cluster,
    append_log_entry,
    load_plan,
    normalize_step,
    parse_steps_file,
    plan_lock,
    remove_from_cluster,
    save_plan,
    step_summary,
)
from desloppify.state import utc_now

from .cluster_ops import _cmd_cluster_create
from .cluster_ops import _cmd_cluster_delete
from .cluster_ops import _cmd_cluster_export
from .cluster_ops import _cmd_cluster_import
from .cluster_ops import _cmd_cluster_list
from .cluster_ops import _cmd_cluster_merge
from .cluster_ops import _cmd_cluster_reorder
from .cluster_ops import _cmd_cluster_show
from .cluster_update import cmd_cluster_update as _cmd_cluster_update_impl

_HEX8_RE = re.compile(r"^[0-9a-f]{8}$")


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
                for match in suggestions[:3]:
                    print(colorize(f"    {match}", "dim"))
                print(colorize(f"  Tip: match by hash suffix alone: {last_seg}", "dim"))
            continue

        slug = segments[-2] if len(segments) >= 2 else ""
        for fid in all_ids:
            if f"::{last_seg}::" in fid or fid.endswith(f"::{last_seg}"):
                suggestions.append(fid)
            elif slug and (f"::{slug}::" in fid or fid.endswith(f"::{slug}")):
                suggestions.append(fid)
        if suggestions:
            print(colorize(f"  No match for: {pattern!r}", "yellow"))
            print(colorize("  Did you mean:", "dim"))
            for match in suggestions[:3]:
                print(colorize(f"    {match}", "dim"))


def _print_pattern_hints() -> None:
    """Print valid pattern format hints after a no-match error."""
    print(colorize("  Valid patterns:", "dim"))
    print(colorize("    f41b3eb7              (8-char hash suffix from dashboard)", "dim"))
    print(colorize("    review::path::name    (ID prefix)", "dim"))
    print(colorize("    review                (all issues from detector)", "dim"))
    print(colorize("    src/foo.py            (all issues in file)", "dim"))
    print(colorize("    timing_attack         (issue name — last ::segment of ID)", "dim"))
    print(colorize("    review::*naming*      (glob pattern)", "dim"))
    print(colorize("    my-cluster            (cluster name — expands to members)", "dim"))


def _cmd_cluster_add(args: argparse.Namespace) -> None:
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    cluster_name: str = getattr(args, "cluster_name", "")
    patterns: list[str] = getattr(args, "patterns", [])
    dry_run: bool = getattr(args, "dry_run", False)

    plan = load_plan()
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

    member_set = set(issue_ids)
    for other_name, other_cluster in plan.get("clusters", {}).items():
        if other_name == cluster_name or other_cluster.get("auto"):
            continue
        other_ids = set(other_cluster.get("issue_ids", []))
        if not other_ids:
            continue
        overlap = member_set & other_ids
        if len(overlap) > len(other_ids) * 0.5:
            percent = int(len(overlap) / len(other_ids) * 100)
            print(
                colorize(
                    f"  Warning: {len(overlap)} issue(s) also in cluster '{other_name}' "
                    f"({len(overlap)}/{len(other_ids)} = {percent}% overlap).",
                    "yellow",
                )
            )

    append_log_entry(plan, "cluster_add", issue_ids=issue_ids, cluster_name=cluster_name, actor="user")
    save_plan(plan)
    print(colorize(f"  Added {count} item(s) to cluster {cluster_name}.", "green"))


def _cmd_cluster_remove(args: argparse.Namespace) -> None:
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    cluster_name: str = getattr(args, "cluster_name", "")
    patterns: list[str] = getattr(args, "patterns", [])
    dry_run: bool = getattr(args, "dry_run", False)

    plan = load_plan()
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

    append_log_entry(plan, "cluster_remove", issue_ids=issue_ids, cluster_name=cluster_name, actor="user")
    save_plan(plan)
    print(colorize(f"  Removed {count} item(s) from cluster {cluster_name}.", "green"))


def _cmd_cluster_update(args: argparse.Namespace) -> None:
    """Update cluster description, steps, and/or priority."""
    _cmd_cluster_update_impl(
        args,
        load_plan_fn=load_plan,
        save_plan_fn=save_plan,
        append_log_entry_fn=append_log_entry,
        plan_lock_fn=plan_lock,
        parse_steps_file_fn=parse_steps_file,
        normalize_step_fn=normalize_step,
        step_summary_fn=step_summary,
        utc_now_fn=utc_now,
        colorize_fn=colorize,
    )


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
        "export": _cmd_cluster_export,
        "import": _cmd_cluster_import,
    }
    handler = dispatch.get(cluster_action)
    if handler is None:
        _cmd_cluster_list(args)
        return
    handler(args)


__all__ = ["_cmd_cluster_add", "_cmd_cluster_remove", "_cmd_cluster_update", "cmd_cluster_dispatch"]
