"""Plan override subcommand handlers: describe, note, skip, unskip, done, reopen, focus."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan, state_path
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.app.commands.plan.triage.helpers import (
    has_triage_in_queue,
    inject_triage_stages,
)
from desloppify.app.commands.plan.triage_playbook import TRIAGE_STAGE_DEPENDENCIES
from desloppify.app.commands.resolve.cmd import cmd_resolve
from desloppify.app.commands.helpers.attestation import (
    show_attestation_requirement,
    show_note_length_requirement,
    validate_attestation,
    validate_note_length,
)
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS, CommandError
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine._work_queue.core import ATTEST_EXAMPLE
from desloppify.engine.plan import (
    PLAN_FILE,
    TRIAGE_IDS,
    TRIAGE_STAGE_IDS,
    SKIP_KIND_LABELS,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    annotate_issue,
    auto_complete_steps,
    append_log_entry,
    clear_focus,
    describe_issue,
    load_plan,
    plan_path_for_state,
    purge_ids,
    purge_uncommitted_ids,
    save_plan,
    set_focus,
    skip_kind_from_flags,
    skip_kind_requires_attestation,
    skip_kind_requires_note,
    skip_kind_state_status,
    skip_items,
    unskip_items,
)

logger = logging.getLogger(__name__)

_BULK_SKIP_THRESHOLD = 5


def _resolve_state_file(path: Path | None) -> Path:
    return path if path is not None else state_mod.STATE_FILE


def _resolve_plan_file(path: Path | None) -> Path:
    return path if path is not None else PLAN_FILE


def _plan_file_for_state(state_file: Path | None) -> Path | None:
    if state_file is None:
        return None
    return plan_path_for_state(state_file)


def _snapshot_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text()


def _restore_file_snapshot(path: Path, snapshot: str | None) -> None:
    if snapshot is None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        return
    safe_write_text(path, snapshot)


def _save_plan_state_transactional(
    *,
    plan: dict,
    plan_path: Path | None,
    state_data: dict,
    state_path_value: Path | None,
) -> None:
    """Persist plan+state together; rollback both files on partial write failure."""
    effective_plan_path = _resolve_plan_file(plan_path)
    effective_state_path = _resolve_state_file(state_path_value)
    plan_snapshot = _snapshot_file(effective_plan_path)
    state_snapshot = _snapshot_file(effective_state_path)

    try:
        state_mod.save_state(state_data, effective_state_path)
        save_plan(plan, effective_plan_path)
    except Exception:
        _restore_file_snapshot(effective_state_path, state_snapshot)
        _restore_file_snapshot(effective_plan_path, plan_snapshot)
        raise


def cmd_plan_describe(args: argparse.Namespace) -> None:
    """Set augmented description on issues."""
    state = command_runtime(args).state
    if not require_completed_scan(state):
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
    append_log_entry(
        plan, "describe", issue_ids=issue_ids, actor="user",
        detail={"text": text or None},
    )
    save_plan(plan)
    print(colorize(f"  Set description on {len(issue_ids)} issue(s).", "green"))


def cmd_plan_note(args: argparse.Namespace) -> None:
    """Set note on issues."""
    state = command_runtime(args).state
    if not require_completed_scan(state):
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
    append_log_entry(
        plan, "note", issue_ids=issue_ids, actor="user",
        note=text,
    )
    save_plan(plan)
    print(colorize(f"  Set note on {len(issue_ids)} issue(s).", "green"))


# ---------------------------------------------------------------------------
# Skip / unskip
# ---------------------------------------------------------------------------


def _validate_skip_requirements(
    *,
    kind: str,
    attestation: str | None,
    note: str | None,
) -> bool:
    if not skip_kind_requires_attestation(kind):
        return True
    if not validate_attestation(attestation):
        show_attestation_requirement(
            "Permanent skip" if kind == "permanent" else "False positive",
            attestation,
            ATTEST_EXAMPLE,
        )
        return False
    if skip_kind_requires_note(kind) and not note:
        print(
            colorize("  --permanent requires --note to explain the decision.", "yellow"),
            file=sys.stderr,
        )
        return False
    return True


def _apply_state_skip_resolution(
    *,
    kind: str,
    state_file: Path | None,
    issue_ids: list[str],
    note: str | None,
    attestation: str | None,
) -> dict | None:
    status = skip_kind_state_status(kind)
    if status is None:
        return None
    state_data = state_mod.load_state(state_file)
    for fid in issue_ids:
        state_mod.resolve_issues(
            state_data,
            fid,
            status,
            note or "",
            attestation=attestation,
        )
    return state_data


def cmd_plan_skip(args: argparse.Namespace) -> None:
    """Skip issues — unified command for temporary/permanent/false-positive."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    reason: str | None = getattr(args, "reason", None)
    review_after: int | None = getattr(args, "review_after", None)
    permanent: bool = getattr(args, "permanent", False)
    false_positive: bool = getattr(args, "false_positive", False)
    note: str | None = getattr(args, "note", None)
    attestation: str | None = getattr(args, "attest", None)

    kind = skip_kind_from_flags(permanent=permanent, false_positive=false_positive)
    if not _validate_skip_requirements(
        kind=kind,
        attestation=attestation,
        note=note,
    ):
        return

    state_file = runtime.state_path
    plan_file = _plan_file_for_state(state_file)
    plan = load_plan(plan_file)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    # Bulk skip guard — prevent agents from draining the queue in one shot
    if len(issue_ids) > _BULK_SKIP_THRESHOLD:
        print(colorize(
            f"  Bulk skip: {len(issue_ids)} items will be removed from the active queue.",
            "yellow",
        ), file=sys.stderr)
        if not getattr(args, "confirm", False):
            raise CommandError(
                f"Skipping {len(issue_ids)} items requires --confirm. "
                "Review the items first, or skip individually."
            )

    # For permanent/false_positive: delegate to state layer for score impact
    state_data = _apply_state_skip_resolution(
        kind=kind,
        state_file=state_file,
        issue_ids=issue_ids,
        note=note,
        attestation=attestation,
    )

    scan_count = state.get("scan_count", 0)
    count = skip_items(
        plan,
        issue_ids,
        kind=kind,
        reason=reason,
        note=note,
        attestation=attestation,
        review_after=review_after,
        scan_count=scan_count,
    )

    # Log the skip action
    append_log_entry(
        plan,
        "skip",
        issue_ids=issue_ids,
        actor="user",
        note=note,
        detail={"kind": kind, "reason": reason},
    )
    if state_data is not None:
        _save_plan_state_transactional(
            plan=plan,
            plan_path=plan_file,
            state_data=state_data,
            state_path_value=state_file,
        )
    else:
        save_plan(plan, plan_file)

    print(colorize(f"  {SKIP_KIND_LABELS[kind]} {count} item(s).", "green"))
    if review_after:
        print(colorize(f"  Will re-surface after {review_after} scan(s).", "dim"))
    print_user_message(
        "Hey — if skipping was the right call, just continue with"
        " what you were doing. If you think a broader re-triage is"
        " needed, use `desloppify plan triage`. Run `desloppify"
        " plan --help` to see all available plan tools. Otherwise"
        " no need to reply, just keep going."
    )


def cmd_plan_unskip(args: argparse.Namespace) -> None:
    """Unskip issues — bring back to queue."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])

    state_file = runtime.state_path
    plan_file = _plan_file_for_state(state_file)
    plan = load_plan(plan_file)
    # For unskip we need to match against all statuses (skipped items may be wontfix/fp)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan, status_filter="all")
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    include_protected = bool(getattr(args, "force", False))
    count, need_reopen, protected_kept = unskip_items(
        plan, issue_ids, include_protected=include_protected,
    )
    unskipped_ids = [fid for fid in issue_ids if fid not in protected_kept]
    append_log_entry(
        plan, "unskip", issue_ids=unskipped_ids, actor="user",
        detail={"need_reopen": need_reopen},
    )

    # Reopen permanent/false_positive items in state
    reopened: list[str] = []
    if need_reopen:
        state_data = state_mod.load_state(state_file)
        for fid in need_reopen:
            reopened.extend(state_mod.resolve_issues(state_data, fid, "open"))
        _save_plan_state_transactional(
            plan=plan,
            plan_path=plan_file,
            state_data=state_data,
            state_path_value=state_file,
        )
        print(colorize(f"  Reopened {len(reopened)} issue(s) in state.", "dim"))
    else:
        save_plan(plan, plan_file)

    print(colorize(f"  Unskipped {count} item(s) — back in queue.", "green"))
    if protected_kept:
        print(colorize(
            f"  Kept {len(protected_kept)} protected skip(s) "
            f"(permanent/false_positive with notes). Use --force to override.",
            "yellow",
        ))


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------

def cmd_plan_reopen(args: argparse.Namespace) -> None:
    """Reopen resolved issues from plan context."""
    patterns: list[str] = getattr(args, "patterns", [])

    raw_state_path = state_path(args)
    state_file = raw_state_path if isinstance(raw_state_path, Path) else Path(raw_state_path) if raw_state_path else None
    state_data = state_mod.load_state(state_file)
    plan_file = _plan_file_for_state(state_file)

    reopened: list[str] = []
    for pattern in patterns:
        reopened.extend(
            state_mod.resolve_issues(state_data, pattern, "open")
        )

    if not reopened:
        print(colorize("  No resolved issues matching: " + " ".join(patterns), "yellow"))
        return

    # Remove from skipped if present, and ensure all reopened IDs are in queue
    plan = load_plan(plan_file)

    # Remove from commit tracking uncommitted list
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
    append_log_entry(
        plan, "reopen", issue_ids=reopened, actor="user",
    )
    _save_plan_state_transactional(
        plan=plan,
        plan_path=plan_file,
        state_data=state_data,
        state_path_value=state_file,
    )

    print(colorize(f"  Reopened {len(reopened)} issue(s).", "green"))
    if count:
        print(colorize("  Plan updated: items moved back to queue.", "dim"))


_CLUSTER_INDIVIDUAL_THRESHOLD = 10


def _check_cluster_guard(patterns: list[str], plan: dict, state: dict) -> bool:
    """Return True if blocked by cluster guard, False if OK to proceed."""
    clusters = plan.get("clusters", {})
    issues = state.get("issues", {})
    for pattern in patterns:
        if pattern in clusters:
            cluster = clusters[pattern]
            # Filter to alive issues only — stale IDs should not count
            ids = [
                fid for fid in cluster.get("issue_ids", [])
                if fid in issues and issues[fid].get("status") == "open"
            ]
            if len(ids) == 0:
                print(colorize(
                    f"\n  Cluster '{pattern}' is empty — add items before marking it done.\n",
                    "yellow",
                ))
                print(colorize(
                    f"  Use: desloppify plan cluster add {pattern} <issue-id>",
                    "dim",
                ))
                return True  # blocked
            if len(ids) <= _CLUSTER_INDIVIDUAL_THRESHOLD:
                _print_cluster_guard(pattern, ids, state)
                return True  # blocked
    return False  # OK


def _print_cluster_guard(cluster_name: str, issue_ids: list[str], state: dict) -> None:
    issues = state.get("issues", {})
    print(colorize(
        f"\n  Cluster '{cluster_name}' has {len(issue_ids)} item(s) — mark them done individually first:\n",
        "yellow",
    ))
    for fid in issue_ids:
        f = issues.get(fid, {})
        summary = f.get("summary", "(no summary)")[:80]
        detector = f.get("detector", "?")
        print(f"    {fid}  [{detector}]  {summary}")
    print(colorize(
        "\n  Use: desloppify resolve <id> --status fixed --note '...' --attest '...'",
        "dim",
    ))
    print(colorize(
        "  Or mark each resolved: desloppify plan resolve <id> --note '...' --confirm\n",
        "dim",
    ))


def _is_synthetic_id(fid: str) -> bool:
    """Return True if the ID is a synthetic workflow/triage item, not a real issue."""
    return fid.startswith("triage::") or fid.startswith("workflow::") or fid.startswith("subjective::")


def _resolve_synthetic_ids(patterns: list[str]) -> tuple[list[str], list[str]]:
    """Separate synthetic IDs from real issue patterns.

    Returns (synthetic_ids, remaining_patterns).
    """
    synthetic = [p for p in patterns if _is_synthetic_id(p)]
    remaining = [p for p in patterns if not _is_synthetic_id(p)]
    return synthetic, remaining


def _blocked_triage_stages(plan: dict) -> dict[str, list[str]]:
    """Return ``{stage_id: [blocked_by_ids]}`` for triage stages that can't run yet.

    Uses the dependency graph and confirmed-stage metadata directly —
    no state needed, no queue item construction.
    """
    order_set = set(plan.get("queue_order", []))
    present = order_set & TRIAGE_IDS
    if not present:
        return {}

    confirmed = set(plan.get("epic_triage_meta", {}).get("triage_stages", {}).keys())
    stage_names = ("observe", "reflect", "organize", "enrich", "sense-check", "commit")

    blocked: dict[str, list[str]] = {}
    for sid, name in zip(TRIAGE_STAGE_IDS, stage_names, strict=False):
        if sid not in present or name in confirmed:
            continue
        deps = TRIAGE_STAGE_DEPENDENCIES.get(name, set())
        unmet = sorted(
            f"triage::{dep}" for dep in deps
            if f"triage::{dep}" in present and dep not in confirmed
        )
        if unmet:
            blocked[sid] = unmet
    return blocked


def cmd_plan_resolve(args: argparse.Namespace) -> None:
    """Mark issues as fixed — delegates to cmd_resolve for rich UX."""
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

    # Handle synthetic IDs (triage::*, workflow::*, subjective::*) directly
    synthetic_ids, real_patterns = _resolve_synthetic_ids(patterns)
    if synthetic_ids:
        plan = load_plan()
        # Validate triage dependency chain
        blocked_map = _blocked_triage_stages(plan)
        for sid in synthetic_ids:
            if sid in blocked_map:
                deps = ", ".join(b.replace("triage::", "") for b in blocked_map[sid])
                print(colorize(f"  Cannot resolve {sid} — blocked by: {deps}", "red"))
                print(colorize("  Complete those stages first, or use --force-resolve to override.", "dim"))
                if not getattr(args, "force_resolve", False):
                    return

        # Gate workflow items behind triage completion
        GATED_WORKFLOW_IDS = {WORKFLOW_SCORE_CHECKPOINT_ID, WORKFLOW_CREATE_PLAN_ID}
        gated_ids = [sid for sid in synthetic_ids if sid in GATED_WORKFLOW_IDS]
        if gated_ids:
            force = getattr(args, "force_resolve", False)
            meta = plan.get("epic_triage_meta", {})
            # Triage is complete if last_completed_at is set (stages archive on --complete)
            triage_ever_completed = bool(meta.get("last_completed_at"))
            if triage_ever_completed:
                # --complete archives stages and sets last_completed_at → all 4 done
                missing: set[str] = set()
            else:
                confirmed_stages = set(meta.get("triage_stages", {}).keys())
                required_stages = {"observe", "reflect", "organize", "enrich", "commit"}
                missing = required_stages - confirmed_stages

            if missing and not force:
                # Auto-inject triage stages if not already in queue
                if not has_triage_in_queue(plan):
                    inject_triage_stages(plan)
                    meta.setdefault("triage_stages", {})
                    plan["epic_triage_meta"] = meta
                    save_plan(plan)

                # Print targeted error based on which stage is next
                stage_order = ["observe", "reflect", "organize", "enrich", "commit"]
                next_stage = next((s for s in stage_order if s in missing), "observe")

                for wid in gated_ids:
                    print(colorize(f"  Cannot resolve {wid} — triage not complete.", "red"))
                print()

                if next_stage == "observe":
                    print(colorize("  You must analyze the findings before resolving this.", "yellow"))
                    print(colorize("  Start by examining themes, root causes, and contradictions:", "dim"))
                    print(colorize('    desloppify plan triage --stage observe --report "..."', "dim"))
                    print()
                    print(colorize("  The report must be 100+ chars describing what you found.", "dim"))
                elif next_stage == "reflect":
                    print(colorize("  Observe is done. Now compare against previously completed work:", "yellow"))
                    print(colorize('    desloppify plan triage --stage reflect --report "..."', "dim"))
                    print()
                    print(colorize("  The report must mention recurring dimensions if any exist.", "dim"))
                elif next_stage == "organize":
                    print(colorize("  Reflect is done. Now create clusters and prioritize:", "yellow"))
                    print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
                    print(colorize("    desloppify plan cluster add <name> <issue-patterns>", "dim"))
                    print(colorize('    desloppify plan cluster update <name> --steps "step1" "step2"', "dim"))
                    print(colorize('    desloppify plan triage --stage organize --report "..."', "dim"))
                    print()
                    print(colorize("  All manual clusters must have descriptions and action_steps.", "dim"))
                elif next_stage == "enrich":
                    print(colorize("  Organize is done. Now enrich steps with detail and issue refs:", "yellow"))
                    print(colorize('    desloppify plan cluster update <name> --update-step N --detail "sub-details"', "dim"))
                    print(colorize('    desloppify plan triage --stage enrich --report "..."', "dim"))
                elif next_stage == "commit":
                    print(colorize("  Enrich is done. Finalize the execution plan:", "yellow"))
                    print(colorize('    desloppify plan triage --complete --strategy "..."', "dim"))

                print()
                print(colorize(f"  Remaining stages: {', '.join(sorted(missing))}", "dim"))
                print(colorize(
                    "  To skip triage: --force-resolve --note 'reason for skipping triage'",
                    "dim",
                ))

                # Log the blocked attempt
                append_log_entry(
                    plan, "workflow_blocked",
                    issue_ids=gated_ids, actor="user",
                    note=note,
                    detail={"missing_stages": sorted(missing), "next_stage": next_stage},
                )
                save_plan(plan)
                return

            if missing and force:
                # Force-resolve: require substantial note, log prominently
                if not note or len(note.strip()) < 50:
                    print(colorize(
                        f"  --force-resolve still requires --note (min 50 chars) explaining "
                        f"why you're skipping triage.",
                        "red",
                    ))
                    return
                print(colorize(
                    "  WARNING: Skipping triage requirement — this is logged.",
                    "yellow",
                ))
                append_log_entry(
                    plan, "workflow_force_skip",
                    issue_ids=gated_ids, actor="user",
                    note=note,
                    detail={"forced": True, "missing_stages": sorted(missing)},
                )
                save_plan(plan)
                # Fall through to scan gate / purge_ids below

        # Gate workflow items behind scan completion
        if gated_ids:
            scan_count_at_start = plan.get("scan_count_at_plan_start")
            if scan_count_at_start is not None:
                resolved_state_path = state_path(args)
                state_data = state_mod.load_state(resolved_state_path)
                current_scan_count = int(state_data.get("scan_count", 0) or 0)
                scan_ran = current_scan_count > scan_count_at_start
                scan_skipped = plan.get("scan_gate_skipped", False)

                if not scan_ran and not scan_skipped and not force:
                    for wid in gated_ids:
                        print(colorize(
                            f"  Cannot resolve {wid} — no scan has run this cycle.",
                            "red",
                        ))
                    print()
                    print(colorize(
                        "  You must run a scan before resolving workflow items:",
                        "yellow",
                    ))
                    print(colorize("    desloppify scan", "dim"))
                    print()
                    print(colorize(
                        f"  Scans at cycle start: {scan_count_at_start}  "
                        f"Current: {current_scan_count}",
                        "dim",
                    ))
                    print(colorize(
                        "  To skip scan requirement: desloppify plan scan-gate --skip "
                        '--note "reason for skipping scan"',
                        "dim",
                    ))
                    print(colorize(
                        "  Or use: --force-resolve --note 'reason for skipping'",
                        "dim",
                    ))

                    append_log_entry(
                        plan, "scan_gate_blocked",
                        issue_ids=gated_ids, actor="user",
                        note=note,
                        detail={
                            "scan_count_at_start": scan_count_at_start,
                            "current_scan_count": current_scan_count,
                        },
                    )
                    save_plan(plan)
                    return

        purge_ids(plan, synthetic_ids)
        # Auto-complete steps whose issue_refs are all resolved
        step_messages = auto_complete_steps(plan)
        for msg in step_messages:
            print(colorize(msg, "green"))
        append_log_entry(
            plan, "done", issue_ids=synthetic_ids, actor="user", note=note,
        )
        save_plan(plan)
        for sid in synthetic_ids:
            print(colorize(f"  Resolved: {sid}", "green"))
        if not real_patterns:
            return
        # Continue with remaining real patterns
        patterns = real_patterns
        args.patterns = patterns

    # Validate note length
    if not validate_note_length(note):
        show_note_length_requirement(note)
        return

    # Pre-validate attestation before delegating (avoids stale hint in resolve)
    if not validate_attestation(attestation):
        show_attestation_requirement("Plan resolve", attestation, ATTEST_EXAMPLE)
        return

    # Cluster completion guard: block bulk-completing small clusters
    try:
        runtime = command_runtime(args)
        state = runtime.state
        plan = load_plan()
        if _check_cluster_guard(patterns, plan, state):
            return
    except PLAN_LOAD_EXCEPTIONS:
        plan = None

    # Log the done action (best-effort)
    try:
        if plan is None:
            plan = load_plan()
        clusters = plan.get("clusters", {})
        cluster_name = None
        for p in patterns:
            if p in clusters:
                cluster_name = p
                break
        append_log_entry(
            plan,
            "done",
            issue_ids=patterns,
            cluster_name=cluster_name,
            actor="user",
            note=note,
        )
        save_plan(plan)
    except PLAN_LOAD_EXCEPTIONS as exc:
        log_best_effort_failure(logger, "append plan resolve log entry", exc)
        print(colorize(f"  Note: unable to append plan resolve log entry ({exc}).", "dim"))

    # Build a Namespace that cmd_resolve expects
    resolve_args = argparse.Namespace(
        status="fixed",
        patterns=patterns,
        note=note,
        attest=attestation,
        confirm_batch_wontfix=False,
        force_resolve=bool(getattr(args, "force_resolve", False)),
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
        prev = plan.get("active_cluster")
        clear_focus(plan)
        append_log_entry(
            plan, "focus", actor="user",
            detail={"action": "clear", "previous": prev},
        )
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
    append_log_entry(
        plan, "focus", cluster_name=cluster_name, actor="user",
        detail={"action": "set"},
    )
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
    state_data = state_mod.load_state(resolved_state_path)
    current_scan_count = int(state_data.get("scan_count", 0) or 0)
    scan_ran = current_scan_count > scan_count_at_start
    scan_skipped = plan.get("scan_gate_skipped", False)

    if not skip:
        # Status check
        if scan_ran:
            print(colorize("  Scan gate: PASSED", "green"))
            print(colorize(
                f"  Scans at cycle start: {scan_count_at_start}  "
                f"Current: {current_scan_count}",
                "dim",
            ))
        elif scan_skipped:
            print(colorize("  Scan gate: SKIPPED (manually)", "yellow"))
        else:
            print(colorize("  Scan gate: BLOCKED", "red"))
            print(colorize(
                f"  Scans at cycle start: {scan_count_at_start}  "
                f"Current: {current_scan_count}",
                "dim",
            ))
            print(colorize("  Run: desloppify scan", "dim"))
            print(colorize(
                '  Or:  desloppify plan scan-gate --skip --note "reason"',
                "dim",
            ))
        return

    # --skip mode
    if scan_ran:
        print(colorize("  Scan already ran this cycle — no skip needed.", "green"))
        return

    if not note or len(note.strip()) < 50:
        print(colorize(
            "  --skip requires --note with at least 50 chars explaining why.",
            "red",
        ))
        return

    plan["scan_gate_skipped"] = True
    append_log_entry(
        plan, "scan_gate_skip",
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
    "cmd_plan_resolve",
    "cmd_plan_focus",
    "cmd_plan_note",
    "cmd_plan_reopen",
    "cmd_plan_scan_gate",
    "cmd_plan_skip",
    "cmd_plan_unskip",
]
