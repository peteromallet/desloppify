"""Rendering and follow-up helpers for the status command."""

from __future__ import annotations

from collections import defaultdict

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.rendering import print_agent_plan, print_ranked_actions
from desloppify.app.commands.helpers.subjective import print_subjective_followup
from desloppify.app.commands.scan import (
    scan_reporting_dimensions as reporting_dimensions_mod,
)
from desloppify.app.commands.scan.scan_reporting_presentation import dimension_bar
from desloppify.app.commands.status_parts.summary import (
    print_open_scope_breakdown,
    print_scan_completeness,
    print_scan_metrics,
    score_summary_lines,
)
from desloppify.engine.planning.scorecard_projection import (
    scorecard_subjective_entries,
)
from desloppify.core.paths_api import get_area
from desloppify.core.registry import dimension_action_type
from desloppify.scoring import (
    DIMENSIONS,
    compute_health_breakdown,
    compute_score_impact,
    merge_potentials,
)
from desloppify.core.output_api import colorize, print_table


def show_tier_progress_table(by_tier: dict) -> None:
    """Fallback display when dimension scores are unavailable."""
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
        bar = colorize("█" * filled, "green") + colorize(
            "░" * (bar_len - filled), "dim"
        )
        rows.append(
            [
                f"Tier {tier_num}",
                bar,
                f"{strict_pct}%",
                str(t_open),
                str(t_fixed),
                str(t_wontfix),
            ]
        )
    print_table(
        ["Tier", "Strict Progress", "%", "Open", "Fixed", "Debt"],
        rows,
        [40, 22, 5, 6, 6, 6],
    )


def _status_next_command(narrative: dict) -> str:
    actions = narrative.get("actions", [])
    return actions[0]["command"] if actions else "desloppify next --count 20"


def write_status_query(
    *,
    state: dict,
    stats: dict,
    by_tier: dict,
    dim_scores: dict,
    scorecard_dims: list[dict],
    subjective_measures: list[dict],
    suppression: dict,
    narrative: dict,
    ignores: list[str],
    overall_score: float | None,
    objective_score: float | None,
    strict_score: float | None,
    verified_strict_score: float | None,
    plan: dict | None = None,
) -> None:
    findings = state.get("findings", {})
    open_scope = (
        state_mod.open_scope_breakdown(findings, state.get("scan_path"))
        if isinstance(findings, dict)
        else None
    )
    write_query(
        {
            "command": "status",
            "overall_score": overall_score,
            "objective_score": objective_score,
            "strict_score": strict_score,
            "verified_strict_score": verified_strict_score,
            "dimension_scores": dim_scores,
            "scorecard_dimensions": scorecard_dims,
            "subjective_measures": subjective_measures,
            "stats": stats,
            "scan_count": state.get("scan_count", 0),
            "last_scan": state.get("last_scan"),
            "by_tier": by_tier,
            "ignores": ignores,
            "suppression": suppression,
            "potentials": state.get("potentials"),
            "codebase_metrics": state.get("codebase_metrics"),
            "open_scope": open_scope,
            "score_breakdown": compute_health_breakdown(dim_scores) if dim_scores else None,
            "next_command": _status_next_command(narrative),
            "narrative": narrative,
            **({"plan": {
                "active": True,
                "focus": plan.get("active_cluster"),
                "total_ordered": len(plan.get("queue_order", [])),
                "total_skipped": len(plan.get("skipped", {})),
                "plan_overrides_narrative": True,
            }} if plan and (plan.get("queue_order") or plan.get("clusters") or plan.get("skipped")) else {}),
        }
    )


def show_ignore_summary(ignores: list[str], suppression: dict) -> None:
    """Show ignore list plus suppression accountability from recent scans."""
    print(colorize(f"\n  Ignore list ({len(ignores)}):", "dim"))
    for p in ignores[:10]:
        print(colorize(f"    {p}", "dim"))

    last_ignored = int(suppression.get("last_ignored", 0) or 0)
    last_raw = int(suppression.get("last_raw_findings", 0) or 0)
    last_pct = float(suppression.get("last_suppressed_pct", 0.0) or 0.0)

    if last_raw > 0:
        style = "red" if last_pct >= 30 else "yellow" if last_pct >= 10 else "dim"
        print(
            colorize(
                f"  Ignore suppression (last scan): {last_ignored}/{last_raw} findings hidden ({last_pct:.1f}%)",
                style,
            )
        )
    elif suppression.get("recent_scans", 0):
        print(colorize("  Ignore suppression (last scan): 0 findings hidden", "dim"))

    recent_scans = int(suppression.get("recent_scans", 0) or 0)
    recent_raw = int(suppression.get("recent_raw_findings", 0) or 0)
    if recent_scans > 1 and recent_raw > 0:
        recent_ignored = int(suppression.get("recent_ignored", 0) or 0)
        recent_pct = float(suppression.get("recent_suppressed_pct", 0.0) or 0.0)
        print(
            colorize(
                f"    Recent ({recent_scans} scans): {recent_ignored}/{recent_raw} findings hidden ({recent_pct:.1f}%)",
                "dim",
            )
        )


def _scorecard_subjective_entries(state: dict, dim_scores: dict) -> list[dict]:
    """Return subjective entries aligned to scorecard labels and ordering."""
    return scorecard_subjective_entries(
        state,
        dim_scores=dim_scores,
    )


def _find_lowest_dimension(
    dim_scores: dict,
    scorecard_subjective: list[dict],
) -> str | None:
    """Return the name of the dimension with the lowest strict score."""
    lowest_name = None
    lowest_score = 101.0
    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        strict_val = ds.get("strict", ds["score"])
        if strict_val < lowest_score:
            lowest_score = strict_val
            lowest_name = dim.name
    for entry in scorecard_subjective:
        strict_val = float(entry.get("strict", entry.get("score", 100.0)))
        if strict_val < lowest_score:
            lowest_score = strict_val
            lowest_name = entry.get("name")
    return lowest_name


def _open_review_issue_counts(state: dict) -> dict[str, int]:
    """Count open review findings grouped by subjective dimension key."""
    findings = state.get("findings", {})
    if not isinstance(findings, dict):
        return {}

    counts: dict[str, int] = {}
    for finding in findings.values():
        if not isinstance(finding, dict):
            continue
        if finding.get("status") != "open" or finding.get("detector") != "review":
            continue
        detail = finding.get("detail", {})
        dimension = ""
        if isinstance(detail, dict):
            dimension = str(detail.get("dimension", "")).strip()
        if not dimension:
            dimension = str(finding.get("dimension", "")).strip()
        if not dimension:
            continue
        counts[dimension] = counts.get(dimension, 0) + 1
    return counts


def _render_objective_dimensions(
    dim_scores: dict, *, lowest_name: str | None, bar_len: int
) -> None:
    """Print rows for objective (detector-based) dimensions."""
    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        score_val = ds["score"]
        strict_val = ds.get("strict", score_val)
        checks = ds["checks"]

        bar = dimension_bar(score_val, colorize_fn=colorize, bar_len=bar_len)

        focus = colorize(" ←", "yellow") if dim.name == lowest_name else "  "
        checks_str = f"{checks:>7,}"
        action = dimension_action_type(dim.name)
        print(
            f"  {dim.name:<22} {checks_str}  {score_val:5.1f}%  {strict_val:5.1f}%  {bar}  T{dim.tier}  {action}{focus}"
        )


def _render_subjective_dimensions(
    scorecard_subjective: list[dict],
    *,
    lowest_name: str | None,
    bar_len: int,
    review_issue_counts: dict[str, int],
) -> None:
    """Print rows for subjective (review-based) dimensions."""
    if not scorecard_subjective:
        return
    print(
        colorize(
            "  ── Subjective Measures (matches scorecard.png) ──────────────────────",
            "dim",
        )
    )
    for entry in scorecard_subjective:
        name = str(entry.get("name", "Unknown"))
        score_val = float(entry.get("score", 0.0))
        strict_val = float(entry.get("strict", score_val))
        tier = 4

        bar = dimension_bar(score_val, colorize_fn=colorize, bar_len=bar_len)

        focus = colorize(" ←", "yellow") if name == lowest_name else "  "
        checks_str = f"{'—':>7}"
        stale_tag = colorize(" [stale]", "yellow") if entry.get("stale") else ""
        placeholder_tag = (
            colorize(" [unassessed]", "yellow") if entry.get("placeholder") else ""
        )
        dim_key = str(entry.get("dimension_key", "")).strip()
        cli_keys = [
            str(key).strip()
            for key in entry.get("cli_keys", [])
            if isinstance(key, str) and str(key).strip()
        ]
        if dim_key:
            issue_count = int(review_issue_counts.get(dim_key, 0))
        elif cli_keys:
            issue_count = int(sum(review_issue_counts.get(key, 0) for key in cli_keys))
        else:
            issue_count = 0
        issue_style = "yellow" if strict_val < 95.0 and issue_count == 0 else "dim"
        issue_tag = colorize(f" [open issues: {issue_count}]", issue_style)
        print(
            f"  {name:<22} {checks_str}  {score_val:5.1f}%  {strict_val:5.1f}%  {bar}  T{tier}  {'review'}{focus}{stale_tag}"
            f"{placeholder_tag}{issue_tag}"
        )


def _render_dimension_legend(scorecard_subjective: list[dict], state: dict | None = None) -> None:
    """Print the legend footer and stale-dimension re-review hint."""
    print(
        colorize("  Health = open penalized | Strict = open + wontfix penalized", "dim")
    )
    print(
        colorize(
            "  Action: fix=auto-fixer | move=reorganize | refactor=manual rewrite | manual=review & fix",
            "dim",
        )
    )
    stale_keys = [
        str(e.get("dimension_key"))
        for e in scorecard_subjective
        if e.get("stale") and e.get("dimension_key")
    ]
    if stale_keys:
        n = len(stale_keys)
        dims_arg = ",".join(stale_keys)
        print(
            colorize(
                f"  [stale] = subjective assessment outdated, not an unresolved finding"
                f" — re-review to refresh",
                "yellow",
            )
        )
        print(
            colorize(
                f"  {n} stale dimension{'s' if n != 1 else ''}"
                f": `desloppify review --prepare --dimensions {dims_arg} --force-review-rerun`",
                "yellow",
            )
        )


def show_dimension_table(state: dict, dim_scores: dict) -> None:
    """Show dimension health table with dual scores and progress bars."""
    print()
    bar_len = 20
    print(
        colorize(
            f"  {'Dimension':<22} {'Checks':>7}  {'Health':>6}  {'Strict':>6}  {'Bar':<{bar_len + 2}} {'Tier'}  {'Action'}",
            "dim",
        )
    )
    print(colorize("  " + "─" * 86, "dim"))

    scorecard_subjective = _scorecard_subjective_entries(state, dim_scores)
    lowest_name = _find_lowest_dimension(dim_scores, scorecard_subjective)
    review_issue_counts = _open_review_issue_counts(state)

    _render_objective_dimensions(dim_scores, lowest_name=lowest_name, bar_len=bar_len)
    _render_subjective_dimensions(
        scorecard_subjective,
        lowest_name=lowest_name,
        bar_len=bar_len,
        review_issue_counts=review_issue_counts,
    )
    _render_dimension_legend(scorecard_subjective, state=state)
    print()


def show_focus_suggestion(
    dim_scores: dict, state: dict, *, plan: dict | None = None
) -> None:
    """Show the lowest-scoring dimension as the focus area."""
    # When plan has an active focus cluster, show that instead
    if plan and plan.get("active_cluster"):
        cluster_name = plan["active_cluster"]
        cluster = plan.get("clusters", {}).get(cluster_name, {})
        remaining = len(cluster.get("finding_ids", []))
        desc = cluster.get("description") or ""
        desc_str = f" — {desc}" if desc else ""
        print(
            colorize(
                f"  Focus: {cluster_name} ({remaining} items remaining){desc_str}",
                "cyan",
            )
        )
        print()
        return

    scorecard_subjective = _scorecard_subjective_entries(state, dim_scores)
    lowest_name = _find_lowest_dimension(dim_scores, scorecard_subjective)
    if not lowest_name:
        return

    # Determine kind, score, and issue count from the resolved name
    lowest_kind = None
    lowest_score = 101.0
    lowest_issues = 0
    for dim in DIMENSIONS:
        if dim.name == lowest_name:
            ds = dim_scores.get(dim.name)
            if ds:
                lowest_score = float(ds.get("strict", ds["score"]))
                lowest_kind = "mechanical"
                lowest_issues = int(ds.get("issues", 0))
            break
    else:
        for entry in scorecard_subjective:
            if entry.get("name") == lowest_name:
                lowest_score = float(entry.get("strict", entry.get("score", 100.0)))
                lowest_kind = "subjective"
                lowest_issues = 0
                break

    if lowest_name and lowest_score < 100:
        if lowest_kind == "subjective":
            print(
                colorize(
                    f"  Focus: {lowest_name} ({lowest_score:.1f}%) — re-review to improve",
                    "cyan",
                )
            )
            print()
            return

        potentials = merge_potentials(state.get("potentials", {}))
        target_dim = next((d for d in DIMENSIONS if d.name == lowest_name), None)
        if target_dim:
            impact = 0.0
            for det in target_dim.detectors:
                impact = compute_score_impact(
                    {
                        k: {
                            "score": v["score"],
                            "tier": v.get("tier", 3),
                            "detectors": v.get("detectors", {}),
                        }
                        for k, v in dim_scores.items()
                        if "score" in v
                    },
                    potentials,
                    det,
                    lowest_issues,
                )
                if impact > 0:
                    break

            impact_str = f" for +{impact:.1f} pts" if impact > 0 else ""
            print(
                colorize(
                    f"  Focus: {lowest_name} ({lowest_score:.1f}%) — "
                    f"fix {lowest_issues} items{impact_str}",
                    "cyan",
                )
            )
            print()


def show_subjective_followup(
    state: dict, dim_scores: dict, *, target_strict_score: float
) -> None:
    """Show concrete subjective follow-up commands when applicable."""
    if not dim_scores:
        return

    subjective = _scorecard_subjective_entries(state, dim_scores)
    if not subjective:
        return

    followup = reporting_dimensions_mod.build_subjective_followup(
        state,
        subjective,
        threshold=target_strict_score,
        max_quality_items=3,
        max_integrity_items=5,
    )
    if print_subjective_followup(followup):
        print()


def show_agent_plan(narrative: dict, *, plan: dict | None = None) -> None:
    """Show concise action plan derived from narrative.actions.

    When a living *plan* is active, renders plan focus/progress instead.
    """
    if plan and (plan.get("queue_order") or plan.get("clusters")):
        print_agent_plan(
            [],
            plan=plan,
            header="  AGENT PLAN (use `desloppify next` to see your next task):",
        )
        return

    actions = narrative.get("actions", [])
    if not actions:
        return

    print(
        colorize(
            "  AGENT PLAN (use `desloppify next --count 20` to inspect more items):",
            "yellow",
        )
    )
    top = actions[0]
    print(colorize(f"  Agent focus: `{top['command']}` — {top['description']}", "cyan"))

    if print_ranked_actions(actions):
        print()


def _collect_structural_areas(
    state: dict,
) -> list[tuple[str, list]] | None:
    """Collect T3/T4 structural findings grouped by area.

    Returns sorted area list, or None if insufficient data to display.
    """
    findings = state_mod.path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")
    )

    structural = [
        f
        for f in findings.values()
        if f["tier"] in (3, 4) and f["status"] in ("open", "wontfix")
    ]

    if len(structural) < 5:
        return None

    areas: dict[str, list] = defaultdict(list)
    for f in structural:
        area = get_area(str(f.get("file", "")))
        areas[area].append(f)

    if len(areas) < 2:
        return None

    return sorted(areas.items(), key=lambda x: -sum(f["tier"] for f in x[1]))


def _build_area_rows(sorted_areas: list[tuple[str, list]], *, max_areas: int = 15) -> list[list[str]]:
    """Build table rows from sorted area findings."""
    rows = []
    for area, area_findings in sorted_areas[:max_areas]:
        t3 = sum(1 for f in area_findings if f["tier"] == 3)
        t4 = sum(1 for f in area_findings if f["tier"] == 4)
        open_count = sum(1 for f in area_findings if f["status"] == "open")
        debt_count = sum(1 for f in area_findings if f["status"] == "wontfix")
        weight = sum(f["tier"] for f in area_findings)
        rows.append(
            [
                area,
                str(len(area_findings)),
                f"T3:{t3} T4:{t4}",
                str(open_count),
                str(debt_count),
                str(weight),
            ]
        )
    return rows


def _render_area_workflow(sorted_areas: list[tuple[str, list]], *, max_areas: int = 15) -> None:
    """Print the overflow count and workflow instructions."""
    remaining = len(sorted_areas) - max_areas
    if remaining > 0:
        print(colorize(f"\n  ... and {remaining} more areas", "dim"))

    print(colorize("\n  Workflow:", "dim"))
    print(colorize("    1. desloppify show <area> --status wontfix --top 50", "dim"))
    print(
        colorize(
            "    2. Create tasks/<date>-<area-name>.md with decomposition plan", "dim"
        )
    )
    print(
        colorize("    3. Farm each task doc to a sub-agent for implementation", "dim")
    )
    print()


def show_structural_areas(state: dict):
    """Show structural debt grouped by area when T3/T4 debt is significant."""
    sorted_areas = _collect_structural_areas(state)
    if sorted_areas is None:
        return

    print(colorize("\n  ── Structural Debt by Area ──", "bold"))
    print(
        colorize(
            "  Create a task doc for each area → farm to sub-agents for decomposition",
            "dim",
        )
    )
    print()

    rows = _build_area_rows(sorted_areas)
    print_table(
        ["Area", "Items", "Tiers", "Open", "Debt", "Weight"], rows, [42, 6, 10, 5, 5, 7]
    )

    _render_area_workflow(sorted_areas)


def show_review_summary(state: dict):
    """Show review findings summary if any exist."""
    findings = state.get("findings", {})
    review_open = [
        f
        for f in findings.values()
        if f.get("status") == "open" and f.get("detector") == "review"
    ]
    if not review_open:
        return
    uninvestigated = sum(
        1 for f in review_open if not f.get("detail", {}).get("investigation")
    )
    parts = [f"{len(review_open)} finding{'s' if len(review_open) != 1 else ''} open"]
    if uninvestigated:
        parts.append(f"{uninvestigated} uninvestigated")
    print(colorize(f"  Review: {', '.join(parts)} — `desloppify show review --status open`", "cyan"))
    dim_scores = state.get("dimension_scores", {})
    if "Test health" in dim_scores:
        print(
            colorize(
                "  Test health tracks coverage + review; review findings track issues found.",
                "dim",
            )
        )
    print()


__all__ = [
    "print_open_scope_breakdown",
    "print_scan_completeness",
    "print_scan_metrics",
    "score_summary_lines",
    "show_agent_plan",
    "show_dimension_table",
    "show_focus_suggestion",
    "show_ignore_summary",
    "show_review_summary",
    "show_structural_areas",
    "show_subjective_followup",
    "show_tier_progress_table",
    "write_status_query",
]
