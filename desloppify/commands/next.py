"""next command: show next highest-priority open finding(s)."""

from __future__ import annotations

import json

from ..utils import colorize
from ._helpers import _write_query, show_narrative_plan, show_narrative_reminders, state_path


def _serialize_item(finding: dict) -> dict:
    """Build a serializable output dict from a finding."""
    return {
        "id": finding["id"],
        "tier": finding["tier"],
        "confidence": finding["confidence"],
        "file": finding["file"],
        "summary": finding["summary"],
        "detail": finding.get("detail", {}),
    }


def _load_state(args):
    from ..state import load_state
    sp = state_path(args)
    return load_state(sp)


def _warn_if_stale(state: dict) -> None:
    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))


def _get_items(args, state: dict) -> list[dict]:
    from ..plan import get_next_items
    tier = getattr(args, "tier", None)
    count = getattr(args, "count", 1) or 1
    return get_next_items(state, tier, count, scan_path=state.get("scan_path"))


def _write_empty_query(state: dict, strict: float | None) -> None:
    from ..state import get_objective_score, get_overall_score
    _write_query(
        {
            "command": "next",
            "items": [],
            "overall_score": get_overall_score(state),
            "objective_score": get_objective_score(state),
            "strict_score": strict,
        }
    )


def _write_items_query(args, state: dict, items: list[dict], *, narrative: dict | None = None) -> None:
    from ..state import get_objective_score, get_overall_score, get_strict_score
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang

    if narrative is None:
        lang = resolve_lang(args)
        narrative = compute_narrative(
            state,
            lang=(lang.name if lang else None),
            command="next",
            config=getattr(args, "_config", None),
        )
    _write_query(
        {
            "command": "next",
            "overall_score": get_overall_score(state),
            "objective_score": get_objective_score(state),
            "strict_score": get_strict_score(state),
            "items": [_serialize_item(item) for item in items],
            "narrative": narrative,
        }
    )


def _write_output_file(output_file: str, items: list[dict]) -> None:
    from ..utils import safe_write_text
    payload = json.dumps([_serialize_item(item) for item in items], indent=2) + "\n"
    try:
        safe_write_text(output_file, payload)
        print(colorize(f"Wrote {len(items)} items to {output_file}", "green"))
    except OSError as exc:
        print(colorize(f"Could not write to {output_file}: {exc}", "red"))
        raise SystemExit(1) from exc


def _print_item_basics(item: dict, index: int, total: int) -> None:
    label = f"  [{index + 1}/{total}]" if total > 1 else "  Next item"
    print(colorize(f"{label} (Tier {item['tier']}, {item['confidence']} confidence):", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item['summary'], 'yellow')}")
    print(f"  File: {item['file']}")
    print(colorize(f"  ID:   {item['id']}", "dim"))


def _print_item_snippet(item: dict, detail: dict) -> None:
    target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
    if not target_line or item["file"] in (".", ""):
        return
    from ..utils import read_code_snippet
    snippet = read_code_snippet(item["file"], target_line)
    if snippet:
        print(colorize("\n  Code:", "dim"))
        print(snippet)


def _print_dimension_context(item: dict, dim_scores: dict) -> None:
    if not dim_scores:
        return
    from ..scoring import get_dimension_for_detector
    dimension = get_dimension_for_detector(item.get("detector", ""))
    if not dimension or dimension.name not in dim_scores:
        return
    score_data = dim_scores[dimension.name]
    strict_val = score_data.get("strict", score_data["score"])
    print(
        colorize(
            f"\n  Dimension: {dimension.name} — {score_data['score']:.1f}% "
            f"(strict: {strict_val:.1f}%) "
            f"({score_data['issues']} of {score_data['checks']:,} checks failing)",
            "dim",
        )
    )


def _print_auto_fix_hint(item: dict, findings_scoped: dict) -> None:
    from ..registry import DETECTORS
    detector = item.get("detector", "")
    if detector not in DETECTORS:
        return
    meta = DETECTORS[detector]
    if meta.action_type != "auto_fix" or not meta.fixers:
        return

    similar_count = sum(
        1 for finding in findings_scoped.values() if finding.get("detector") == detector and finding["status"] == "open"
    )
    if similar_count <= 1:
        return
    print(
        colorize(
            f"\n  Auto-fixable: {similar_count} similar findings. "
            f"Run `desloppify fix {meta.fixers[0]} --dry-run` to fix all at once.",
            "cyan",
        )
    )


def _print_resolution_hints(item: dict, findings_scoped: dict) -> None:
    from ..registry import DETECTORS

    detector = item.get("detector", "")
    if detector in DETECTORS and DETECTORS[detector].action_type == "auto_fix" and DETECTORS[detector].fixers:
        print(colorize("\n  Fix with:", "dim"))
        print(f"    desloppify fix {DETECTORS[detector].fixers[0]} --dry-run")
        print(colorize("  Or resolve individually:", "dim"))
    else:
        print(colorize("\n  Resolve with:", "dim"))

    print(f"    desloppify resolve fixed \"{item['id']}\" --note \"<what you did>\"")
    print(f"    desloppify resolve wontfix \"{item['id']}\" --note \"<why>\"")

    detail = item.get("detail", {})
    smell_id = detail.get("smell_id") or detail.get("kind") or detail.get("category") or ""
    if not detector or not smell_id:
        return

    batch_count = sum(
        1
        for finding in findings_scoped.values()
        if finding.get("detector") == detector
        and finding["status"] == "open"
        and (
            finding.get("detail", {}).get("smell_id")
            or finding.get("detail", {}).get("kind")
            or finding.get("detail", {}).get("category")
            or ""
        )
        == smell_id
    )
    if batch_count <= 1:
        return
    print(colorize(f"\n  Batch resolve ({batch_count} similar):", "dim"))
    print(f'    desloppify resolve wontfix "{detector}::*::{smell_id}" --note "<why all>"')


def _print_review_nudge(findings_scoped: dict) -> None:
    review_open = [
        finding
        for finding in findings_scoped.values()
        if finding["status"] == "open" and finding.get("detector") == "review"
    ]
    if not review_open:
        return
    uninvestigated = sum(1 for finding in review_open if not finding.get("detail", {}).get("investigation"))
    suffix = "s" if len(review_open) != 1 else ""
    msg = f"\n  Also: {len(review_open)} review finding{suffix} open"
    if uninvestigated > 0:
        msg += f" ({uninvestigated} uninvestigated)"
    msg += ". Run `desloppify issues` for the review work queue."
    print(colorize(msg, "cyan"))


def _render_items(items: list[dict], findings_scoped: dict, dim_scores: dict) -> None:
    for index, item in enumerate(items):
        if index > 0:
            print()
        detail = item.get("detail", {})
        _print_item_basics(item, index, len(items))
        if detail.get("lines"):
            print(f"  Lines: {', '.join(str(line) for line in detail['lines'][:8])}")
        if detail.get("category"):
            print(f"  Category: {detail['category']}")
        if detail.get("importers") is not None:
            print(f"  Active importers: {detail['importers']}")
        _print_item_snippet(item, detail)
        _print_dimension_context(item, dim_scores)
        _print_auto_fix_hint(item, findings_scoped)

    if len(items) == 1:
        _print_resolution_hints(items[0], findings_scoped)

    _print_review_nudge(findings_scoped)
    print()


def cmd_next(args) -> None:
    """Show next highest-priority open finding(s)."""
    from ..state import get_strict_score, path_scoped_findings
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang

    state = _load_state(args)
    _warn_if_stale(state)
    items = _get_items(args, state)

    if not items:
        strict = get_strict_score(state)
        suffix = f" Strict score: {strict:.1f}/100" if strict is not None else ""
        print(colorize(f"Nothing to do!{suffix}", "green"))
        _write_empty_query(state, strict)
        return

    lang = resolve_lang(args)
    narrative = compute_narrative(
        state,
        lang=(lang.name if lang else None),
        command="next",
        config=getattr(args, "_config", None),
    )
    _write_items_query(args, state, items, narrative=narrative)
    output_file = getattr(args, "output", None)
    if output_file:
        _write_output_file(output_file, items)
        return

    _render_items(
        items,
        path_scoped_findings(state["findings"], state.get("scan_path")),
        state.get("dimension_scores", {}),
    )
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(
        narrative,
        limit=2,
        skip_types={"report_scores", "rescan_needed", "review_findings_pending"},
    )
