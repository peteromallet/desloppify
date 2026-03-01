"""Plan override subcommand handlers: describe, note, skip, unskip, done, reopen, focus."""

from __future__ import annotations

import argparse
import sys

from desloppify import state as state_mod
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan, state_path
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.app.commands.resolve.cmd import cmd_resolve
from desloppify.app.commands.resolve.selection import (
    show_attestation_requirement,
    validate_attestation,
)
from desloppify.core.output_api import colorize
from desloppify.engine.plan import (
    annotate_finding,
    clear_focus,
    describe_finding,
    load_plan,
    save_plan,
    set_focus,
    skip_items,
    unskip_items,
)
from desloppify.engine.work_queue import ATTEST_EXAMPLE


def cmd_plan_describe(args: argparse.Namespace) -> None:
    """Set augmented description on findings."""
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    text: str = getattr(args, "text", "")

    plan = load_plan()
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return

    for fid in finding_ids:
        describe_finding(plan, fid, text or None)
    save_plan(plan)
    print(colorize(f"  Set description on {len(finding_ids)} finding(s).", "green"))


def cmd_plan_note(args: argparse.Namespace) -> None:
    """Set note on findings."""
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    text: str | None = getattr(args, "text", None)

    plan = load_plan()
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return

    for fid in finding_ids:
        annotate_finding(plan, fid, text)
    save_plan(plan)
    print(colorize(f"  Set note on {len(finding_ids)} finding(s).", "green"))


# ---------------------------------------------------------------------------
# Skip / unskip
# ---------------------------------------------------------------------------

def cmd_plan_skip(args: argparse.Namespace) -> None:
    """Skip findings — unified command for temporary/permanent/false-positive."""
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    reason: str | None = getattr(args, "reason", None)
    review_after: int | None = getattr(args, "review_after", None)
    permanent: bool = getattr(args, "permanent", False)
    false_positive: bool = getattr(args, "false_positive", False)
    note: str | None = getattr(args, "note", None)
    attestation: str | None = getattr(args, "attest", None)

    # Determine skip kind
    if false_positive:
        kind = "false_positive"
    elif permanent:
        kind = "permanent"
    else:
        kind = "temporary"

    # Validate requirements for permanent/false_positive
    if kind in ("permanent", "false_positive"):
        if not validate_attestation(attestation):
            show_attestation_requirement(
                "Permanent skip" if kind == "permanent" else "False positive",
                attestation,
                ATTEST_EXAMPLE,
            )
            return
        if kind == "permanent" and not note:
            print(
                colorize("  --permanent requires --note to explain the decision.", "yellow"),
                file=sys.stderr,
            )
            return

    plan = load_plan()
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return

    # For permanent/false_positive: delegate to state layer for score impact
    if kind in ("permanent", "false_positive"):
        state_file = state_path(args)
        state_data = state_mod.load_state(state_file)
        status = "wontfix" if kind == "permanent" else "false_positive"
        resolved: list[str] = []
        for fid in finding_ids:
            resolved.extend(
                state_mod.resolve_findings(
                    state_data, fid, status, note or "", attestation=attestation
                )
            )
        if resolved:
            state_mod.save_state(state_data, state_file)

    scan_count = state.get("scan_count", 0)
    count = skip_items(
        plan,
        finding_ids,
        kind=kind,
        reason=reason,
        note=note,
        attestation=attestation,
        review_after=review_after,
        scan_count=scan_count,
    )
    save_plan(plan)

    label = {"temporary": "Skipped", "permanent": "Wontfixed", "false_positive": "Marked false positive"}
    print(colorize(f"  {label[kind]} {count} item(s).", "green"))
    if review_after:
        print(colorize(f"  Will re-surface after {review_after} scan(s).", "dim"))


def cmd_plan_unskip(args: argparse.Namespace) -> None:
    """Unskip findings — bring back to queue."""
    state = command_runtime(args).state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])

    plan = load_plan()
    # For unskip we need to match against all statuses (skipped items may be wontfix/fp)
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan, status_filter="all")
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return

    count, need_reopen = unskip_items(plan, finding_ids)
    save_plan(plan)

    # Reopen permanent/false_positive items in state
    if need_reopen:
        state_file = state_path(args)
        state_data = state_mod.load_state(state_file)
        reopened: list[str] = []
        for fid in need_reopen:
            reopened.extend(state_mod.resolve_findings(state_data, fid, "open"))
        if reopened:
            state_mod.save_state(state_data, state_file)
        print(colorize(f"  Reopened {len(reopened)} finding(s) in state.", "dim"))

    print(colorize(f"  Unskipped {count} item(s) — back in queue.", "green"))


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------

def cmd_plan_reopen(args: argparse.Namespace) -> None:
    """Reopen resolved findings from plan context."""
    patterns: list[str] = getattr(args, "patterns", [])

    state_file = state_path(args)
    state_data = state_mod.load_state(state_file)

    reopened: list[str] = []
    for pattern in patterns:
        reopened.extend(
            state_mod.resolve_findings(state_data, pattern, "open")
        )

    if not reopened:
        print(colorize("  No resolved findings matching: " + " ".join(patterns), "yellow"))
        return

    state_mod.save_state(state_data, state_file)

    # Remove from skipped if present, and ensure all reopened IDs are in queue
    plan = load_plan()
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
    if count:
        save_plan(plan)

    print(colorize(f"  Reopened {len(reopened)} finding(s).", "green"))
    if count:
        print(colorize(f"  Plan updated: items moved back to queue.", "dim"))


def cmd_plan_done(args: argparse.Namespace) -> None:
    """Mark findings as fixed — delegates to cmd_resolve for rich UX."""
    patterns: list[str] = getattr(args, "patterns", [])
    attestation: str | None = getattr(args, "attest", None)
    note: str | None = getattr(args, "note", None)

    # --confirm: auto-generate attestation from --note
    if getattr(args, "confirm", False):
        if not note:
            print(colorize("  --confirm requires --note to describe what you did.", "red"))
            return
        attestation = f"I have actually {note} and I am not gaming the score."
        args.attest = attestation

    # Pre-validate attestation before delegating (avoids stale hint in resolve)
    if not validate_attestation(attestation):
        show_attestation_requirement("Plan done", attestation, ATTEST_EXAMPLE)
        return

    # Build a Namespace that cmd_resolve expects
    resolve_args = argparse.Namespace(
        status="fixed",
        patterns=patterns,
        note=note,
        attest=attestation,
        confirm_batch_wontfix=False,
        state=getattr(args, "state", None),
        lang=getattr(args, "lang", None),
        path=getattr(args, "path", None),
        exclude=getattr(args, "exclude", None),
    )

    cmd_resolve(resolve_args)


def cmd_plan_focus(args: argparse.Namespace) -> None:
    """Set or clear the active cluster focus."""
    clear_flag = getattr(args, "clear", False)
    cluster_name: str | None = getattr(args, "cluster_name", None)

    plan = load_plan()
    if clear_flag:
        clear_focus(plan)
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
    save_plan(plan)
    print(colorize(f"  Focused on: {cluster_name}", "green"))


__all__ = [
    "cmd_plan_describe",
    "cmd_plan_done",
    "cmd_plan_focus",
    "cmd_plan_note",
    "cmd_plan_reopen",
    "cmd_plan_skip",
    "cmd_plan_unskip",
]
