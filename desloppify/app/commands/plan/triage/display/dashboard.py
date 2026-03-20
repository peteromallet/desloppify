"""Display and dashboard rendering for plan triage."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.issue_id_display import short_issue_id
from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine.plan_triage import build_triage_snapshot

from .layout import (
    print_action_guidance,
    print_dashboard_header,
    print_issues_by_dimension,
    print_prior_stage_reports,
    show_plan_summary,
)
from .primitives import print_stage_progress
from ..review_coverage import (
    cluster_issue_ids,
    triage_coverage,
)
from ..stage_queue import print_cascade_clear_feedback
from ..services import TriageServices, default_triage_services


def _cluster_tags(cluster: dict) -> str:
    """Build display tags for cluster metadata."""
    desc = cluster.get("description") or ""
    steps = cluster.get("action_steps", [])
    auto = cluster.get("auto", False)
    tags: list[str] = []
    if auto:
        tags.append("auto")
    if desc:
        tags.append("desc")
    else:
        tags.append("no desc")
    if steps:
        tags.append(f"{len(steps)} steps")
    elif not auto:
        tags.append("no steps")
    return f" [{', '.join(tags)}]"


def _print_active_clusters(active_clusters: dict[str, dict]) -> None:
    """Render currently active clusters with tags and descriptions."""
    if not active_clusters:
        return
    print(colorize("\n  Current clusters:", "cyan"))
    for name, cluster in active_clusters.items():
        count = len(cluster_issue_ids(cluster))
        desc = cluster.get("description") or ""
        desc_str = f" — {desc}" if desc else ""
        print(f"    {name}: {count} items{_cluster_tags(cluster)}{desc_str}")


def _unclustered_issue_ids(clusters: dict, open_issues: dict) -> list[str]:
    """Return issue IDs not currently assigned to any cluster."""
    all_clustered: set[str] = set()
    for cluster in clusters.values():
        all_clustered.update(cluster_issue_ids(cluster))
    return [fid for fid in open_issues if fid not in all_clustered]


def _print_unclustered_issues(unclustered: list[str], open_issues: dict) -> None:
    """Render unclustered issue list with compact IDs."""
    if not unclustered:
        return
    print(colorize(f"\n  {len(unclustered)} issues not yet in a cluster:", "yellow"))
    for fid in unclustered[:10]:
        issue = open_issues[fid]
        detail = issue.get("detail")
        dim = (detail or {}).get("dimension", "") if isinstance(detail, dict) else ""
        short = short_issue_id(fid)
        print(f"    [{short}] [{dim}] {issue.get('summary', '')}")
    if len(unclustered) > 10:
        print(colorize(f"    ... and {len(unclustered) - 10} more", "dim"))


def print_progress(plan: dict, open_issues: dict) -> None:
    """Show cluster state and unclustered issues."""
    clusters = plan.get("clusters", {})
    active_clusters = {name: c for name, c in clusters.items() if cluster_issue_ids(c)}
    _print_active_clusters(active_clusters)

    unclustered = _unclustered_issue_ids(clusters, open_issues)
    if unclustered:
        _print_unclustered_issues(unclustered, open_issues)
    elif open_issues:
        organized, total, _ = triage_coverage(plan, open_review_ids=set(open_issues.keys()))
        print(colorize(f"\n  All {organized}/{total} issues are in clusters.", "green"))


def print_reflect_result(
    *,
    issue_count: int,
    recurring_dims: list[str],
    recurring: dict,
    report: str,
    is_reuse: bool,
    cleared: list,
    stages: dict,
) -> None:
    """Print reflect stage output including briefing box and next steps."""
    print(colorize(f"  Reflect stage recorded: {issue_count} issues, {len(recurring_dims)} recurring dimension(s).", "green"))
    if is_reuse:
        print(colorize("  Reflect data preserved (no changes).", "dim"))
        if cleared:
            print_cascade_clear_feedback(cleared, stages)
    else:
        print(colorize("  Now confirm your strategy.", "yellow"))
        print(colorize("    desloppify plan triage --confirm reflect", "dim"))
    if recurring_dims:
        for dim in recurring_dims:
            info = recurring[dim]
            print(colorize(f"    {dim}: {len(info['resolved'])} resolved, {len(info['open'])} still open", "dim"))

    print()
    print(colorize("  ┌─ Strategic briefing (share with user before organizing) ─┐", "cyan"))
    for line in report.strip().splitlines():
        print(colorize(f"  │ {line}", "cyan"))
    print(colorize("  └" + "─" * 57 + "┘", "cyan"))
    print_user_message(
        "Reflect recorded. Before confirming — check the"
        " subagent's report. Is it a strategy or just observe"
        " restated? It should include a concrete cluster"
        " blueprint: which clusters, which issues, what to skip"
        " (with per-issue reasons). Confirm when the blueprint"
        " is specific enough for organize to execute mechanically."
    )


def print_organize_result(
    *,
    manual_clusters: list[str],
    plan: dict,
    report: str,
    is_reuse: bool,
    cleared: list,
    stages: dict,
) -> None:
    """Print organize stage output including cluster summary and next steps."""
    print(colorize(f"  Organize stage recorded: {len(manual_clusters)} enriched cluster(s).", "green"))
    if is_reuse:
        print(colorize("  Organize data preserved (no changes).", "dim"))
        if cleared:
            print_cascade_clear_feedback(cleared, stages)
    else:
        print(colorize("  Now confirm the plan.", "yellow"))
        print(colorize("    desloppify plan triage --confirm organize", "dim"))
    for name in manual_clusters:
        cluster = plan.get("clusters", {}).get(name, {})
        steps = cluster.get("action_steps", [])
        desc = cluster.get("description", "")
        desc_str = f" — {desc}" if desc else ""
        print(colorize(f"    {name}: {len(cluster_issue_ids(cluster))} issues, {len(steps)} steps{desc_str}", "dim"))

    print()
    print(colorize("  ┌─ Prioritized organization (share with user) ────────────┐", "cyan"))
    for line in report.strip().splitlines():
        print(colorize(f"  │ {line}", "cyan"))
    print(colorize("  └" + "─" * 57 + "┘", "cyan"))
    print_user_message(
        "Organize recorded. Before confirming — does the"
        " organize output match the reflect blueprint? Clusters"
        " by file area (same PR), not by theme? Step count <"
        " issue count (consolidated)? Cluster names describe"
        " locations, not problem types? This should read like"
        " a set of PR plans."
    )


def print_reflect_dashboard(
    si: object,
    plan: dict,
    *,
    services: TriageServices | None = None,
) -> None:
    """Show completed clusters, resolved issues, and recurring patterns."""
    resolved_services = services or default_triage_services()
    completed = getattr(si, "completed_clusters", [])
    resolved = getattr(si, "resolved_issues", {})
    review_issues = getattr(si, "review_issues", getattr(si, "open_issues", {}))

    _print_completed_clusters(completed)
    _print_resolved_issue_deltas(resolved)
    _print_recurring_or_first_triage(
        recurring=resolved_services.detect_recurring_patterns(review_issues, resolved),
        completed=completed,
        resolved=resolved,
    )


def _print_completed_clusters(completed: list[dict]) -> None:
    """Render previously completed cluster snapshots."""
    if not completed:
        return
    print(colorize("\n  Previously completed clusters:", "cyan"))
    for cluster in completed[:10]:
        name = cluster.get("name", "?")
        count = len(cluster_issue_ids(cluster))
        thesis = cluster.get("thesis", "")
        print(f"    {name}: {count} issues")
        if thesis:
            print(colorize(f"      {thesis}", "dim"))
        for step in cluster.get("action_steps", [])[:3]:
            print(colorize(f"      - {step}", "dim"))
    if len(completed) > 10:
        print(colorize(f"    ... and {len(completed) - 10} more", "dim"))


def _print_resolved_issue_deltas(resolved: dict[str, dict]) -> None:
    """Render issues resolved since the previous triage cycle."""
    if not resolved:
        return
    print(colorize(f"\n  Resolved issues since last triage: {len(resolved)}", "cyan"))
    for fid, issue in sorted(resolved.items())[:10]:
        status = issue.get("status", "")
        summary = issue.get("summary", "")
        detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
        dim = detail.get("dimension", "")
        print(f"    [{status}] [{dim}] {summary}")
        print(colorize(f"      {fid}", "dim"))
    if len(resolved) > 10:
        print(colorize(f"    ... and {len(resolved) - 10} more", "dim"))


def _print_recurring_or_first_triage(
    *,
    recurring: dict,
    completed: list[dict],
    resolved: dict,
) -> None:
    """Render recurring-pattern warnings or first-triage guidance."""
    if recurring:
        print(colorize("\n  Recurring patterns detected:", "yellow"))
        for dim, info in sorted(recurring.items()):
            resolved_count = len(info["resolved"])
            open_count = len(info["open"])
            label = "potential loop" if open_count >= resolved_count else "root cause unaddressed"
            print(colorize(f"    {dim}: {resolved_count} resolved, {open_count} still open — {label}", "yellow"))
        return
    if completed or resolved:
        return
    print(colorize("\n  First triage — no prior work to compare against.", "dim"))
    print(colorize("  Focus your reflect report on your strategy:", "yellow"))
    print(colorize("  - How will you resolve contradictions you identified in observe?", "dim"))
    print(colorize("  - Which issues will you cluster together vs defer?", "dim"))
    print(colorize("  - What's the overall arc of work and why?", "dim"))


def _print_strategist_briefing(meta: dict) -> None:
    briefing = meta.get("strategist_briefing", {})
    if not isinstance(briefing, dict):
        return
    focus = [
        str(entry.get("name", "")).strip()
        for entry in briefing.get("focus_dimensions", [])
        if isinstance(entry, dict) and str(entry.get("name", "")).strip()
    ]
    if not briefing and not focus:
        return
    print(colorize("\n  ╭─ Strategist Briefing ─────────────────────────────╮", "cyan"))
    print(
        colorize(
            "  │ "
            f"Score trend: {briefing.get('score_trend', 'stable'):<10} "
            f"Debt trend: {briefing.get('debt_trend', 'stable'):<10}"
            " │",
            "cyan",
        )
    )
    focus_line = ", ".join(focus[:3]) or "none"
    print(colorize(f"  │ Focus: {focus_line[:42]:<42} │", "cyan"))
    print(
        colorize(
            "  │ "
            f"Rework warnings: {len(briefing.get('rework_warnings', []) or [])}  "
            f"Anti-patterns: {len(briefing.get('anti_patterns', []) or [])}"
            " │",
            "cyan",
        )
    )
    print(colorize("  ╰───────────────────────────────────────────────────╯", "cyan"))


def cmd_triage_dashboard(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Default view: show issues, stage progress, and next command."""
    resolved_services = services or default_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    plan = resolved_services.load_plan()
    si = resolved_services.collect_triage_input(plan, state)
    snapshot = build_triage_snapshot(plan, state)
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})

    print_dashboard_header(si, stages, meta, plan, snapshot=snapshot)
    _print_strategist_briefing(meta)
    print_action_guidance(stages, meta, si, plan, snapshot=snapshot)
    print_prior_stage_reports(stages)
    review_issues = getattr(si, "review_issues", getattr(si, "open_issues", {}))
    print_issues_by_dimension(review_issues)

    if "observe" in stages and "reflect" not in stages:
        print_reflect_dashboard(si, plan, services=resolved_services)

    print_progress(plan, review_issues)


__all__ = [
    "cmd_triage_dashboard",
    "print_organize_result",
    "print_progress",
    "print_reflect_dashboard",
    "print_reflect_result",
    "print_stage_progress",
    "show_plan_summary",
]
