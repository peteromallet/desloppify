"""next command: show next highest-priority open finding(s)."""

import json
from pathlib import Path

from ..utils import c
from ..cli import _state_path, _write_query


def cmd_next(args):
    """Show next highest-priority open finding(s)."""
    from ..state import load_state
    from ..plan import get_next_items

    sp = _state_path(args)
    state = load_state(sp)

    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(c(f"  {stale_warning}", "yellow"))

    tier = getattr(args, "tier", None)
    count = getattr(args, "count", 1) or 1

    items = get_next_items(state, tier, count)
    if not items:
        print(c("Nothing to do! Score: 100/100", "green"))
        _write_query({"command": "next", "items": [], "score": state.get("score", 0)})
        return

    _write_query({
        "command": "next",
        "score": state.get("score", 0),
        "items": [{"id": f["id"], "tier": f["tier"], "confidence": f["confidence"],
                   "file": f["file"], "summary": f["summary"], "detail": f.get("detail", {})}
                  for f in items],
    })

    output_file = getattr(args, "output", None)
    if output_file:
        output = [{"id": f["id"], "tier": f["tier"], "confidence": f["confidence"],
                   "file": f["file"], "summary": f["summary"], "detail": f.get("detail", {})}
                  for f in items]
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(json.dumps(output, indent=2) + "\n")
        print(c(f"Wrote {len(items)} items to {output_file}", "green"))
        return

    # Look up dimension info for context
    dim_scores = state.get("dimension_scores", {})

    for i, item in enumerate(items):
        if i > 0:
            print()
        label = f"  [{i+1}/{len(items)}]" if len(items) > 1 else "  Next item"
        print(c(f"{label} (Tier {item['tier']}, {item['confidence']} confidence):", "bold"))
        print(c("  " + "─" * 60, "dim"))
        print(f"  {c(item['summary'], 'yellow')}")
        print(f"  File: {item['file']}")
        print(c(f"  ID:   {item['id']}", "dim"))

        detail = item.get("detail", {})
        if detail.get("lines"):
            print(f"  Lines: {', '.join(str(l) for l in detail['lines'][:8])}")
        if detail.get("category"):
            print(f"  Category: {detail['category']}")
        if detail.get("importers") is not None:
            print(f"  Active importers: {detail['importers']}")

        # Dimension context
        if dim_scores:
            from ..scoring import get_dimension_for_detector
            det = item.get("detector", "")
            dim = get_dimension_for_detector(det)
            if dim and dim.name in dim_scores:
                ds = dim_scores[dim.name]
                strict_val = ds.get('strict', ds['score'])
                print(c(f"\n  Dimension: {dim.name} — {ds['score']:.1f}% "
                        f"(strict: {strict_val:.1f}%) "
                        f"({ds['issues']} of {ds['checks']:,} checks failing)", "dim"))

    if len(items) == 1:
        item = items[0]
        print(c("\n  Resolve with:", "dim"))
        print(f"    desloppify resolve \"{item['id']}\" fixed --note \"<what you did>\"")
        print(f"    desloppify resolve \"{item['id']}\" wontfix --note \"<why>\"")
    print()
