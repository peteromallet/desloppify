"""Describe/note/reopen/focus/scan-gate handlers for plan overrides."""

from __future__ import annotations

import argparse
from pathlib import Path

from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.state import require_issue_inventory, state_path
from desloppify.app.commands.plan.shared.patterns import resolve_ids_from_patterns
from .io import (
    _plan_file_for_state,
    save_plan_state_transactional,
)
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import (
    load_plan,
    purge_uncommitted_ids,
    save_plan,
)
from desloppify.engine.plan_ops import (
    annotate_issue,
    append_log_entry,
    clear_focus,
    describe_issue,
    set_focus,
)
from desloppify.app.commands.helpers.transition_messages import emit_transition_message
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_EXECUTE,
    clear_postflight_scan_completion,
)
from desloppify.engine._state.resolution import resolve_issues
from desloppify.state_io import load_state


def cmd_plan_describe(args: argparse.Namespace) -> None:
    """Set augmented description on issues."""
    state = command_runtime(args).state
    if not require_issue_inventory(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    text: str = getattr(args, "text", "")

    plan = load_plan()
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    for fid in issue_ids:
        describe_issue(plan, fid, text or None)
    append_log_entry(plan, "describe", issue_ids=issue_ids, actor="user", detail={"text": text or None})
    save_plan(plan)
    print(colorize(f"  Set description on {len(issue_ids)} issue(s).", "green"))


def cmd_plan_note(args: argparse.Namespace) -> None:
    """Set note on issues."""
    state = command_runtime(args).state
    if not require_issue_inventory(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    text: str | None = getattr(args, "text", None)

    plan = load_plan()
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    for fid in issue_ids:
        annotate_issue(plan, fid, text)
    append_log_entry(plan, "note", issue_ids=issue_ids, actor="user", note=text)
    save_plan(plan)
    print(colorize(f"  Set note on {len(issue_ids)} issue(s).", "green"))


def cmd_plan_reopen(args: argparse.Namespace) -> None:
    """Reopen resolved issues from plan context."""
    patterns: list[str] = getattr(args, "patterns", [])

    raw_state_path = state_path(args)
    state_file = (
        raw_state_path
        if isinstance(raw_state_path, Path)
        else Path(raw_state_path)
        if raw_state_path
        else None
    )
    state_data = load_state(state_file)
    plan_file = _plan_file_for_state(state_file)

    reopened: list[str] = []
    for pattern in patterns:
        reopened.extend(resolve_issues(state_data, pattern, "open"))

    if not reopened:
        print(colorize("  No resolved issues matching: " + " ".join(patterns), "yellow"))
        return

    plan = load_plan(plan_file)
    purge_uncommitted_ids(plan, reopened)

    skipped = plan.get("skipped", {})
    count = 0
    order = set(plan.get("queue_order", []))
    for fid in reopened:
        if fid in skipped:
            skipped.pop(fid)
            count += 1
        if fid not in order:
            plan["queue_order"].append(fid)
            order.add(fid)
            count += 1

    append_log_entry(plan, "reopen", issue_ids=reopened, actor="user")
    transition_phase: str | None = None
    if clear_postflight_scan_completion(plan, issue_ids=reopened, state=state_data):
        transition_phase = LIFECYCLE_PHASE_EXECUTE
    save_plan_state_transactional(
        plan=plan,
        plan_path=plan_file,
        state_data=state_data,
        state_path_value=state_file,
    )

    print(colorize(f"  Reopened {len(reopened)} issue(s).", "green"))
    if count:
        print(colorize("  Plan updated: items moved back to queue.", "dim"))
    if transition_phase:
        emit_transition_message(transition_phase)


def cmd_plan_focus(args: argparse.Namespace) -> None:
    """Set or clear the active cluster focus."""
    clear_flag = getattr(args, "clear", False)
    cluster_name: str | None = getattr(args, "cluster_name", None)

    plan = load_plan()
    if clear_flag:
        prev = plan.get("active_cluster")
        clear_focus(plan)
        append_log_entry(plan, "focus", actor="user", detail={"action": "clear", "previous": prev})
        save_plan(plan)
        print(colorize("  Focus cleared.", "green"))
        return

    if not cluster_name:
        active = plan.get("active_cluster")
        if active:
            print(f"  Focused on: {active}")
        else:
            print("  No active focus.")
        return

    try:
        set_focus(plan, cluster_name)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    append_log_entry(plan, "focus", cluster_name=cluster_name, actor="user", detail={"action": "set"})
    save_plan(plan)
    print(colorize(f"  Focused on: {cluster_name}", "green"))


def cmd_plan_scan_gate(args: argparse.Namespace) -> None:
    """Check or skip the scan requirement for workflow items."""
    skip = getattr(args, "skip", False)
    note: str | None = getattr(args, "note", None)

    plan = load_plan()
    scan_count_at_start = plan.get("scan_count_at_plan_start")

    if scan_count_at_start is None:
        print(colorize("  No active plan cycle (plan_start_scores not seeded).", "dim"))
        print(colorize("  Scan gate is not applicable — workflow items gate themselves.", "dim"))
        return

    resolved_state_path = state_path(args)
    state_data = load_state(resolved_state_path)
    current_scan_count = int(state_data.get("scan_count", 0) or 0)
    scan_ran = current_scan_count > scan_count_at_start
    scan_skipped = plan.get("scan_gate_skipped", False)

    if not skip:
        if scan_ran:
            print(colorize("  Scan gate: PASSED", "green"))
            print(colorize(f"  Scans at cycle start: {scan_count_at_start}  Current: {current_scan_count}", "dim"))
        elif scan_skipped:
            print(colorize("  Scan gate: SKIPPED (manually)", "yellow"))
        else:
            print(colorize("  Scan gate: BLOCKED", "red"))
            print(colorize(f"  Scans at cycle start: {scan_count_at_start}  Current: {current_scan_count}", "dim"))
            print(colorize("  Run: desloppify scan", "dim"))
            print(colorize('  Or:  desloppify plan scan-gate --skip --note "reason"', "dim"))
        return

    if scan_ran:
        print(colorize("  Scan already ran this cycle — no skip needed.", "green"))
        return

    if not note or len(note.strip()) < 50:
        print(colorize("  --skip requires --note with at least 50 chars explaining why.", "red"))
        return

    plan["scan_gate_skipped"] = True
    append_log_entry(
        plan,
        "scan_gate_skip",
        actor="user",
        note=note,
        detail={
            "scan_count_at_start": scan_count_at_start,
            "current_scan_count": current_scan_count,
        },
    )
    save_plan(plan)
    print(colorize("  Scan requirement marked as satisfied (logged).", "yellow"))


__all__ = [
    "cmd_plan_describe",
    "cmd_plan_focus",
    "cmd_plan_note",
    "cmd_plan_reopen",
    "cmd_plan_scan_gate",
]
