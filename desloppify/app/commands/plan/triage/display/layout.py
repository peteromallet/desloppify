"""Layout-oriented triage dashboard rendering helpers."""

from __future__ import annotations

from collections import defaultdict

from desloppify.app.commands.helpers.issue_id_display import short_issue_id
from desloppify.engine._plan.constants import is_synthetic_id
from desloppify.engine.plan_triage import TriageSnapshot
from desloppify.engine.plan_triage import (
    TRIAGE_CMD_CLUSTER_ADD,
    TRIAGE_CMD_CLUSTER_CREATE,
    TRIAGE_CMD_CLUSTER_ENRICH_COMPACT,
    TRIAGE_CMD_CLUSTER_STEPS,
    TRIAGE_CMD_COMPLETE_VERBOSE,
    TRIAGE_CMD_CONFIRM_EXISTING,
    TRIAGE_CMD_ENRICH,
    TRIAGE_CMD_OBSERVE,
    TRIAGE_CMD_ORGANIZE,
    TRIAGE_CMD_REFLECT,
    TRIAGE_CMD_RUN_STAGES_CLAUDE,
    TRIAGE_CMD_RUN_STAGES_CODEX,
    triage_runner_commands,
    TRIAGE_CMD_STRATEGIZE,
)
from desloppify.base.output.terminal import colorize

from .primitives import print_stage_progress
from ..review_coverage import (
    cluster_issue_ids,
    find_cluster_for,
    manual_clusters_with_issues,
    open_review_ids_from_state,
    triage_coverage,
)
from ..stages.helpers import unenriched_clusters


def _print_runner_paths(
    *,
    only_stages: str | None = None,
    manual_fallback: str | None = None,
    intro: str = "  Preferred runners:",
) -> None:
    print(colorize(intro, "yellow"))
    for label, command in triage_runner_commands(only_stages=only_stages):
        print(f"    {label}:  {command}")
    if manual_fallback:
        print(colorize(f"  Manual fallback: {manual_fallback}", "dim"))


def print_dashboard_header(
    si: object,
    stages: dict,
    meta: dict,
    plan: dict,
    *,
    snapshot: TriageSnapshot | None = None,
) -> None:
    """Print the header section: title, open issues count, stage progress, overall status."""
    review_issues = getattr(si, "review_issues", getattr(si, "open_issues", {}))
    print(colorize("  Cluster triage", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  Open review issues: {len(review_issues)}")
    print(colorize("  Goal: identify contradictions, resolve them, then group the coherent", "cyan"))
    print(colorize("  remainder into clusters by root cause with action steps and priorities.", "cyan"))
    print(colorize("  Preferred: staged runner workflow (Codex or Claude).", "cyan"))
    print(colorize(f"    Codex:  {TRIAGE_CMD_RUN_STAGES_CODEX}", "dim"))
    print(colorize(f"    Claude: {TRIAGE_CMD_RUN_STAGES_CLAUDE}", "dim"))
    print(colorize("  Manual stage commands below are fallback/debug paths.", "dim"))
    existing_clusters = si.existing_clusters
    if existing_clusters:
        print(f"  Existing clusters: {len(existing_clusters)}")
    new_since_last = (
        set(snapshot.new_since_triage_ids) if snapshot is not None else set(si.new_since_last)
    )
    if new_since_last:
        print(colorize(f"  New since last triage: {len(new_since_last)}", "yellow"))
        for fid in sorted(new_since_last):
            issue = review_issues.get(fid, {})
            dim = ""
            detail = issue.get("detail")
            if isinstance(detail, dict):
                dim = detail.get("dimension", "")
            dim_tag = f" ({dim})" if dim else ""
            print(colorize(f"    * [{short_issue_id(fid)}] {issue.get('summary', '')}{dim_tag}", "yellow"))
    if si.resolved_since_last:
        print(f"  Resolved since last triage: {len(si.resolved_since_last)}")

    print()
    print_stage_progress(stages, plan)
    if meta.get("stage_refresh_required"):
        print(
            colorize(
                "  Note: review issues changed since stage progress started; "
                "refresh stage reports before completion.",
                "yellow",
            )
        )


def _print_completed_guidance(si: object) -> None:
    """Triage completed, no new issues — point to execution."""
    print(colorize("  Triage complete. Executing current plan.", "green"))
    print(colorize("    desloppify next", "dim"))
    if si.resolved_since_last:
        print(colorize(f"  {len(si.resolved_since_last)} issue(s) resolved since last triage.", "dim"))


def _print_retriage_guidance(si: object, meta: dict) -> None:
    """Triage completed but new issues arrived — offer re-triage paths."""
    has_only_additions = bool(si.new_since_last) and not si.resolved_since_last
    if has_only_additions and meta.get("strategy_summary"):
        print(colorize("  Two paths available:", "yellow"))
        print()
        print(colorize("  To reuse the existing enriched cluster plan (without rewriting clusters):", "cyan"))
        print('    desloppify plan triage --confirm-existing --note "..." --strategy "same" --confirmed "I have reviewed..."')
        print()
        print(colorize("  To re-prioritize and restructure:", "cyan"))
        print(f"    Codex:  {TRIAGE_CMD_RUN_STAGES_CODEX}")
        print(f"    Claude: {TRIAGE_CMD_RUN_STAGES_CLAUDE}")
        print(colorize(f"    Manual fallback: {TRIAGE_CMD_STRATEGIZE}", "dim"))
    else:
        _print_runner_paths(
            only_stages="strategize",
            manual_fallback=TRIAGE_CMD_STRATEGIZE,
            intro="  Next step:",
        )
        print(colorize("    (cross-cycle history, rework loops, score churn, and strategic constraints)", "dim"))


def _print_in_progress_guidance(
    stages: dict,
    meta: dict,
    plan: dict,
    *,
    snapshot: TriageSnapshot,
) -> None:
    """Triage stages are active — guide through the stage chain."""
    current_stage = snapshot.progress.current_stage
    if current_stage is None and snapshot.progress.blocked_reason:
        print(colorize(f"  {snapshot.progress.blocked_reason}", "yellow"))
        if snapshot.progress.next_command:
            print(colorize(f"    {snapshot.progress.next_command}", "dim"))
        return

    if "reflect" not in stages or current_stage == "reflect":
        _print_runner_paths(
            only_stages="reflect",
            manual_fallback=TRIAGE_CMD_REFLECT,
            intro="  Next step: use the completed work and patterns below to write your reflect report.",
        )
        print(colorize("    (Contradictions, recurring patterns, which direction to take, what to defer)", "dim"))
    elif "organize" not in stages or current_stage == "organize":
        gaps = unenriched_clusters(plan)
        manual = manual_clusters_with_issues(plan)

        if not manual:
            _print_runner_paths(
                only_stages="organize",
                manual_fallback=TRIAGE_CMD_ORGANIZE,
                intro="  Next steps:",
            )
            print("    0. Defer contradictory issues: `desloppify plan skip <hash>`")
            print(f"    1. Create clusters:  {TRIAGE_CMD_CLUSTER_CREATE}")
            print(f"    2. Add issues:     {TRIAGE_CMD_CLUSTER_ADD}")
            print(f"    3. Enrich clusters:  {TRIAGE_CMD_CLUSTER_STEPS}")
            print(f"    4. Record stage:     {TRIAGE_CMD_ORGANIZE}")
        elif gaps:
            print(colorize("  Enrich these clusters before recording organize:", "yellow"))
            for name, missing in gaps:
                print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
            print(colorize(f"    Fix: {TRIAGE_CMD_CLUSTER_ENRICH_COMPACT}", "dim"))
            print(colorize(f"    Then: {TRIAGE_CMD_ORGANIZE}", "dim"))
        else:
            print(colorize("  All clusters enriched! Record the organize stage:", "green"))
            _print_runner_paths(
                only_stages="organize",
                manual_fallback=TRIAGE_CMD_ORGANIZE,
                intro="  Preferred runner paths:",
            )

        if meta.get("strategy_summary"):
            print()
            print(colorize("  Or fast-track by reusing the current enriched cluster plan:", "dim"))
            print(colorize("    (This confirms the existing manual clusters; it does not materialize a new reflect blueprint.)", "dim"))
            print(f"    {TRIAGE_CMD_CONFIRM_EXISTING}")
    elif "enrich" not in stages or current_stage == "enrich":
        shallow = unenriched_clusters(plan)
        if shallow:
            print(colorize("  Next step: enrich steps with detail and issue_refs.", "yellow"))
            print(colorize('    desloppify plan cluster update <name> --update-step N --detail "sub-details"', "dim"))
        else:
            print(colorize("  Steps look enriched. Record the enrich stage:", "green"))
        _print_runner_paths(
            only_stages="enrich",
            manual_fallback=TRIAGE_CMD_ENRICH,
            intro="  Preferred runner paths:",
        )
        print(colorize("  You can still reorganize: add/remove clusters, reorder items.", "dim"))
    else:
        print(colorize("  Ready to complete:", "green"))
        _print_runner_paths(
            manual_fallback=TRIAGE_CMD_COMPLETE_VERBOSE,
            intro="  Preferred runner paths:",
        )
        print(colorize('    (use --strategy "same" to keep existing strategy)', "dim"))


def print_action_guidance(
    stages: dict,
    meta: dict,
    si: object,
    plan: dict,
    *,
    snapshot: TriageSnapshot,
) -> None:
    """Print the 'What to do' action guidance section based on current stage.

    Three states, matching the engine's canonical triage lifecycle:
      1. Completed & current — triaged_ids present, no new issues
      2. Needs (re-)triage — observe not done yet (fresh start or new issues)
      3. In progress — observe done, working through remaining stages
    """
    print()
    triage_has_run = snapshot.triage_has_run
    has_new_issues = snapshot.is_triage_stale

    later_stage_present = any(
        name in stages for name in ("observe", "reflect", "organize", "enrich", "sense-check", "commit")
    )
    if "strategize" not in stages and not later_stage_present:
        if triage_has_run and not has_new_issues:
            _print_completed_guidance(si)
        else:
            _print_retriage_guidance(si, meta)
    elif "observe" not in stages:
        _print_runner_paths(
            only_stages="observe",
            manual_fallback=TRIAGE_CMD_OBSERVE,
            intro="  Next step:",
        )
        print(colorize("    (themes, root causes, contradictions between issues — NOT a list of IDs)", "dim"))
    else:
        _print_in_progress_guidance(stages, meta, plan, snapshot=snapshot)


def print_prior_stage_reports(stages: dict) -> None:
    """Print prior stage reports (observe/reflect) as context for current action."""
    if "strategize" in stages:
        strat_report = stages["strategize"].get("report", "")
        if strat_report:
            print(colorize("\n  Strategist briefing:", "dim"))
            for line in strat_report.strip().splitlines()[:6]:
                print(colorize(f"    {line}", "dim"))
            if len(strat_report.strip().splitlines()) > 6:
                print(colorize("    ...", "dim"))
    if "observe" in stages:
        obs_report = stages["observe"].get("report", "")
        if obs_report:
            print(colorize("\n  Your observe analysis:", "dim"))
            for line in obs_report.strip().splitlines()[:8]:
                print(colorize(f"    {line}", "dim"))
            if len(obs_report.strip().splitlines()) > 8:
                print(colorize("    ...", "dim"))
    if "reflect" in stages:
        ref_report = stages["reflect"].get("report", "")
        if ref_report:
            print(colorize("\n  Your reflect strategy:", "dim"))
            for line in ref_report.strip().splitlines()[:8]:
                print(colorize(f"    {line}", "dim"))
            if len(ref_report.strip().splitlines()) > 8:
                print(colorize("    ...", "dim"))


def print_issues_by_dimension(open_issues: dict) -> None:
    """Print issues grouped by dimension with suggestions to surface contradictions."""
    by_dim: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for fid, issue in open_issues.items():
        detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        by_dim[dim].append((fid, issue))

    print(colorize("\n  Review issues by dimension:", "cyan"))
    print(colorize("  (Look for contradictions: issues in the same dimension that", "dim"))
    print(colorize("  recommend opposite changes. These must be resolved before clustering.)", "dim"))
    max_per_dim = 5
    for dim in sorted(by_dim, key=lambda d: (-len(by_dim[d]), d)):
        items = by_dim[dim]
        print(colorize(f"\n    {dim} ({len(items)}):", "bold"))
        for fid, issue in items[:max_per_dim]:
            summary = issue.get("summary", "")
            short = short_issue_id(fid)
            detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
            suggestion = (detail.get("suggestion") or "")[:120]
            print(f"      [{short}] {summary}")
            if suggestion:
                print(colorize(f"        → {suggestion}", "dim"))
        if len(items) > max_per_dim:
            print(colorize(f"      ... and {len(items) - max_per_dim} more", "dim"))
    print(colorize("\n  Use hash in commands: desloppify plan skip <hash>  |  desloppify show <hash>", "dim"))


def show_plan_summary(plan: dict, state: dict) -> None:
    """Print a compact plan rendering: clusters + queue order + coverage."""
    clusters = plan.get("clusters", {})
    active = {
        name: cluster
        for name, cluster in clusters.items()
        if cluster_issue_ids(cluster) and not cluster.get("auto")
    }
    issues = (state.get("work_items") or state.get("issues", {}))

    if active:
        print(colorize(f"\n  Clusters ({len(active)}):", "bold"))
        for name, cluster in active.items():
            count = len(cluster_issue_ids(cluster))
            steps = len(cluster.get("action_steps", []))
            desc = (cluster.get("description") or "")[:60]
            print(f"    {name}: {count} items, {steps} steps — {desc}")

    queue_order = [
        fid
        for fid in plan.get("queue_order", [])
        if not is_synthetic_id(fid)
    ]
    if queue_order:
        show = min(15, len(queue_order))
        print(colorize(f"\n  Queue order (first {show} of {len(queue_order)}):", "bold"))
        for i, fid in enumerate(queue_order[:show]):
            issue = issues.get(fid, {})
            summary = (issue.get("summary") or fid)[:60]
            detector = issue.get("detector", "?")
            cluster_name = find_cluster_for(fid, active)
            print(f"    {i + 1}. [{detector}] {summary}{f' ({cluster_name})' if cluster_name else ''}")

    organized, total, _ = triage_coverage(plan, open_review_ids=open_review_ids_from_state(state))
    pct = int(organized / total * 100) if total else 0
    print(colorize(f"\n  Coverage: {organized}/{total} in clusters ({pct}%)", "bold"))


__all__ = [
    "print_action_guidance",
    "print_dashboard_header",
    "print_issues_by_dimension",
    "print_prior_stage_reports",
    "show_plan_summary",
]
