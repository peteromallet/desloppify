"""Resolve command handlers."""

from __future__ import annotations

import argparse

import desloppify.intelligence.narrative.core as narrative_mod
from desloppify.app.commands.helpers.attestation import (
    show_note_length_requirement,
    validate_note_length,
)
from desloppify.app.commands.helpers.guardrails import require_triage_current_or_exit
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.state_persistence import save_state_or_exit
from desloppify.app.commands.helpers.queue_progress import show_score_with_plan_context
from desloppify.app.commands.helpers.state import state_path
from desloppify.base.output.terminal import colorize
from desloppify.engine._state.resolution import coerce_assessment_score
from desloppify.state_io import load_state

from .apply import _resolve_all_patterns, _write_resolve_query_entry
from .living_plan import update_living_plan_after_resolve
from .messages import print_fixed_next_user_message, print_no_match_warning
from .plan_load import load_resolve_plan_access
from .queue_guard import _check_queue_order_guard
from .render import (
    _print_next_command,
    _print_resolve_summary,
    _print_subjective_reset_hint,
    _print_wontfix_batch_warning,
    render_commit_guidance,
)
from .selection import (
    ResolveQueryContext,
    _enforce_batch_wontfix_confirmation,
    _previous_score_snapshot,
    _validate_resolve_inputs,
)


def _validate_fixed_note(args: argparse.Namespace) -> bool:
    if args.status != "fixed":
        return True
    note = getattr(args, "note", None)
    if validate_note_length(note):
        return True
    show_note_length_requirement(note)
    return False


def _load_state_with_guards(
    args: argparse.Namespace,
    *,
    attestation: str | None,
) -> tuple[str, dict, object] | None:
    """Validate inputs, apply guardrails, and load state for resolve."""
    _validate_resolve_inputs(args, attestation)
    if not _validate_fixed_note(args):
        return None

    state_file = state_path(args)
    state = load_state(state_file)
    plan_access = load_resolve_plan_access()

    if not getattr(args, "force_resolve", False):
        if _check_queue_order_guard(
            state,
            args.patterns,
            args.status,
            plan_access=plan_access,
        ):
            return None

    if args.status == "fixed":
        require_triage_current_or_exit(
            state=state,
            plan=plan_access.plan if isinstance(plan_access.plan, dict) and not plan_access.degraded else None,
            patterns=args.patterns,
            bypass=bool(getattr(args, "force_resolve", False)),
            attest=getattr(args, "attest", "") or "",
        )

    return state_file, state, plan_access


def _resolve_ids_with_snapshots(
    state: dict,
    args: argparse.Namespace,
    *,
    attestation: str | None,
    plan_access,
) -> tuple[object, dict[str, float], list[str]]:
    """Apply resolve patterns and return pre/post context for rendering."""
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
    all_resolved = _resolve_all_patterns(
        state,
        args,
        attestation=attestation,
        plan_access=plan_access,
    )
    return prev, prev_subjective_scores, all_resolved


def cmd_resolve(args: argparse.Namespace) -> None:
    """Resolve issue(s) matching one or more patterns."""
    attestation = getattr(args, "attest", None)
    loaded = _load_state_with_guards(args, attestation=attestation)
    if loaded is None:
        return
    state_file, state, plan_access = loaded
    prev, prev_subjective_scores, all_resolved = _resolve_ids_with_snapshots(
        state,
        args,
        attestation=attestation,
        plan_access=plan_access,
    )
    if not all_resolved:
        print_no_match_warning(args)
        return

    save_state_or_exit(state, state_file)

    plan, cluster_ctx = update_living_plan_after_resolve(
        args=args,
        all_resolved=all_resolved,
        attestation=attestation,
        state_file=state_file,
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
    print_fixed_next_user_message(
        args=args,
        plan=plan,
        next_command=next_command,
        mid_cluster=mid_cluster,
        cluster_ctx=cluster_ctx,
    )


__all__ = ["_check_queue_order_guard", "cmd_resolve"]
