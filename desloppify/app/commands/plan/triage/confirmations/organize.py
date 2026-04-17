"""Organize-stage triage confirmation handler."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message

from .basic import MIN_ATTESTATION_LEN, validate_attestation
from .shared import (
    StageConfirmationRequest,
    ensure_stage_is_confirmable,
    finalize_stage_confirmation,
)
from ..display.dashboard import show_plan_summary
from ..completion_flow import count_log_activity_since
from ..review_coverage import (
    cluster_issue_ids,
    open_review_ids_from_state,
    triage_coverage,
)
from ..services import TriageServices, default_triage_services
from ..validation.enrich_checks import (
    _cluster_file_overlaps,
    _clusters_with_directory_scatter,
    _clusters_with_high_step_ratio,
)


def _require_enriched_clusters(plan: dict, state: dict | None = None) -> bool:
    from ..stages.helpers import unenriched_clusters  # noqa: PLC0415

    gaps = unenriched_clusters(plan, state)
    if not gaps:
        return True
    print(colorize(f"\n  Cannot confirm: {len(gaps)} cluster(s) still need enrichment.", "red"))
    for name, missing in gaps:
        print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
    print(colorize("  Small clusters (<5 issues) need at least 1 action step per issue.", "dim"))
    print(colorize('  Fix: desloppify plan cluster update <name> --steps "step1" "step2"', "dim"))
    return False


def _require_clustered_review_issues(plan: dict, state: dict) -> bool:
    from ..stages.helpers import unclustered_review_issues  # noqa: PLC0415

    unclustered = unclustered_review_issues(plan, state)
    if not unclustered:
        return True
    print(colorize(f"\n  Cannot confirm: {len(unclustered)} review issue(s) have no action plan.", "red"))
    for fid in unclustered[:5]:
        short = fid.rsplit("::", 2)[-2] if "::" in fid else fid
        print(colorize(f"    {short}", "yellow"))
    if len(unclustered) > 5:
        print(colorize(f"    ... and {len(unclustered) - 5} more", "yellow"))
    print(colorize("  Add each to a cluster or wontfix it before confirming.", "dim"))
    return False


def _print_reflect_activity_summary(plan: dict, stages: dict) -> None:
    reflect_ts = stages.get("reflect", {}).get("timestamp", "")
    if not reflect_ts:
        return
    activity = count_log_activity_since(plan, reflect_ts)
    if activity:
        print("  Since reflect, you have:")
        for action, count in sorted(activity.items()):
            print(f"    {action}: {count}")
        return
    print("  No logged plan operations since reflect.")


def _print_cluster_shape_warnings(plan: dict) -> None:
    scattered = _clusters_with_directory_scatter(plan)
    if scattered:
        print(colorize(f"\n  Warning: {len(scattered)} cluster(s) span many unrelated directories:", "yellow"))
        for name, dir_count, sample_dirs in scattered:
            print(colorize(f"    {name}: {dir_count} directories — likely grouped by theme, not area", "yellow"))
            for directory in sample_dirs[:3]:
                print(colorize(f"      {directory}", "dim"))
        print(colorize("  Consider splitting into area-focused clusters (same files in same PR).", "dim"))

    high_ratio = _clusters_with_high_step_ratio(plan)
    if high_ratio:
        print(colorize(f"\n  Warning: {len(high_ratio)} cluster(s) have step count ≥ issue count:", "yellow"))
        for name, steps, issues, ratio in high_ratio:
            print(colorize(f"    {name}: {steps} steps for {issues} issues ({ratio:.1f}x)", "yellow"))
        print(colorize("  Steps should consolidate changes to the same file. 1:1 means each issue is its own step.", "dim"))

    _print_cluster_overlap_notes(plan, _cluster_file_overlaps(plan))


def _print_cluster_overlap_notes(plan: dict, overlaps: list[tuple[str, str, list[str]]]) -> None:
    if not overlaps:
        return
    clusters_dict = plan.get("clusters", {})
    print(colorize(f"\n  Note: {len(overlaps)} cluster pair(s) reference the same files:", "yellow"))
    for left, right, files in overlaps[:5]:
        print(colorize(f"    {left} ↔ {right}: {len(files)} shared file(s)", "yellow"))
    needs_dep = []
    for left, right, files in overlaps:
        left_deps = set(clusters_dict.get(left, {}).get("depends_on_clusters", []))
        right_deps = set(clusters_dict.get(right, {}).get("depends_on_clusters", []))
        if right not in left_deps and left not in right_deps:
            needs_dep.append((left, right, files))
    if not needs_dep:
        return
    print(colorize("  These pairs have no dependency relationship — add one to prevent merge conflicts:", "dim"))
    for left, right, _files in needs_dep[:5]:
        print(colorize(f"    desloppify plan cluster update {right} --depends-on {left}", "dim"))
        print(colorize(f"    # or: desloppify plan cluster update {left} --depends-on {right}", "dim"))


def _print_orphaned_cluster_notes(all_clusters: dict) -> None:
    for name, cluster in all_clusters.items():
        deps = cluster.get("depends_on_clusters", [])
        if name in deps:
            print(colorize(f"  Warning: {name} depends on itself.", "yellow"))

    orphaned = [
        (name, len(cluster.get("action_steps", [])))
        for name, cluster in all_clusters.items()
        if not cluster.get("auto") and not cluster_issue_ids(cluster) and cluster.get("action_steps")
    ]
    if not orphaned:
        return
    print(colorize(f"\n  Note: {len(orphaned)} cluster(s) have steps but no issues:", "yellow"))
    for name, step_count in orphaned:
        print(colorize(f"    {name}: {step_count} steps, 0 issues", "yellow"))
    print(colorize("  These may need issues added, or may be leftover from resolved work.", "dim"))


def confirm_organize(
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
    *,
    services: TriageServices | None = None,
) -> None:
    """Show full plan summary and record confirmation if attestation is valid."""
    resolved_services = services or default_triage_services()
    if not ensure_stage_is_confirmable(stages, stage="organize"):
        return

    runtime = resolved_services.command_runtime(args)
    state = runtime.state

    print(colorize("  Stage: ORGANIZE — Defer contradictions, cluster, & prioritize", "bold"))
    print(colorize("  " + "─" * 63, "dim"))

    _print_reflect_activity_summary(plan, stages)

    print(colorize("\n  Plan:", "bold"))
    show_plan_summary(plan, state)

    organize_clusters = [
        name for name in plan.get("clusters", {}) if not plan["clusters"][name].get("auto")
    ]
    if not _require_enriched_clusters(plan, state):
        return
    if not _require_clustered_review_issues(plan, state):
        return

    _print_cluster_shape_warnings(plan)
    all_clusters = plan.get("clusters", {})
    _print_orphaned_cluster_notes(all_clusters)

    organized, total, _ = triage_coverage(plan, open_review_ids=open_review_ids_from_state(state))
    if not finalize_stage_confirmation(
        plan=plan,
        stages=stages,
        request=StageConfirmationRequest(
            stage="organize",
            attestation=attestation,
            min_attestation_len=MIN_ATTESTATION_LEN,
            command_hint='desloppify plan triage --confirm organize --attestation "This plan is correct..."',
            validation_stage="organize",
            validate_attestation_fn=validate_attestation,
            validation_kwargs={"cluster_names": organize_clusters},
            log_action="triage_confirm_organize",
            log_detail={"coverage": f"{organized}/{total}"},
            not_satisfied_hint="If not, adjust clusters, priorities, or queue order before completing.",
        ),
        services=resolved_services,
    ):
        return
    print_user_message(
        "Hey — organize is confirmed. Next: enrich your steps"
        " with detail and issue_refs so they're executor-ready."
        " Run `desloppify plan triage --stage enrich --report \"...\"`."
        " You can still reorganize (add/remove clusters, reorder)"
        " during the enrich stage."
    )


__all__ = ["confirm_organize"]
