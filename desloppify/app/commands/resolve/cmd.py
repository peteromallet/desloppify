"""Resolve command handlers."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import NamedTuple

from desloppify import state as state_mod
from desloppify.app.commands.helpers.guardrails import require_triage_current_or_exit
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.queue_progress import show_score_with_plan_context
from desloppify.app.commands.helpers.state import state_path
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine.plan import (
    add_uncommitted_issues,
    auto_complete_steps,
    append_log_entry,
    has_living_plan,
    load_plan,
    purge_ids,
    purge_uncommitted_ids,
    save_plan,
)
import desloppify.intelligence.narrative.core as narrative_mod
from desloppify.state import coerce_assessment_score

from desloppify.app.commands.helpers.persist import save_state_or_exit

from .apply import _resolve_all_patterns, _write_resolve_query_entry
from .queue_guard import _check_queue_order_guard
from .render import (
    _print_next_command,
    _print_resolve_summary,
    _print_subjective_reset_hint,
    _print_wontfix_batch_warning,
    render_commit_guidance,
)
from desloppify.app.commands.helpers.attestation import (
    show_note_length_requirement,
    validate_note_length,
)

from .selection import (
    ResolveQueryContext,
    _enforce_batch_wontfix_confirmation,
    _previous_score_snapshot,
    _validate_resolve_inputs,
)

_logger = logging.getLogger(__name__)


class ClusterContext(NamedTuple):
    cluster_name: str | None
    cluster_completed: bool
    cluster_remaining: int


def _capture_cluster_context(
    plan: dict, resolved_ids: list[str],
) -> ClusterContext:
    """Determine cluster membership for resolved issues, pre-purge."""
    clusters = plan.get("clusters") or {}
    overrides = plan.get("overrides") or {}
    # Find the cluster the first resolved issue belongs to
    cluster_name: str | None = None
    for rid in resolved_ids:
        ov = overrides.get(rid)
        if ov and ov.get("cluster"):
            cluster_name = ov["cluster"]
            break
    if not cluster_name or cluster_name not in clusters:
        return ClusterContext(cluster_name=None, cluster_completed=False, cluster_remaining=0)
    # Count how many will remain after these ids are removed
    current_ids = set(clusters[cluster_name].get("issue_ids") or [])
    remaining = current_ids - set(resolved_ids)
    return ClusterContext(
        cluster_name=cluster_name,
        cluster_completed=len(remaining) == 0,
        cluster_remaining=len(remaining),
    )


def _validate_fixed_note(args: argparse.Namespace) -> bool:
    if args.status != "fixed":
        return True
    note = getattr(args, "note", None)
    if validate_note_length(note):
        return True
    show_note_length_requirement(note)
    return False


def _update_living_plan_after_resolve(
    *,
    args: argparse.Namespace,
    all_resolved: list[str],
    attestation: str | None,
) -> tuple[dict | None, ClusterContext]:
    plan = None
    ctx = ClusterContext(cluster_name=None, cluster_completed=False, cluster_remaining=0)
    try:
        if not has_living_plan():
            return None, ctx
        plan = load_plan()
        ctx = _capture_cluster_context(plan, all_resolved)
        purged = purge_ids(plan, all_resolved)
        # Auto-complete steps whose issue_refs are all resolved
        step_messages = auto_complete_steps(plan)
        for msg in step_messages:
            print(colorize(msg, "green"))
        append_log_entry(
            plan,
            "resolve",
            issue_ids=all_resolved,
            actor="user",
            note=getattr(args, "note", None),
            detail={"status": args.status, "attestation": attestation},
        )
        if ctx.cluster_completed and ctx.cluster_name:
            append_log_entry(
                plan,
                "cluster_done",
                issue_ids=all_resolved,
                cluster_name=ctx.cluster_name,
                actor="user",
            )
        # Commit tracking: add to uncommitted on fix, remove on reopen
        if args.status == "fixed":
            add_uncommitted_issues(plan, all_resolved)
        elif args.status == "open":
            purge_uncommitted_ids(plan, all_resolved)
        save_plan(plan)
        if purged:
            print(colorize(f"  Plan updated: {purged} item(s) removed from queue.", "dim"))
    except PLAN_LOAD_EXCEPTIONS:
        _logger.debug("plan update failed after resolve", exc_info=True)
        print(colorize("  Warning: could not update living plan.", "yellow"), file=sys.stderr)
    return plan, ctx


def cmd_resolve(args: argparse.Namespace) -> None:
    """Resolve issue(s) matching one or more patterns."""
    attestation = getattr(args, "attest", None)
    _validate_resolve_inputs(args, attestation)
    if not _validate_fixed_note(args):
        return

    state_file = state_path(args)
    state = state_mod.load_state(state_file)

    if _check_queue_order_guard(state, args.patterns, args.status):
        return

    if args.status == "fixed":
        require_triage_current_or_exit(
            state=state,
            bypass=bool(getattr(args, "force_resolve", False)),
            attest=getattr(args, "attest", "") or "",
        )

    _enforce_batch_wontfix_confirmation(
        state,
        args,
        attestation=attestation,
        resolve_all_patterns_fn=_resolve_all_patterns,
    )
    prev = _previous_score_snapshot(state)
    prev_subjective_scores = {
        str(dim): (coerce_assessment_score(payload) or 0.0)
        for dim, payload in (state.get("subjective_assessments") or {}).items()
        if isinstance(dim, str)
    }

    all_resolved = _resolve_all_patterns(state, args, attestation=attestation)
    if not all_resolved:
        status_label = "resolved" if args.status == "open" else "open"
        print(colorize(f"No {status_label} issues matching: {' '.join(args.patterns)}", "yellow"))
        return

    save_state_or_exit(state, state_file)

    plan, cluster_ctx = _update_living_plan_after_resolve(
        args=args,
        all_resolved=all_resolved,
        attestation=attestation,
    )
    mid_cluster = (
        cluster_ctx.cluster_name is not None and not cluster_ctx.cluster_completed
    )

    _print_resolve_summary(status=args.status, all_resolved=all_resolved)
    _print_wontfix_batch_warning(
        state,
        status=args.status,
        resolved_count=len(all_resolved),
    )
    show_score_with_plan_context(state, prev)
    if not mid_cluster:
        render_commit_guidance(state, plan, all_resolved, args.status)
    _print_subjective_reset_hint(
        args=args,
        state=state,
        all_resolved=all_resolved,
        prev_subjective_scores=prev_subjective_scores,
    )

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_name, command="resolve"),
    )
    if narrative.get("milestone"):
        print(colorize(f"  → {narrative['milestone']}", "green"))

    next_command = _print_next_command(state)
    _write_resolve_query_entry(
        ResolveQueryContext(
            patterns=args.patterns,
            status=args.status,
            resolved=all_resolved,
            next_command=next_command,
            prev_overall=prev.overall,
            prev_objective=prev.objective,
            prev_strict=prev.strict,
            prev_verified=prev.verified,
            attestation=attestation,
            narrative=narrative,
            state=state,
        )
    )

    if args.status == "fixed" and plan is not None and next_command == "desloppify next":
        if mid_cluster:
            print_user_message(
                f"Hey — task done, {cluster_ctx.cluster_remaining} left in"
                f" cluster '{cluster_ctx.cluster_name}'. Run `desloppify next`"
                " to pick up the next one. Keep going — don't stop until the"
                " cluster is finished."
            )
        elif cluster_ctx.cluster_completed and cluster_ctx.cluster_name:
            print_user_message(
                f"Hey — nice, you just finished cluster '{cluster_ctx.cluster_name}'."
                " Check the commit tracking above — this is a good time to"
                " commit and push your work. Then run `desloppify next` to"
                " pick up your next task."
            )
        else:
            print_user_message(
                "Hey — nice, on to the next one. Run `desloppify next`"
                " to pick up your next task. Before moving on, glance at the"
                " commit tracking above — if there's a decent chunk of"
                " uncommitted work, consider whether now's a good time"
                " to commit and push. Otherwise just keep going."
            )


__all__ = ["_check_queue_order_guard", "cmd_resolve"]
