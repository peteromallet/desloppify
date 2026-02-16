"""resolve and ignore commands: mark findings, manage ignore list."""

from __future__ import annotations

import argparse
import sys

from ..utils import colorize
from ._helpers import state_path, _write_query


def cmd_resolve(args: argparse.Namespace) -> None:
    """Resolve finding(s) matching one or more patterns."""
    from ..state import (
        load_state,
        save_state,
        resolve_findings,
        get_overall_score,
        get_objective_score,
        get_strict_score,
    )

    if args.status == "wontfix" and not args.note:
        print(colorize("Wontfix items become technical debt. Add --note to record your reasoning for future review.", "yellow"))
        sys.exit(1)

    sp = state_path(args)
    state = load_state(sp)
    prev_overall = get_overall_score(state)
    prev_objective = get_objective_score(state)
    prev_strict = get_strict_score(state)

    all_resolved = []
    for pattern in args.patterns:
        resolved = resolve_findings(state, pattern, args.status, args.note)
        all_resolved.extend(resolved)

    if not all_resolved:
        print(colorize(f"No open findings matching: {' '.join(args.patterns)}", "yellow"))
        return

    save_state(state, sp)

    print(colorize(f"\nResolved {len(all_resolved)} finding(s) as {args.status}:", "green"))
    for fid in all_resolved[:20]:
        print(f"  {fid}")
    if len(all_resolved) > 20:
        print(f"  ... and {len(all_resolved) - 20} more")

    # Warn when batch wontfixing creates significant debt
    if args.status == "wontfix" and len(all_resolved) > 10:
        wontfix_count = sum(1 for f in state["findings"].values() if f["status"] == "wontfix")
        actionable = sum(1 for f in state["findings"].values()
                         if f["status"] in ("open", "wontfix", "fixed", "auto_resolved", "false_positive"))
        wontfix_pct = round(wontfix_count / actionable * 100) if actionable else 0
        print(colorize(f"\n  \u26a0 Wontfix debt is now {wontfix_count} findings ({wontfix_pct}% of actionable).", "yellow"))
        print(colorize(f"    The strict score reflects this. Run `desloppify show \"*\" --status wontfix` to review.", "dim"))

    new_overall = get_overall_score(state)
    new_objective = get_objective_score(state)
    new_strict = get_strict_score(state)
    if new_overall is not None and new_objective is not None and new_strict is not None:
        overall_delta = new_overall - (prev_overall or 0)
        objective_delta = new_objective - (prev_objective or 0)
        strict_delta = new_strict - (prev_strict or 0)
        overall_delta_str = (
            f" ({'+' if overall_delta > 0 else ''}{overall_delta:.1f})"
            if abs(overall_delta) >= 0.05 else ""
        )
        objective_delta_str = (
            f" ({'+' if objective_delta > 0 else ''}{objective_delta:.1f})"
            if abs(objective_delta) >= 0.05 else ""
        )
        strict_delta_str = (
            f" ({'+' if strict_delta > 0 else ''}{strict_delta:.1f})"
            if abs(strict_delta) >= 0.05 else ""
        )
        print(
            f"\n  Scores: overall {new_overall:.1f}/100{overall_delta_str}"
            + colorize(f"  objective {new_objective:.1f}/100{objective_delta_str}", "dim")
            + colorize(f"  strict {new_strict:.1f}/100{strict_delta_str}", "dim")
        )
    else:
        print(colorize("\n  Scores unavailable — run `desloppify scan`.", "yellow"))

    # When resolving review findings with active assessments, the score
    # is driven by assessments, not finding status — nudge re-review.
    has_review = any(state["findings"].get(fid, {}).get("detector") == "review"
                     for fid in all_resolved)
    if has_review and (state.get("subjective_assessments") or state.get("review_assessments")):
        print(colorize("  Score unchanged — re-run `desloppify review` to update subjective scores.", "yellow"))

    # Computed narrative: milestone + context for LLM
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, lang=lang_name, command="resolve")
    if narrative.get("milestone"):
        print(colorize(f"  → {narrative['milestone']}", "green"))

    remaining = sum(1 for f in state["findings"].values()
                    if f["status"] == "open" and f.get("detector") == "review")
    if remaining > 0:
        s = "s" if remaining != 1 else ""
        print(colorize(f"\n  {remaining} review finding{s} remaining — run `desloppify issues`", "dim"))
    print()

    _write_query({"command": "resolve", "patterns": args.patterns, "status": args.status,
                  "resolved": all_resolved, "count": len(all_resolved),
                  "overall_score": get_overall_score(state),
                  "objective_score": get_objective_score(state),
                  "strict_score": get_strict_score(state),
                  "prev_overall_score": prev_overall,
                  "prev_objective_score": prev_objective,
                  "prev_strict_score": prev_strict,
                  "narrative": narrative})


def cmd_ignore_pattern(args: argparse.Namespace) -> None:
    """Add a pattern to the ignore list."""
    from ..config import add_ignore_pattern, save_config
    from ..state import (
        load_state,
        save_state,
        remove_ignored_findings,
        get_overall_score,
        get_objective_score,
        get_strict_score,
    )

    sp = state_path(args)
    state = load_state(sp)

    config = args._config
    add_ignore_pattern(config, args.pattern)
    save_config(config)

    removed = remove_ignored_findings(state, args.pattern)
    save_state(state, sp)

    print(colorize(f"Added ignore pattern: {args.pattern}", "green"))
    if removed:
        print(f"  Removed {removed} matching findings from state.")
    overall = get_overall_score(state)
    objective = get_objective_score(state)
    strict = get_strict_score(state)
    if overall is not None and objective is not None and strict is not None:
        print(
            f"  Scores: overall {overall:.1f}/100"
            + colorize(f"  objective: {objective:.1f}/100", "dim")
            + colorize(f"  strict: {strict:.1f}/100", "dim")
        )
    print()

    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, lang=lang_name, command="ignore")
    _write_query({"command": "ignore", "pattern": args.pattern,
                  "removed": removed,
                  "overall_score": overall,
                  "objective_score": objective,
                  "strict_score": strict,
                  "narrative": narrative})
