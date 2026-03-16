"""Skip and unskip command handlers for plan overrides."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.attestation import (
    show_attestation_requirement,
    validate_attestation,
)
from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.state import require_issue_inventory
from .io import (
    _plan_file_for_state,
    save_plan_state_transactional,
)
from desloppify.app.commands.plan.shared.patterns import resolve_ids_from_patterns
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.app.commands.helpers.transition_messages import emit_transition_message
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_EXECUTE,
    clear_postflight_scan_completion,
)
from desloppify.engine.plan_ops import (
    SKIP_KIND_LABELS,
    append_log_entry,
    backlog_items,
    skip_items,
    skip_kind_from_flags,
    skip_kind_requires_attestation,
    skip_kind_requires_note,
    skip_kind_state_status,
    unskip_items,
)
from desloppify.engine.plan_state import (
    load_plan,
    save_plan,
)

logger = logging.getLogger(__name__)

_BULK_SKIP_THRESHOLD = 5
_TRIAGE_SKIP_ATTESTATION_PHRASES = ("reviewed", "not gaming")
_TRIAGE_SKIP_ATTEST_EXAMPLE = (
    "I have reviewed this triage skip against the code and I am not gaming "
    "the score by suppressing a real defect."
)


def _validate_skip_requirements(
    *,
    kind: str,
    attestation: str | None,
    note: str | None,
) -> bool:
    if not skip_kind_requires_attestation(kind):
        return True
    if not validate_attestation(
        attestation,
        required_phrases=_TRIAGE_SKIP_ATTESTATION_PHRASES,
    ):
        show_attestation_requirement(
            "Permanent skip" if kind == "permanent" else "False positive",
            attestation,
            _TRIAGE_SKIP_ATTEST_EXAMPLE,
            required_phrases=_TRIAGE_SKIP_ATTESTATION_PHRASES,
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


def _validate_temporary_skip_confirmation(
    *,
    confirm: bool,
    kind: str,
    reason: str | None,
    attestation: str | None,
) -> bool:
    if not confirm or kind != "temporary":
        return True
    if not reason:
        print(
            colorize(
                "  --confirm requires --reason to describe why this is being deferred.",
                "red",
            )
        )
        return False
    required_phrases = ("i have actually reflected", "not deferring")
    normalized_attest = " ".join((attestation or "").strip().lower().split())
    missing = [phrase for phrase in required_phrases if phrase not in normalized_attest]
    if not missing:
        return True
    print(
        colorize(
            "  Deferring items requires you to confirm you've thought this through.",
            "yellow",
        )
    )
    print(colorize("  Add this to your command:", "dim"))
    print()
    print(
        colorize(
            '    --attest "I have actually reflected and '
            'I am not deferring this for lazy reasons."',
            "dim",
        )
    )
    print()
    return False


def _warn_or_block_bulk_skip(issue_ids: list[str], *, confirm: bool) -> None:
    if len(issue_ids) <= _BULK_SKIP_THRESHOLD:
        return
    print(
        colorize(
            f"  Bulk skip: {len(issue_ids)} items will be removed from the active queue.",
            "yellow",
        ),
        file=sys.stderr,
    )
    if confirm:
        return
    raise CommandError(
        f"Skipping {len(issue_ids)} items requires --confirm. "
        "Review the items first, or skip individually."
    )


def _save_skip_plan_state(
    *,
    plan: dict,
    plan_file: Path | None,
    state_data: dict | None,
    state_file: Path | None,
) -> None:
    if state_data is None:
        save_plan(plan, plan_file)
        return
    save_plan_state_transactional(
        plan=plan,
        plan_path=plan_file,
        state_data=state_data,
        state_path_value=state_file,
    )


def cmd_plan_skip(args: argparse.Namespace) -> None:
    """Skip issues — unified command for temporary/permanent/false-positive."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_issue_inventory(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    reason: str | None = getattr(args, "reason", None)
    review_after: int | None = getattr(args, "review_after", None)
    permanent: bool = getattr(args, "permanent", False)
    false_positive: bool = getattr(args, "false_positive", False)
    note: str | None = getattr(args, "note", None)
    attestation: str | None = getattr(args, "attest", None)

    kind = skip_kind_from_flags(permanent=permanent, false_positive=false_positive)

    if not _validate_temporary_skip_confirmation(
        confirm=bool(getattr(args, "confirm", False)),
        kind=kind,
        reason=reason,
        attestation=attestation,
    ):
        return
    if not _validate_skip_requirements(kind=kind, attestation=attestation, note=note):
        raise CommandError(
            "Invalid plan skip attestation or note.",
            exit_code=2,
        )

    state_file = runtime.state_path
    plan_file = _plan_file_for_state(state_file)
    plan = load_plan(plan_file)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    _warn_or_block_bulk_skip(issue_ids, confirm=bool(getattr(args, "confirm", False)))

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

    append_log_entry(
        plan,
        "skip",
        issue_ids=issue_ids,
        actor="user",
        note=note,
        detail={"kind": kind, "reason": reason},
    )
    transition_phase: str | None = None
    if clear_postflight_scan_completion(plan, issue_ids=issue_ids, state=state):
        transition_phase = LIFECYCLE_PHASE_EXECUTE
    _save_skip_plan_state(
        plan=plan,
        plan_file=plan_file,
        state_data=state_data,
        state_file=state_file,
    )

    print(colorize(f"  {SKIP_KIND_LABELS[kind]} {count} item(s).", "green"))
    if review_after:
        print(colorize(f"  Will re-surface after {review_after} scan(s).", "dim"))
    if kind == "temporary":
        print(
            colorize(
                "  If you're actually not going to fix these, use "
                "`desloppify plan skip <patterns> --permanent` instead to wontfix them.",
                "dim",
            )
        )
    print_user_message(
        "Hey — if skipping was the right call, just continue with"
        " what you were doing. If you think a broader re-triage is"
        " needed, use `desloppify plan triage`. Run `desloppify"
        " plan --help` to see all available plan tools. Otherwise"
        " no need to reply, just keep going."
    )
    if transition_phase:
        emit_transition_message(transition_phase)


def cmd_plan_unskip(args: argparse.Namespace) -> None:
    """Unskip issues — bring back to queue."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_issue_inventory(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])

    state_file = runtime.state_path
    plan_file = _plan_file_for_state(state_file)
    plan = load_plan(plan_file)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan, status_filter="all")
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    include_protected = bool(getattr(args, "force", False))
    count, need_reopen, protected_kept = unskip_items(
        plan,
        issue_ids,
        include_protected=include_protected,
    )
    unskipped_ids = [fid for fid in issue_ids if fid not in protected_kept]
    append_log_entry(
        plan,
        "unskip",
        issue_ids=unskipped_ids,
        actor="user",
        detail={"need_reopen": need_reopen},
    )
    transition_phase: str | None = None
    if clear_postflight_scan_completion(plan, issue_ids=unskipped_ids, state=state):
        transition_phase = LIFECYCLE_PHASE_EXECUTE

    reopened: list[str] = []
    if need_reopen:
        state_data = state_mod.load_state(state_file)
        for fid in need_reopen:
            reopened.extend(state_mod.resolve_issues(state_data, fid, "open"))
        save_plan_state_transactional(
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
        print(
            colorize(
                f"  Kept {len(protected_kept)} protected skip(s) "
                f"(permanent/false_positive with notes). Use --force to override.",
                "yellow",
            )
        )
    if transition_phase:
        emit_transition_message(transition_phase)


def cmd_plan_backlog(args: argparse.Namespace) -> None:
    """Move deferred items to backlog — remove from plan tracking entirely."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_issue_inventory(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])

    state_file = runtime.state_path
    plan_file = _plan_file_for_state(state_file)
    plan = load_plan(plan_file)
    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan, status_filter="all")
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    removed = backlog_items(plan, issue_ids)
    if not removed:
        print(colorize("  No matching deferred items found.", "yellow"))
        return

    # Reopen issues whose state status was set by the skip (deferred/triaged_out)
    # so they don't get stranded with a non-open status while untracked by plan.
    _BACKLOG_REOPEN_STATUSES = {"deferred", "triaged_out"}
    state_data = state_mod.load_state(state_file)
    issues = state_data.get("work_items", {})
    reopen_ids = [
        fid for fid in removed
        if issues.get(fid, {}).get("status") in _BACKLOG_REOPEN_STATUSES
    ]

    if reopen_ids:
        for fid in reopen_ids:
            state_mod.resolve_issues(state_data, fid, "open")

    append_log_entry(
        plan,
        "backlog",
        issue_ids=removed,
        actor="user",
    )
    transition_phase: str | None = None
    if clear_postflight_scan_completion(plan, issue_ids=removed, state=state_data):
        transition_phase = LIFECYCLE_PHASE_EXECUTE

    if reopen_ids:
        save_plan_state_transactional(
            plan=plan,
            plan_path=plan_file,
            state_data=state_data,
            state_path_value=state_file,
        )
    else:
        save_plan(plan, plan_file)

    print(colorize(f"  Moved {len(removed)} item(s) to backlog.", "green"))
    if reopen_ids:
        print(colorize(f"  Reopened {len(reopen_ids)} deferred/triaged-out issue(s) in state.", "dim"))
    if transition_phase:
        emit_transition_message(transition_phase)


__all__ = [
    "_apply_state_skip_resolution",
    "_validate_skip_requirements",
    "cmd_plan_backlog",
    "cmd_plan_skip",
    "cmd_plan_unskip",
]
