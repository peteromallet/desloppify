"""Resolve findings or apply ignore-pattern suppressions."""

from __future__ import annotations

import argparse
import sys

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.score_update import print_score_update
from desloppify.app.commands.helpers.state import state_path
from desloppify.core import config as config_mod
from desloppify.core.fallbacks import print_error
from desloppify.engine.work_queue import ATTEST_EXAMPLE
from desloppify.intelligence import narrative as narrative_mod
from desloppify.state import coerce_assessment_score
from desloppify.core.output_api import colorize
from desloppify.core.tooling import check_config_staleness

from .apply import _resolve_all_patterns, _write_resolve_query_entry
from .render import (
    _print_next_command,
    _print_resolve_summary,
    _print_score_movement,
    _print_subjective_reset_hint,
    _print_wontfix_batch_warning,
)
from .selection import (
    ResolveQueryContext,
    _enforce_batch_wontfix_confirmation,
    _previous_score_snapshot,
    show_attestation_requirement,
    validate_attestation,
    _validate_resolve_inputs,
)


def _save_state_or_exit(state: dict, state_file: str) -> None:
    """Persist state with a consistent CLI error boundary."""
    try:
        state_mod.save_state(state, state_file)
    except OSError as exc:
        print_error(f"could not save state: {exc}")
        sys.exit(1)


def _save_config_or_exit(config: dict) -> None:
    """Persist config with a consistent CLI error boundary."""
    try:
        config_mod.save_config(config)
    except OSError as exc:
        print_error(f"could not save config: {exc}")
        sys.exit(1)


def cmd_resolve(args: argparse.Namespace) -> None:
    """Resolve finding(s) matching one or more patterns."""
    attestation = getattr(args, "attest", None)
    _validate_resolve_inputs(args, attestation)

    state_file = state_path(args)
    state = state_mod.load_state(state_file)
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
        print(
            colorize(
                f"No {status_label} findings matching: {' '.join(args.patterns)}",
                "yellow",
            )
        )
        return

    _save_state_or_exit(state, state_file)

    # Remove resolved items from the living plan queue (best-effort)
    try:
        from desloppify.engine.plan import has_living_plan, load_plan, purge_ids, save_plan

        if has_living_plan():
            plan = load_plan()
            purged = purge_ids(plan, all_resolved)
            if purged:
                save_plan(plan)
                print(colorize(f"  Plan updated: {purged} item(s) removed from queue.", "dim"))
    except (OSError, ValueError, KeyError, TypeError):
        print(colorize("  Warning: could not update living plan.", "yellow"), file=sys.stderr)

    _print_resolve_summary(status=args.status, all_resolved=all_resolved)
    _print_wontfix_batch_warning(
        state,
        status=args.status,
        resolved_count=len(all_resolved),
    )
    has_review_findings = any(
        state["findings"].get(fid, {}).get("detector") == "review"
        for fid in all_resolved
    )
    from desloppify.app.commands.helpers.score import target_strict_score_from_config

    _resolve_config = config_mod.load_config()
    _resolve_target = target_strict_score_from_config(_resolve_config, fallback=95.0)
    _print_score_movement(
        status=args.status,
        prev_overall=prev.overall,
        prev_objective=prev.objective,
        prev_strict=prev.strict,
        prev_verified=prev.verified,
        state=state,
        has_review_findings=has_review_findings,
        target_strict=_resolve_target,
    )
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


def cmd_ignore_pattern(args: argparse.Namespace) -> None:
    """Add a pattern to the ignore list."""
    attestation = getattr(args, "attest", None)
    if not validate_attestation(attestation):
        show_attestation_requirement("Ignore", attestation, ATTEST_EXAMPLE)
        sys.exit(1)

    runtime = command_runtime(args)
    state_file = runtime.state_path
    state = runtime.state
    prev = state_mod.score_snapshot(state)

    config = runtime.config
    config_mod.add_ignore_pattern(config, args.pattern)
    config["needs_rescan"] = True
    _save_config_or_exit(config)

    removed = state_mod.remove_ignored_findings(state, args.pattern)
    state.setdefault("attestation_log", []).append(
        {
            "timestamp": state.get("last_scan"),
            "command": "ignore",
            "pattern": args.pattern,
            "attestation": attestation,
            "affected": removed,
        }
    )
    _save_state_or_exit(state, state_file)

    print(colorize(f"Added ignore pattern: {args.pattern}", "green"))
    if removed:
        print(f"  Removed {removed} matching findings from state.")
    config_warning = check_config_staleness(config)
    if config_warning:
        print(colorize(f"  {config_warning}", "yellow"))
    print_score_update(state, prev)

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_name, command="ignore"),
    )
    scores = state_mod.score_snapshot(state)
    write_query(
        {
            "command": "ignore",
            "pattern": args.pattern,
            "removed": removed,
            "overall_score": scores.overall,
            "objective_score": scores.objective,
            "strict_score": scores.strict,
            "verified_strict_score": scores.verified,
            "attestation": attestation,
            "narrative": narrative,
        }
    )
