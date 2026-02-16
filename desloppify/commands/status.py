"""status command: score dashboard with per-tier progress."""

from __future__ import annotations

import argparse
import json

from ..utils import LOC_COMPACT_THRESHOLD, colorize, print_table
from ._helpers import _write_query, show_narrative_plan, show_narrative_reminders, state_path
from ._strict_target import format_strict_target_progress
from ._status_sections import (
    show_dimension_table as _show_dimension_table,
    show_focus_suggestion as _show_focus_suggestion,
    show_review_summary as _show_review_summary,
    show_structural_areas as _show_structural_areas,
)
from ._status_transparency import (
    build_detector_transparency as _build_detector_transparency,
    show_detector_transparency as _show_detector_transparency,
    show_ignore_summary as _show_ignore_summary,
)


def _build_status_json_payload(
    state: dict,
    stats: dict,
    suppression: dict,
    strict_all_detected: float | None,
    detector_transparency: dict,
    strict_target: dict | None = None,
) -> dict:
    from ..state import get_objective_score, get_overall_score, get_strict_score
    payload = {
        "overall_score": get_overall_score(state),
        "objective_score": get_objective_score(state),
        "strict_score": get_strict_score(state),
        "strict_all_detected": strict_all_detected,
        "dimension_scores": state.get("dimension_scores"),
        "potentials": state.get("potentials"),
        "codebase_metrics": state.get("codebase_metrics"),
        "stats": stats,
        "suppression": suppression,
        "detector_transparency": detector_transparency,
        "scan_count": state.get("scan_count", 0),
        "last_scan": state.get("last_scan"),
    }
    if isinstance(strict_target, dict):
        payload["strict_target"] = strict_target
    return payload


def _print_score_line(overall: float | None, objective: float | None, strict: float | None, strict_all_detected: float | None) -> None:
    if overall is None or objective is None or strict is None:
        print(colorize("\n  Scores unavailable", "bold"))
        print(colorize("  Run a full scan to compute overall/objective/strict scores.", "yellow"))
        return
    score_line = (
        f"\n  Scores: overall {overall:.1f}/100 · objective {objective:.1f}/100 · strict {strict:.1f}/100"
    )
    if strict_all_detected is not None:
        score_line += f" · strict_all_detected {strict_all_detected:.1f}/100"
    print(colorize(score_line, "bold"))


def _show_strict_target_progress(strict_target: dict | None) -> None:
    """Render strict target progress from narrative context."""
    lines, _target, _gap = format_strict_target_progress(strict_target)
    for message, style in lines:
        print(colorize(message, style))


def _print_codebase_metrics(state: dict) -> None:
    metrics = state.get("codebase_metrics", {})
    total_files = sum(m.get("total_files", 0) for m in metrics.values())
    total_loc = sum(m.get("total_loc", 0) for m in metrics.values())
    total_dirs = sum(m.get("total_directories", 0) for m in metrics.values())
    if total_files:
        loc_str = f"{total_loc:,}" if total_loc < LOC_COMPACT_THRESHOLD else f"{total_loc // 1000}K"
        print(colorize(f"  {total_files} files · {loc_str} LOC · {total_dirs} dirs · Last scan: {state.get('last_scan', 'never')}", "dim"))
    else:
        print(colorize(f"  Scans: {state.get('scan_count', 0)} | Last: {state.get('last_scan', 'never')}", "dim"))


def _show_tier_fallback(by_tier: dict) -> None:
    rows = []
    for tier_num in [1, 2, 3, 4]:
        ts = by_tier.get(str(tier_num), {})
        t_open = ts.get("open", 0)
        t_fixed = ts.get("fixed", 0) + ts.get("auto_resolved", 0)
        t_fp = ts.get("false_positive", 0)
        t_wontfix = ts.get("wontfix", 0)
        t_total = sum(ts.values())
        strict_pct = round((t_fixed + t_fp) / t_total * 100) if t_total else 100
        bar_len = 20
        filled = round(strict_pct / 100 * bar_len)
        bar = colorize("█" * filled, "green") + colorize("░" * (bar_len - filled), "dim")
        rows.append([f"Tier {tier_num}", bar, f"{strict_pct}%", str(t_open), str(t_fixed), str(t_wontfix)])
    print_table(["Tier", "Strict Progress", "%", "Open", "Fixed", "Debt"], rows, [40, 22, 5, 6, 6, 6])


def _write_status_query(state: dict, *, overall: float | None, objective: float | None, strict: float | None, strict_all_detected: float | None, stats: dict, suppression: dict, detector_transparency: dict, narrative: dict, dim_scores: dict, by_tier: dict, ignores: list[str]) -> None:
    _write_query(
        {
            "command": "status",
            "overall_score": overall,
            "objective_score": objective,
            "strict_score": strict,
            "strict_all_detected": strict_all_detected,
            "dimension_scores": dim_scores,
            "stats": stats,
            "scan_count": state.get("scan_count", 0),
            "last_scan": state.get("last_scan"),
            "by_tier": by_tier,
            "ignores": ignores,
            "suppression": suppression,
            "detector_transparency": detector_transparency,
            "potentials": state.get("potentials"),
            "codebase_metrics": state.get("codebase_metrics"),
            "strict_target": narrative.get("strict_target") if isinstance(narrative, dict) else None,
            "narrative": narrative,
        }
    )


def cmd_status(args: argparse.Namespace) -> None:
    """Show score dashboard."""
    from ..state import (
        get_objective_score,
        get_overall_score,
        get_strict_all_detected_score,
        get_strict_score,
        load_state,
        suppression_metrics,
    )
    from ..utils import check_tool_staleness

    state = load_state(state_path(args))
    stats = state.get("stats", {})
    suppression = suppression_metrics(state)
    ignore_integrity = state.get("ignore_integrity", {}) or {}
    strict_all_detected = get_strict_all_detected_score(state)
    detector_transparency = _build_detector_transparency(state, ignore_integrity=ignore_integrity)
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    narrative = compute_narrative(
        state,
        lang=(lang.name if lang else None),
        command="status",
        config=getattr(args, "_config", None),
    )

    if getattr(args, "json", False):
        print(
            json.dumps(
                _build_status_json_payload(
                    state,
                    stats,
                    suppression,
                    strict_all_detected,
                    detector_transparency,
                    strict_target=narrative.get("strict_target"),
                ),
                indent=2,
            )
        )
        return
    if not state.get("last_scan"):
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
        return

    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    overall_score = get_overall_score(state)
    objective_score = get_objective_score(state)
    strict_score = get_strict_score(state)
    dim_scores = state.get("dimension_scores", {})
    by_tier = stats.get("by_tier", {})

    _print_score_line(overall_score, objective_score, strict_score, strict_all_detected)
    _show_strict_target_progress(narrative.get("strict_target"))
    _print_codebase_metrics(state)

    completeness = state.get("scan_completeness", {})
    incomplete = [lang for lang, status in completeness.items() if status != "full"]
    if incomplete:
        print(colorize(f"  * Incomplete scan ({', '.join(incomplete)} — slow phases skipped)", "yellow"))
    print(colorize("  " + "─" * 60, "dim"))

    if dim_scores:
        _show_dimension_table(dim_scores)
    else:
        _show_tier_fallback(by_tier)

    _show_structural_areas(state)
    _show_review_summary(state)
    _show_detector_transparency(detector_transparency)
    if dim_scores:
        _show_focus_suggestion(dim_scores, state)

    if narrative.get("headline"):
        print(colorize(f"  → {narrative['headline']}", "cyan"))
        print()
    show_narrative_plan(narrative, max_risks=2)
    show_narrative_reminders(narrative, limit=3, skip_types={"report_scores", "review_findings_pending"})

    ignores = args._config.get("ignore", [])
    if ignores:
        _show_ignore_summary(
            ignores,
            suppression,
            options={
                "ignore_meta": args._config.get("ignore_metadata", {}),
                "score_integrity": state.get("score_integrity", {}),
                "include_suppressed": getattr(args, "include_suppressed", False),
                "ignore_integrity": ignore_integrity,
            },
        )

    review_age = args._config.get("review_max_age_days", 30)
    if review_age != 30:
        label = "never" if review_age == 0 else f"{review_age} days"
        print(colorize(f"  Review staleness: {label}", "dim"))
    print()

    _write_status_query(
        state,
        overall=overall_score,
        objective=objective_score,
        strict=strict_score,
        strict_all_detected=strict_all_detected,
        stats=stats,
        suppression=suppression,
        detector_transparency=detector_transparency,
        narrative=narrative,
        dim_scores=dim_scores,
        by_tier=by_tier,
        ignores=ignores,
    )
