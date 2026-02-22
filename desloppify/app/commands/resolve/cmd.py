"""Resolve findings or apply ignore-pattern suppressions."""

from __future__ import annotations

import argparse
import sys

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import state_path
from desloppify.core import config as config_mod
from desloppify.core.fallbacks import print_error
from desloppify.engine.work_queue import ATTEST_EXAMPLE
from desloppify.intelligence import narrative as narrative_mod
from desloppify.utils import colorize

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
    _assessment_score,
    _enforce_batch_wontfix_confirmation,
    _previous_score_snapshot,
    _show_attestation_requirement,
    _validate_attestation,
    _validate_resolve_inputs,
)


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
        str(dim): _assessment_score(payload)
        for dim, payload in (state.get("subjective_assessments") or {}).items()
        if isinstance(dim, str)
    }

    all_resolved = _resolve_all_patterns(state, args, attestation=attestation)
    if not all_resolved:
        print(colorize(f"No open findings matching: {' '.join(args.patterns)}", "yellow"))
        return

    state_mod.save_state(state, state_file)
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
    _print_score_movement(
        status=args.status,
        prev_overall=prev.overall,
        prev_objective=prev.objective,
        prev_strict=prev.strict,
        prev_verified=prev.verified,
        state=state,
        has_review_findings=has_review_findings,
    )
    _print_subjective_reset_hint(
        args=args,
        state=state,
        all_resolved=all_resolved,
        prev_subjective_scores=prev_subjective_scores,
        assessment_score_fn=_assessment_score,
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
    if not _validate_attestation(attestation):
        _show_attestation_requirement("Ignore", attestation, ATTEST_EXAMPLE)
        sys.exit(1)

    state_file = state_path(args)
    state = state_mod.load_state(state_file)

    config = command_runtime(args).config
    config_mod.add_ignore_pattern(config, args.pattern)
    try:
        config_mod.save_config(config)
    except OSError as e:
        print_error(f"could not save config: {e}")
        sys.exit(1)

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
    state_mod.save_state(state, state_file)

    print(colorize(f"Added ignore pattern: {args.pattern}", "green"))
    if removed:
        print(f"  Removed {removed} matching findings from state.")
    scores = state_mod.score_snapshot(state)
    if (
        scores.overall is not None
        and scores.objective is not None
        and scores.strict is not None
        and scores.verified is not None
    ):
        print(
            f"  Scores: overall {scores.overall:.1f}/100"
            + colorize(f"  objective: {scores.objective:.1f}/100", "dim")
            + colorize(f"  strict: {scores.strict:.1f}/100", "dim")
            + colorize(f"  verified: {scores.verified:.1f}/100", "dim")
        )
    print()

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_name, command="ignore"),
    )
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
