"""Strategize stage command flow."""

from __future__ import annotations

import argparse
import json
import logging

from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.triage.strategist_data import collect_strategist_input
from desloppify.engine._state.progression import append_progression_event, load_progression
from desloppify.engine._state.schema import utc_now

from ..lifecycle import TriageLifecycleDeps, ensure_triage_started
from ..services import TriageServices, default_triage_services
from ..stage_queue import has_triage_in_queue, inject_triage_stages, print_cascade_clear_feedback
from .records import record_strategize_stage, resolve_reusable_report

_logger = logging.getLogger(__name__)


def _focus_dimension_names(briefing: dict, *, limit: int = 0) -> list[str]:
    """Extract focus dimension names from a briefing dict."""
    names = [
        name
        for entry in briefing.get("focus_dimensions", [])
        if isinstance(entry, dict) and (name := str(entry.get("name", "")).strip())
    ]
    return names[:limit] if limit else names


_REQUIRED_STRING_FIELDS = (
    "score_trend",
    "debt_trend",
    "executive_summary",
    "observe_guidance",
    "reflect_guidance",
    "organize_guidance",
    "sense_check_guidance",
)


def _parse_briefing(report: str) -> dict | None:
    try:
        briefing = json.loads(report)
    except json.JSONDecodeError as exc:
        print(colorize(f"  Strategize report must be valid JSON: {exc}", "red"))
        return None
    if not isinstance(briefing, dict):
        print(colorize("  Strategize report must decode to a JSON object.", "red"))
        return None
    missing = [
        field
        for field in _REQUIRED_STRING_FIELDS
        if not isinstance(briefing.get(field), str) or not briefing.get(field, "").strip()
    ]
    if missing:
        print(colorize(f"  Strategize report missing required fields: {', '.join(missing)}", "red"))
        return None
    focus_dimensions = briefing.get("focus_dimensions")
    if not isinstance(focus_dimensions, list) or not focus_dimensions:
        print(colorize("  Strategize report must include at least one focus_dimensions entry.", "red"))
        return None
    if briefing.get("score_trend") not in {"improving", "stable", "declining"}:
        print(colorize("  score_trend must be improving, stable, or declining.", "red"))
        return None
    if briefing.get("debt_trend") not in {"growing", "stable", "shrinking"}:
        print(colorize("  debt_trend must be growing, stable, or shrinking.", "red"))
        return None
    briefing.setdefault("computed_at", utc_now())
    briefing.setdefault("lookback_scans", 5)
    return briefing


def _append_progression_event(
    *,
    state: dict,
    plan: dict,
    briefing: dict,
) -> None:
    try:
        append_progression_event(
            {
                "schema_version": 1,
                "event_type": "strategist_complete",
                "timestamp": utc_now(),
                "source_command": "plan triage",
                "scan_count": int(state.get("scan_count", 0) or 0),
                "payload": {
                    "score_trend": briefing.get("score_trend", "stable"),
                    "debt_trend": briefing.get("debt_trend", "stable"),
                    "focus_dimensions": _focus_dimension_names(briefing),
                    "anti_pattern_count": len(briefing.get("anti_patterns", []) or []),
                    "rework_warning_count": len(briefing.get("rework_warnings", []) or []),
                },
            }
        )
    except (OSError, ValueError, TypeError):
        _logger.warning("Failed to append strategist_complete progression event", exc_info=True)


_STRATEGIC_ISSUE_REQUIRED_FIELDS = ("identifier", "summary", "priority", "recommendation", "dimensions_affected")
_STRATEGIC_ISSUE_PRIORITIES = {"critical", "high", "medium"}
_PRIORITY_TO_TIER = {"critical": 1, "high": 2, "medium": 3}


def _parse_strategic_issues(briefing: dict) -> list[dict]:
    """Extract and validate strategic_issues from the briefing (optional field)."""
    raw = briefing.get("strategic_issues")
    if not raw:
        return []
    if not isinstance(raw, list):
        print(colorize("  WARNING: strategic_issues must be a list; ignoring.", "yellow"))
        return []
    valid: list[dict] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            print(colorize(f"  WARNING: strategic_issues[{idx}] is not an object; skipping.", "yellow"))
            continue
        missing = [f for f in _STRATEGIC_ISSUE_REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            print(colorize(f"  WARNING: strategic_issues[{idx}] missing {', '.join(missing)}; skipping.", "yellow"))
            continue
        if entry["priority"] not in _STRATEGIC_ISSUE_PRIORITIES:
            print(colorize(
                f"  WARNING: strategic_issues[{idx}] priority '{entry['priority']}' invalid "
                f"(must be critical|high|medium); skipping.",
                "yellow",
            ))
            continue
        if not isinstance(entry["dimensions_affected"], list):
            print(colorize(f"  WARNING: strategic_issues[{idx}] dimensions_affected must be a list; skipping.", "yellow"))
            continue
        valid.append(entry)
    return valid


def _create_strategic_work_items(
    state: dict,
    plan: dict,
    strategic_issues: list[dict],
) -> None:
    """Create work items in state and insert IDs at front of queue_order."""
    work_items = state.setdefault("work_items", {})
    if not work_items:
        issues = state.get("issues")
        if isinstance(issues, dict):
            work_items = issues
        else:
            state["work_items"] = work_items

    queue_order = plan.setdefault("queue_order", [])
    new_ids: list[str] = []

    for entry in strategic_issues:
        issue_id = f"strategy::{entry['identifier']}"
        work_items[issue_id] = {
            "status": "open",
            "detector": "strategy",
            "tier": _PRIORITY_TO_TIER.get(entry["priority"], 3),
            "priority": entry["priority"],
            "summary": entry["summary"],
            "recommendation": entry["recommendation"],
            "dimensions_affected": entry["dimensions_affected"],
            "detail": {
                "dimension": entry["dimensions_affected"][0] if entry["dimensions_affected"] else "unknown",
                "recommendation": entry["recommendation"],
                "source": "strategist",
            },
            "created_at": utc_now(),
        }
        if issue_id not in queue_order:
            new_ids.append(issue_id)

    # Insert strategy IDs at the front of queue, before other non-synthetic items
    # but after workflow/triage synthetics
    if new_ids:
        non_strategy = [fid for fid in queue_order if not fid.startswith("strategy::")]
        queue_order[:] = new_ids + non_strategy
        from desloppify.engine._plan.constants import normalize_queue_workflow_and_triage_prefix
        normalize_queue_workflow_and_triage_prefix(queue_order)


def cmd_stage_strategize(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Record the STRATEGIZE stage: big-picture cross-cycle analysis."""
    report: str | None = getattr(args, "report", None)

    resolved_services = services or default_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    plan = resolved_services.load_plan()

    if not has_triage_in_queue(plan):
        start_outcome = ensure_triage_started(
            plan,
            services=resolved_services,
            state=state,
            start_message="  Planning mode auto-started (7 stages queued).",
            deps=TriageLifecycleDeps(
                has_triage_in_queue=has_triage_in_queue,
                inject_triage_stages=inject_triage_stages,
            ),
        )
        if start_outcome.status == "blocked":
            return

    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    existing_stage = stages.get("strategize")

    report, is_reuse = resolve_reusable_report(report, existing_stage)
    if not report:
        print(colorize("  --report is required for --stage strategize.", "red"))
        print(colorize("  Provide the strategist JSON briefing payload.", "dim"))
        return

    progression_events = load_progression()
    strategist_input = collect_strategist_input(state, plan, progression_events=progression_events)
    briefing = _parse_briefing(report)
    if briefing is None:
        return

    # --- Fix 1: Validate trends against computed data ---
    computed_score_trend = strategist_input.score_trajectory.trend
    briefing_score_trend = briefing.get("score_trend", "stable")
    if briefing_score_trend != computed_score_trend:
        print(colorize(
            f"  WARNING: Briefing score_trend '{briefing_score_trend}' disagrees with "
            f"computed trend '{computed_score_trend}'. Overriding with computed value.",
            "yellow",
        ))
        briefing["score_trend"] = computed_score_trend

    computed_debt_trend = strategist_input.debt_trajectory.trend
    briefing_debt_trend = briefing.get("debt_trend", "stable")
    if briefing_debt_trend != computed_debt_trend:
        print(colorize(
            f"  WARNING: Briefing debt_trend '{briefing_debt_trend}' disagrees with "
            f"computed trend '{computed_debt_trend}'. Overriding with computed value.",
            "yellow",
        ))
        briefing["debt_trend"] = computed_debt_trend

    # --- Fix 3b: Parse and validate strategic_issues ---
    strategic_issues = _parse_strategic_issues(briefing)

    meta["strategist_briefing"] = briefing
    cleared = record_strategize_stage(
        stages,
        report=report,
        briefing=briefing,
        is_reuse=is_reuse,
        existing_stage=existing_stage,
    )

    resolved_services.save_plan(plan)
    resolved_services.append_log_entry(
        plan,
        "triage_strategize",
        actor="user",
        detail={
            "reuse": is_reuse,
            "score_trend": briefing.get("score_trend", "stable"),
            "focus_dimensions": _focus_dimension_names(briefing),
        },
    )
    # --- Fix 3c/d: Create work items and insert at front of queue ---
    if strategic_issues:
        _create_strategic_work_items(state, plan, strategic_issues)
        resolved_services.save_plan(plan)

    resolved_services.save_plan(plan)
    _append_progression_event(state=state, plan=plan, briefing=briefing)

    print(colorize("  Strategize stage recorded and auto-confirmed.", "green"))
    print(colorize(f"  Score trend: {briefing.get('score_trend', 'stable')}", "dim"))
    print(colorize(f"  Debt trend: {briefing.get('debt_trend', 'stable')}", "dim"))
    focus_names = _focus_dimension_names(briefing, limit=5)
    if focus_names:
        print(colorize(f"  Focus dimensions: {', '.join(focus_names)}", "dim"))
    anti_patterns = briefing.get("anti_patterns", []) or []
    if anti_patterns:
        print(colorize(f"  Anti-patterns flagged: {len(anti_patterns)}", "yellow"))
    if is_reuse:
        print(colorize("  Strategist briefing preserved (no changes).", "dim"))
    if cleared:
        print_cascade_clear_feedback(cleared, stages)
    if strategic_issues:
        print(colorize(f"  Strategic issues created: {len(strategic_issues)}", "green"))
        for si in strategic_issues:
            print(colorize(f"    strategy::{si['identifier']} [{si['priority']}] — {si['summary']}", "dim"))
    if strategist_input.rework_loops and not anti_patterns:
        dims = ", ".join(loop.dimension for loop in strategist_input.rework_loops[:3])
        print(colorize(f"  Warning: data shows rework loops ({dims}) but briefing has no anti_patterns.", "yellow"))


__all__ = ["cmd_stage_strategize"]
