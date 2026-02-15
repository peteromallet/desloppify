"""resolve and ignore commands: mark findings, manage ignore list."""

import sys

from ..utils import colorize
from ._helpers import state_path, _write_query


def cmd_resolve(args):
    """Resolve finding(s) matching one or more patterns."""
    from ..state import load_state, save_state, resolve_findings

    if args.status == "wontfix" and not args.note:
        print(colorize("Wontfix items become technical debt. Add --note to record your reasoning for future review.", "yellow"))
        sys.exit(1)

    sp = state_path(args)
    state = load_state(sp)
    prev_score = state.get("score", 0)
    prev_obj = state.get("objective_score")

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

    new_obj = state.get("objective_score")
    new_obj_strict = state.get("objective_strict")
    if new_obj is not None:
        delta = new_obj - (prev_obj or 0)
        delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if abs(delta) >= 0.05 else ""
        print(f"\n  Health: {new_obj:.1f}/100{delta_str}" +
              colorize(f"  (strict: {new_obj_strict:.1f}/100)", "dim"))
    else:
        delta = state["score"] - prev_score
        delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if abs(delta) >= 0.05 else ""
        print(f"\n  Score: {state['score']:.1f}/100{delta_str}" +
              colorize(f"  (strict: {state.get('strict_score', 0):.1f}/100)", "dim"))

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
                  "score": state["score"], "strict_score": state.get("strict_score", 0),
                  "objective_score": state.get("objective_score"),
                  "objective_strict": state.get("objective_strict"),
                  "prev_score": prev_score, "prev_objective": prev_obj,
                  "narrative": narrative})


def cmd_ignore_pattern(args):
    """Add a pattern to the ignore list."""
    from ..config import add_ignore_pattern, save_config
    from ..state import load_state, save_state, remove_ignored_findings

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
    print(f"  Score: {state['score']}/100" +
          colorize(f"  (strict: {state.get('strict_score', 0)}/100)", "dim"))
    print()

    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, lang=lang_name, command="ignore")
    _write_query({"command": "ignore", "pattern": args.pattern,
                  "removed": removed, "score": state["score"],
                  "strict_score": state.get("strict_score", 0),
                  "narrative": narrative})
