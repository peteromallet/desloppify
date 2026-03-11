"""Markdown plan rendering."""

from __future__ import annotations

from datetime import date

from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import LOC_COMPACT_THRESHOLD
from desloppify.base.registry import dimension_action_type
from desloppify.engine._scoring.policy.core import DIMENSIONS
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)
from desloppify.engine.planning.render_items import plan_item_sections as _plan_item_sections_core
from desloppify.engine.planning.render_items import render_queue_item_sections as _render_queue_item_sections
from desloppify.engine.planning.render_sections import (
    addressed_section as _addressed_section,
)
from desloppify.engine.planning.render_sections import (
    plan_skipped_section as _plan_skipped_section,
)
from desloppify.engine.planning.render_sections import (
    plan_superseded_section as _plan_superseded_section,
)
from desloppify.engine.planning.render_sections import (
    plan_user_ordered_section as _plan_user_ordered_section,
)
from desloppify.engine.planning.render_sections import (
    summary_lines as _summary_lines,
)
from desloppify.engine.planning.types import PlanState
from desloppify.state_scoring import score_snapshot


def _plan_header(state: PlanState, stats: dict) -> list[str]:
    """Build the plan header: title, score line, and codebase metrics."""
    scores = score_snapshot(state)
    overall_score = scores.overall
    objective_score = scores.objective
    strict_score = scores.strict

    if (
        overall_score is not None
        and objective_score is not None
        and strict_score is not None
    ):
        header_score = (
            f"**Health:** overall {overall_score:.1f}/100 | "
            f"objective {objective_score:.1f}/100 | "
            f"strict {strict_score:.1f}/100"
        )
    elif overall_score is not None:
        header_score = f"**Score: {overall_score:.1f}/100**"
    else:
        header_score = "**Scores unavailable**"

    metrics = state.get("codebase_metrics", {})
    total_files = sum(metric.get("total_files", 0) for metric in metrics.values())
    total_loc = sum(metric.get("total_loc", 0) for metric in metrics.values())
    total_dirs = sum(metric.get("total_directories", 0) for metric in metrics.values())

    lines = [
        f"# Desloppify Plan — {date.today().isoformat()}",
        "",
        f"{header_score} | "
        f"{stats.get('open', 0)} open | "
        f"{stats.get('fixed', 0)} fixed | "
        f"{stats.get('wontfix', 0)} wontfix | "
        f"{stats.get('auto_resolved', 0)} auto-resolved",
        "",
    ]

    if total_files:
        loc_str = (
            f"{total_loc:,}"
            if total_loc < LOC_COMPACT_THRESHOLD
            else f"{total_loc // 1000}K"
        )
        lines.append(
            f"\n{total_files} files · {loc_str} LOC · {total_dirs} directories\n"
        )

    return lines


def _plan_dimension_table(state: PlanState) -> list[str]:
    """Build the dimension health table rows (empty list when no data)."""
    dim_scores = state.get("dimension_scores", {})
    if not dim_scores:
        return []

    lines = [
        "## Health by Dimension",
        "",
        "| Dimension | Tier | Checks | Issues | Health | Strict | Action |",
        "|-----------|------|--------|--------|--------|--------|--------|",
    ]
    static_names: set[str] = set()
    rendered_names: set[str] = set()
    subjective_display_names = {
        display.lower() for display in DISPLAY_NAMES.values()
    }

    def _looks_subjective(name: str, data: dict) -> bool:
        detectors = data.get("detectors", {})
        if "subjective_assessment" in detectors:
            return True
        lowered = name.strip().lower()
        return lowered in subjective_display_names or lowered.startswith("elegance")

    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        static_names.add(dim.name)
        rendered_names.add(dim.name)
        checks = ds.get("checks", 0)
        issues = ds.get("failing", 0)
        score_val = ds.get("score", 100)
        strict_val = ds.get("strict", score_val)
        bold = "**" if score_val < 93 else ""
        action = dimension_action_type(dim.name)
        lines.append(
            f"| {bold}{dim.name}{bold} | T{dim.tier} | "
            f"{checks:,} | {issues} | {score_val:.1f}% | {strict_val:.1f}% | {action} |"
        )

    from desloppify.engine.planning.dimension_rows import scorecard_dimension_rows

    scorecard_rows = scorecard_dimension_rows(state)
    scorecard_subjective_rows = [
        (name, ds) for name, ds in scorecard_rows if _looks_subjective(name, ds)
    ]
    scorecard_subjective_names = {name for name, _ in scorecard_subjective_rows}

    # Show custom dimensions not present in scorecard.png in the main table.
    custom_non_subjective_rows: list[tuple[str, dict]] = []
    for name, ds in sorted(dim_scores.items(), key=lambda item: str(item[0]).lower()):
        if name in rendered_names or not isinstance(ds, dict):
            continue
        if _looks_subjective(name, ds):
            continue
        custom_non_subjective_rows.append((name, ds))
        rendered_names.add(name)

    for name, ds in custom_non_subjective_rows:
        checks = ds.get("checks", 0)
        issues = ds.get("failing", 0)
        score_val = ds.get("score", 100)
        strict_val = ds.get("strict", score_val)
        tier = int(ds.get("tier", 3) or 3)
        bold = "**" if score_val < 93 else ""
        action = dimension_action_type(name)
        lines.append(
            f"| {bold}{name}{bold} | T{tier} | "
            f"{checks:,} | {issues} | {score_val:.1f}% | {strict_val:.1f}% | {action} |"
        )

    extra_subjective_rows = [
        (name, ds)
        for name, ds in sorted(
            dim_scores.items(), key=lambda item: str(item[0]).lower()
        )
        if (
            isinstance(ds, dict)
            and name not in scorecard_subjective_names
            and name.strip().lower() not in subjective_display_names
            and name.strip().lower() not in {"elegance", "elegance (combined)"}
            and _looks_subjective(name, ds)
        )
    ]
    subjective_rows = [*scorecard_subjective_rows, *extra_subjective_rows]

    if subjective_rows:
        lines.append("| **Subjective Measures (matches scorecard.png)** | | | | | | |")
        for name, ds in subjective_rows:
            issues = ds.get("failing", 0)
            score_val = ds.get("score", 100)
            strict_val = ds.get("strict", score_val)
            tier = ds.get("tier", 4)
            bold = "**" if score_val < 93 else ""
            lines.append(
                f"| {bold}{name}{bold} | T{tier} | "
                f"— | {issues} | {score_val:.1f}% | {strict_val:.1f}% | review |"
            )

    lines.append("")
    return lines


def _plan_item_sections(
    issues: dict,
    *,
    state: PlanState | None = None,
    plan: dict | None = None,
) -> list[str]:
    """Build per-file sections from the shared work-queue backend."""
    return _plan_item_sections_core(issues, state=state, plan=plan)


def _backlog_item_section(items: list[dict]) -> list[str]:
    """Render backlog items as a dedicated markdown section."""
    if not items:
        return []
    lines = ["---", f"## Backlog ({len(items)})", ""]
    lines.extend(_render_queue_item_sections(items, include_header=False))
    return lines


def generate_plan_md(state: PlanState, plan: dict | None = None) -> str:
    """Generate a prioritized markdown plan from state.

    When *plan* is provided (or auto-loaded from disk), user-ordered
    items, clusters, skipped, and superseded sections are rendered.
    When no plan exists, output is identical to the previous behavior.
    """
    issues = state["issues"]
    stats = state.get("stats", {})

    # Auto-load plan if not provided
    if plan is None:
        try:
            from desloppify.engine.plan_state import load_plan
            plan = load_plan()
        except PLAN_LOAD_EXCEPTIONS:
            plan = {}
    if not isinstance(plan, dict):
        plan = {}
    plan.setdefault("queue_order", [])
    plan.setdefault("skipped", {})
    plan.setdefault("clusters", {})

    has_plan = bool(
        plan
        and (
            plan.get("queue_order")
            or plan.get("skipped")
            or plan.get("clusters")
        )
    )

    lines = _plan_header(state, stats)
    lines.extend(_plan_dimension_table(state))
    lines.extend(_summary_lines(stats))

    if has_plan:
        execution_queue = build_execution_queue(
            state,
            options=QueueBuildOptions(
                count=None,
                status="open",
                include_subjective=True,
                plan=plan,
            ),
        )
        execution_items = execution_queue.get("items", [])
        lines.extend(_plan_user_ordered_section(execution_items, plan))
        lines.extend(_plan_item_sections(issues, state=state, plan=plan))

        backlog_queue = build_backlog_queue(
            state,
            options=QueueBuildOptions(
                count=None,
                status="open",
                include_subjective=True,
                plan=plan,
            ),
        )
        backlog_items = backlog_queue.get("items", [])
        lines.extend(_backlog_item_section(backlog_items))

        all_items = [*execution_items, *backlog_items]
        lines.extend(_plan_skipped_section(all_items, plan))
        lines.extend(_plan_superseded_section(plan))
    else:
        lines.extend(_plan_item_sections(issues, state=state))

    lines.extend(_addressed_section(issues))

    return "\n".join(lines)
