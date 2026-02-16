"""next command: show next highest-priority open finding(s)."""

import json

from ..utils import colorize
from ._helpers import state_path, _write_query


def _serialize_item(f: dict) -> dict:
    """Build a serializable output dict from a finding."""
    return {"id": f["id"], "tier": f["tier"], "confidence": f["confidence"],
            "file": f["file"], "summary": f["summary"], "detail": f.get("detail", {})}


def cmd_next(args) -> None:
    """Show next highest-priority open finding(s)."""
    from ..state import load_state, get_overall_score, get_objective_score, get_strict_score
    from ..plan import get_next_items

    sp = state_path(args)
    state = load_state(sp)

    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    tier = getattr(args, "tier", None)
    count = getattr(args, "count", 1) or 1

    items = get_next_items(state, tier, count, scan_path=state.get("scan_path"))
    if not items:
        strict = get_strict_score(state)
        suffix = f" Strict score: {strict:.1f}/100" if strict is not None else ""
        print(colorize(f"Nothing to do!{suffix}", "green"))
        _write_query({
            "command": "next",
            "items": [],
            "overall_score": get_overall_score(state),
            "objective_score": get_objective_score(state),
            "strict_score": strict,
        })
        return

    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, lang=lang_name, command="next")

    _write_query({
        "command": "next",
        "overall_score": get_overall_score(state),
        "objective_score": get_objective_score(state),
        "strict_score": get_strict_score(state),
        "items": [_serialize_item(f) for f in items],
        "narrative": narrative,
    })

    output_file = getattr(args, "output", None)
    if output_file:
        output = [_serialize_item(f) for f in items]
        try:
            from ..utils import safe_write_text
            safe_write_text(output_file, json.dumps(output, indent=2) + "\n")
            print(colorize(f"Wrote {len(items)} items to {output_file}", "green"))
        except OSError as e:
            print(colorize(f"Could not write to {output_file}: {e}", "red"))
        return

    # Look up dimension info and scoped findings for context
    dim_scores = state.get("dimension_scores", {})
    from ..state import path_scoped_findings
    findings_scoped = path_scoped_findings(state["findings"], state.get("scan_path"))

    for i, item in enumerate(items):
        if i > 0:
            print()
        label = f"  [{i+1}/{len(items)}]" if len(items) > 1 else "  Next item"
        print(colorize(f"{label} (Tier {item['tier']}, {item['confidence']} confidence):", "bold"))
        print(colorize("  " + "─" * 60, "dim"))
        print(f"  {colorize(item['summary'], 'yellow')}")
        print(f"  File: {item['file']}")
        print(colorize(f"  ID:   {item['id']}", "dim"))

        detail = item.get("detail", {})
        if detail.get("lines"):
            print(f"  Lines: {', '.join(str(l) for l in detail['lines'][:8])}")
        if detail.get("category"):
            print(f"  Category: {detail['category']}")
        if detail.get("importers") is not None:
            print(f"  Active importers: {detail['importers']}")

        # Code snippet
        target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
        if target_line and item["file"] not in (".", ""):
            from ..utils import read_code_snippet
            snippet = read_code_snippet(item["file"], target_line)
            if snippet:
                print(colorize("\n  Code:", "dim"))
                print(snippet)

        # Dimension context
        if dim_scores:
            from ..scoring import get_dimension_for_detector
            det = item.get("detector", "")
            dim = get_dimension_for_detector(det)
            if dim and dim.name in dim_scores:
                ds = dim_scores[dim.name]
                strict_val = ds.get('strict', ds['score'])
                print(colorize(f"\n  Dimension: {dim.name} — {ds['score']:.1f}% "
                        f"(strict: {strict_val:.1f}%) "
                        f"({ds['issues']} of {ds['checks']:,} checks failing)", "dim"))

        # Fixer context — suggest batch fixer when available
        from ..registry import DETECTORS
        det_name = item.get("detector", "")
        if det_name in DETECTORS:
            meta = DETECTORS[det_name]
            if meta.action_type == "auto_fix" and meta.fixers:
                similar_count = sum(1 for f in findings_scoped.values()
                                    if f.get("detector") == det_name and f["status"] == "open")
                if similar_count > 1:
                    fixer = meta.fixers[0]
                    print(colorize(f"\n  Auto-fixable: {similar_count} similar findings. "
                            f"Run `desloppify fix {fixer} --dry-run` to fix all at once.", "cyan"))

    if len(items) == 1:
        item = items[0]
        # Check if auto-fixable — show fixer command first
        det_name = item.get("detector", "")
        if det_name in DETECTORS and DETECTORS[det_name].action_type == "auto_fix" and DETECTORS[det_name].fixers:
            print(colorize("\n  Fix with:", "dim"))
            fixer = DETECTORS[det_name].fixers[0]
            print(f"    desloppify fix {fixer} --dry-run")
            print(colorize("  Or resolve individually:", "dim"))
        else:
            print(colorize("\n  Resolve with:", "dim"))
        print(f"    desloppify resolve fixed \"{item['id']}\" --note \"<what you did>\"")
        print(f"    desloppify resolve wontfix \"{item['id']}\" --note \"<why>\"")

        # Batch resolve hint — surface glob pattern for bulk wontfix
        det_name = item.get("detector", "")
        detail = item.get("detail", {})
        smell_id = detail.get("smell_id") or detail.get("kind") or detail.get("category") or ""
        if det_name and smell_id:
            pattern = f"{det_name}::*::{smell_id}"
            batch_count = sum(1 for f in findings_scoped.values()
                              if f.get("detector") == det_name and f["status"] == "open"
                              and (f.get("detail", {}).get("smell_id") or
                                   f.get("detail", {}).get("kind") or
                                   f.get("detail", {}).get("category") or "") == smell_id)
            if batch_count > 1:
                print(colorize(f"\n  Batch resolve ({batch_count} similar):", "dim"))
                print(f'    desloppify resolve wontfix "{pattern}" --note "<why all>"')

    # Review findings nudge — remind agent about the parallel work queue
    open_review = [f for f in findings_scoped.values()
                   if f["status"] == "open" and f.get("detector") == "review"]
    if open_review:
        uninvestigated = sum(1 for f in open_review
                             if not f.get("detail", {}).get("investigation"))
        s = "s" if len(open_review) != 1 else ""
        msg = f"\n  Also: {len(open_review)} review finding{s} open"
        if uninvestigated > 0:
            msg += f" ({uninvestigated} uninvestigated)"
        msg += ". Run `desloppify issues` for the review work queue."
        print(colorize(msg, "cyan"))

    print()
