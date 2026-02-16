"""Resolve findings or apply ignore-pattern suppressions."""

from __future__ import annotations

import argparse
import sys

from ..command_vocab import ISSUES, REVIEW_PREPARE, SCAN
from ..utils import colorize
from ._helpers import state_path, _write_query, show_narrative_plan, show_narrative_reminders


def _require_wontfix_note(args: argparse.Namespace) -> None:
    if args.status == "wontfix" and not args.note:
        print(colorize("Wontfix items become technical debt. Add --note to record your reasoning for future review.", "yellow"))
        sys.exit(1)


def _collect_resolved_findings(
    *,
    state: dict,
    patterns: list[str],
    status: str,
    note: str | None,
    resolve_findings,
) -> list[str]:
    resolved_ids: list[str] = []
    for pattern in patterns:
        resolved_ids.extend(resolve_findings(state, pattern, status, note))
    return resolved_ids


def _print_resolve_summary(*, status: str, resolved_ids: list[str]) -> None:
    print(colorize(f"\nResolved {len(resolved_ids)} finding(s) as {status}:", "green"))
    for fid in resolved_ids[:20]:
        print(f"  {fid}")
    if len(resolved_ids) > 20:
        print(f"  ... and {len(resolved_ids) - 20} more")


def _warn_wontfix_batch(*, status: str, resolved_ids: list[str], state: dict) -> None:
    if status != "wontfix" or len(resolved_ids) <= 10:
        return
    wontfix_count = sum(1 for f in state["findings"].values() if f["status"] == "wontfix")
    actionable = sum(1 for f in state["findings"].values() if f["status"] in ("open", "wontfix", "fixed", "auto_resolved", "false_positive"))
    wontfix_pct = round(wontfix_count / actionable * 100) if actionable else 0
    print(colorize(f"\n  \u26a0 Wontfix debt is now {wontfix_count} findings ({wontfix_pct}% of actionable).", "yellow"))
    print(colorize("    The strict score reflects this. Run `desloppify show \"*\" --status wontfix` to review.", "dim"))


def _format_delta(delta: float) -> str:
    if abs(delta) < 0.05:
        return ""
    sign = "+" if delta > 0 else ""
    return f" ({sign}{delta:.1f})"


def _print_score_deltas(
    *,
    state: dict,
    previous_scores: tuple[float | None, float | None, float | None],
    get_overall_score,
    get_objective_score,
    get_strict_score,
) -> tuple[float | None, float | None, float | None]:
    prev_overall, prev_objective, prev_strict = previous_scores
    new_overall = get_overall_score(state)
    new_objective = get_objective_score(state)
    new_strict = get_strict_score(state)
    if new_overall is None or new_objective is None or new_strict is None:
        print(colorize(f"\n  Scores unavailable — run `{SCAN}`.", "yellow"))
        return new_overall, new_objective, new_strict

    overall_delta = new_overall - (prev_overall or 0)
    objective_delta = new_objective - (prev_objective or 0)
    strict_delta = new_strict - (prev_strict or 0)
    print(
        f"\n  Scores: overall {new_overall:.1f}/100{_format_delta(overall_delta)}"
        + colorize(f"  objective {new_objective:.1f}/100{_format_delta(objective_delta)}", "dim")
        + colorize(f"  strict {new_strict:.1f}/100{_format_delta(strict_delta)}", "dim")
    )
    return new_overall, new_objective, new_strict


def _warn_review_assessment_staleness(state: dict, resolved_ids: list[str]) -> None:
    has_review = any(state["findings"].get(fid, {}).get("detector") == "review" for fid in resolved_ids)
    if has_review and (state.get("subjective_assessments") or state.get("review_assessments")):
        print(colorize(f"  Score unchanged — re-run `{REVIEW_PREPARE}` to update subjective scores.", "yellow"))


def _render_narrative(args: argparse.Namespace, state: dict) -> dict:
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        lang=lang_name,
        command="resolve",
        config=getattr(args, "_config", None),
    )
    if narrative.get("milestone"):
        print(colorize(f"  → {narrative['milestone']}", "green"))
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(narrative, limit=2, skip_types={"report_scores", "review_findings_pending"})
    return narrative


def _print_remaining_review_findings(state: dict) -> None:
    remaining = sum(
        1
        for f in state["findings"].values()
        if f["status"] == "open" and f.get("detector") == "review"
    )
    if remaining <= 0:
        return
    suffix = "s" if remaining != 1 else ""
    print(colorize(f"\n  {remaining} review finding{suffix} remaining — run `{ISSUES}`", "dim"))


def cmd_resolve(args: argparse.Namespace) -> None:
    """Resolve finding(s) matching one or more patterns."""
    if args.status == "ignore":
        _apply_ignore_patterns(args, list(args.patterns))
        return

    from ..state import (
        load_state,
        save_state,
        resolve_findings,
        get_overall_score,
        get_objective_score,
        get_strict_score,
    )

    _require_wontfix_note(args)

    sp = state_path(args)
    state = load_state(sp)
    previous_scores = (get_overall_score(state), get_objective_score(state), get_strict_score(state))
    all_resolved = _collect_resolved_findings(state=state, patterns=list(args.patterns), status=args.status, note=args.note, resolve_findings=resolve_findings)

    if not all_resolved:
        print(colorize(f"No open findings matching: {' '.join(args.patterns)}", "yellow"))
        return

    save_state(state, sp)
    _print_resolve_summary(status=args.status, resolved_ids=all_resolved)
    _warn_wontfix_batch(status=args.status, resolved_ids=all_resolved, state=state)
    new_overall, new_objective, new_strict = _print_score_deltas(state=state, previous_scores=previous_scores, get_overall_score=get_overall_score, get_objective_score=get_objective_score, get_strict_score=get_strict_score)
    _warn_review_assessment_staleness(state, all_resolved)
    narrative = _render_narrative(args, state)
    _print_remaining_review_findings(state)
    print()

    prev_overall, prev_objective, prev_strict = previous_scores
    _write_query(
        {
            "command": "resolve",
            "patterns": args.patterns,
            "status": args.status,
            "resolved": all_resolved,
            "count": len(all_resolved),
            "overall_score": new_overall,
            "objective_score": new_objective,
            "strict_score": new_strict,
            "prev_overall_score": prev_overall,
            "prev_objective_score": prev_objective,
            "prev_strict_score": prev_strict,
            "narrative": narrative,
        }
    )


def _apply_ignore_patterns(args: argparse.Namespace, patterns: list[str]) -> None:
    note = str(getattr(args, "note", "") or "").strip()
    if not note:
        print(colorize("Ignore patterns suppress findings completely. Add --note to document why.", "yellow"))
        sys.exit(1)

    from ..config import add_ignore_pattern, set_ignore_metadata, save_config
    from ..state import (
        load_state,
        save_state,
        remove_ignored_findings,
        _recompute_stats,
        utc_now,
        get_overall_score,
        get_objective_score,
        get_strict_score,
    )

    sp = state_path(args)
    state = load_state(sp)

    normalized = [p for p in patterns if p]
    if not normalized:
        print(colorize("No ignore patterns provided.", "yellow"))
        return

    config = args._config
    added_at = utc_now()
    removed = 0
    by_pattern: dict[str, int] = {}
    total_before = len(state.get("findings", {}))
    for pattern in normalized:
        add_ignore_pattern(config, pattern)
        set_ignore_metadata(config, pattern, note=note, added_at=added_at)
        removed_now = remove_ignored_findings(state, pattern)
        by_pattern[pattern] = removed_now
        removed += removed_now
    save_config(config)

    raw = max(total_before, 0)
    suppressed_pct = round((removed / raw) * 100, 1) if raw else 0.0
    state["ignore_integrity"] = {
        "ignored": removed,
        "raw_findings": raw,
        "suppressed_pct": suppressed_pct,
        "ignore_patterns": len(config.get("ignore", [])),
        "ignored_by_detector": {},
        "ignored_by_tier": {},
        "ignored_findings": [],
        "updated_at": utc_now(),
    }
    _recompute_stats(state, scan_path=state.get("scan_path"))
    save_state(state, sp)

    if len(normalized) == 1:
        print(colorize(f"Added ignore pattern: {normalized[0]}", "green"))
    else:
        print(colorize(f"Added {len(normalized)} ignore patterns:", "green"))
        for pattern in normalized:
            print(f"  {pattern}")
    print(colorize(f"  Note: {note}", "dim"))
    if removed:
        print(f"  Removed {removed} matching findings from state ({suppressed_pct:.1f}% of current findings).")
    elif len(normalized) > 1:
        print("  Removed 0 matching findings from state.")
    overall = get_overall_score(state)
    objective = get_objective_score(state)
    strict = get_strict_score(state)
    if overall is not None and objective is not None and strict is not None:
        print(
            f"  Scores: overall {overall:.1f}/100"
            + colorize(f"  objective: {objective:.1f}/100", "dim")
            + colorize(f"  strict: {strict:.1f}/100", "dim")
        )
        warn = (state.get("score_integrity", {}) or {}).get("ignore_suppression_warning")
        if warn:
            print(colorize(
                f"  Ignore warning: {warn.get('suppressed_pct', 0):.1f}% findings hidden by ignore patterns.",
                "yellow",
            ))
    print()

    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        lang=lang_name,
        command="resolve",
        config=getattr(args, "_config", None),
    )
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(
        narrative,
        limit=2,
        skip_types={"report_scores", "review_findings_pending"},
    )
    payload = {
        "command": "resolve",
        "status": "ignore",
        "patterns": normalized,
        "pattern": normalized[0] if len(normalized) == 1 else None,
        "removed_by_pattern": by_pattern,
        "note": note,
        "removed": removed,
        "suppressed_pct": suppressed_pct,
        "overall_score": overall,
        "objective_score": objective,
        "strict_score": strict,
        "narrative": narrative,
    }
    _write_query(payload)
