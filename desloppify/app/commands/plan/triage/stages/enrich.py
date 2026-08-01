"""Enrich stage command flow."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine.plan_triage import compute_triage_progress

from ..completion_flow import count_log_activity_since
from ..review_coverage import triage_open_review_ids_from_state
from ..services import TriageServices, default_triage_services
from ..stage_queue import has_triage_in_queue, print_cascade_clear_feedback
from ..validation.enrich_checks import (
    _enrich_report_or_error,
    _require_organize_stage_for_enrich,
    _steps_with_bad_paths,
    _steps_without_effort,
    _underspecified_steps,
)
from ..validation.enrich_quality import evaluate_enrich_quality
from .helpers import active_triage_issue_scope
from .records import record_enrich_stage, resolve_reusable_report

ColorizeFn = Callable[[str, str], str]


@dataclass(frozen=True)
class EnrichStageDeps:
    has_triage_in_queue: Callable[[dict], bool] = has_triage_in_queue
    require_organize_stage_for_enrich: Callable[[dict], bool] = _require_organize_stage_for_enrich
    underspecified_steps: Callable[[dict], list[tuple[str, int, int]]] = _underspecified_steps
    steps_with_bad_paths: Callable[[dict, Path], list[tuple[str, int, list[str]]]] = _steps_with_bad_paths
    steps_without_effort: Callable[[dict], list[tuple[str, int, int]]] = _steps_without_effort
    enrich_report_or_error: Callable[[str | None], str | None] = _enrich_report_or_error
    resolve_reusable_report: Callable[[str | None, dict | None], tuple[str | None, bool]] = (
        resolve_reusable_report
    )
    record_enrich_stage: Callable[..., list[str]] = record_enrich_stage
    count_log_activity_since: Callable[[dict, str | None], dict[str, int]] = (
        count_log_activity_since
    )
    colorize: ColorizeFn = colorize
    print_user_message: Callable[[str], None] = print_user_message
    print_cascade_clear_feedback: Callable[[list[str], dict], None] = print_cascade_clear_feedback
    default_triage_services: Callable[[], TriageServices] = default_triage_services
    get_project_root: Callable[[], Path] | None = None
    auto_confirm_organize_for_complete: Callable[..., bool] | None = None


def _resolve_enrich_stage_context(
    *,
    args: argparse.Namespace,
    services: TriageServices | None,
    deps: EnrichStageDeps,
) -> tuple[TriageServices, dict, dict, dict, str | None, str | None]:
    report: str | None = getattr(args, "report", None)
    attestation: str | None = getattr(args, "attestation", None)
    resolved_services = services or deps.default_triage_services()
    plan = resolved_services.load_plan()
    state = resolved_services.command_runtime(args).state
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    return resolved_services, plan, state, stages, report, attestation


def _require_confirmed_organize_stage(
    *,
    plan: dict,
    stages: dict,
    attestation: str | None,
    services: TriageServices,
    deps: EnrichStageDeps,
) -> bool:
    progress = compute_triage_progress(stages)
    if stages.get("organize", {}).get("confirmed_at"):
        return True
    if progress.current_stage != "enrich":
        if progress.blocked_reason:
            print(deps.colorize(f"  {progress.blocked_reason}", "red"))
            if progress.next_command:
                print(deps.colorize(f"  Run: {progress.next_command}", "dim"))
            return False
    if not attestation:
        print(deps.colorize("  Cannot enrich: organize stage not confirmed.", "red"))
        print(deps.colorize("  Run: desloppify plan triage --confirm organize", "dim"))
        print(deps.colorize("  Or pass --attestation to auto-confirm organize inline.", "dim"))
        return False

    auto_confirm_organize_for_complete = deps.auto_confirm_organize_for_complete
    if auto_confirm_organize_for_complete is None:
        from ..validation.completion_stages import _auto_confirm_stage_for_complete

        auto_confirm_organize_for_complete = _auto_confirm_stage_for_complete
    return auto_confirm_organize_for_complete(
        plan=plan,
        stages=stages,
        stage="organize",
        attestation=attestation,
        save_plan_fn=services.save_plan,
    )


def _require_cluster_update_activity(
    *,
    plan: dict,
    state: dict,
    stages: dict,
    attestation: str | None,
    deps: EnrichStageDeps,
) -> bool:
    organize_ts = stages.get("organize", {}).get("timestamp", "")
    if not organize_ts:
        return True
    activity = deps.count_log_activity_since(plan, organize_ts)
    update_ops = activity.get("cluster_update", 0)
    if update_ops != 0 or not triage_open_review_ids_from_state(plan, state):
        return True
    if attestation and len(attestation.strip()) >= 40:
        print(
            deps.colorize(
                "  Note: 0 cluster_update ops logged since organize. "
                "Proceeding with attestation override.",
                "yellow",
            )
        )
        return True
    print(
        deps.colorize(
            "  Cannot enrich: no cluster_update operations logged since organize.",
            "red",
        )
    )
    print(
        deps.colorize(
            "  Enriching steps requires running cluster update commands.\n"
            '  e.g. desloppify plan cluster update <name> --update-step N --detail "..."',
            "dim",
        )
    )
    print(
        deps.colorize(
            '  Override: pass --attestation "reason why no update ops" (40+ chars).',
            "dim",
        )
    )
    return False


def _print_underspecified_step_error(
    underspec: list[tuple[str, int, int]],
    *,
    deps: EnrichStageDeps,
) -> None:
    total_bare = sum(n for _, n, _ in underspec)
    print(
        deps.colorize(
            f"  Cannot enrich: {total_bare} step(s) across {len(underspec)} cluster(s) lack detail or issue_refs:",
            "red",
        )
    )
    for name, bare, total in underspec:
        print(deps.colorize(f"    {name}: {bare}/{total} steps need enrichment", "yellow"))
    print()
    print(
        deps.colorize(
            "  Every step needs --detail (sub-points) or --issue-refs (for auto-completion).",
            "dim",
        )
    )
    print(deps.colorize("  Fix:", "dim"))
    print(
        deps.colorize(
            '    desloppify plan cluster update <name> --update-step N --detail "sub-details"',
            "dim",
        )
    )
    print(
        deps.colorize(
            "  You can also still reorganize: add/remove clusters, reorder, etc.",
            "dim",
        )
    )


def _print_enrich_warnings(
    *,
    report,
    deps: EnrichStageDeps,
) -> None:
    bad_paths = report.warning("bad_paths")
    if bad_paths:
        print(
            deps.colorize(
                f"  Warning: {bad_paths.total} file path(s) in step details don't exist on disk:",
                "yellow",
            )
        )
        for name, step_num, paths in bad_paths.rows[:5]:
            print(deps.colorize(f"    {name} step {step_num}: {', '.join(paths[:3])}", "yellow"))
        print(
            deps.colorize(
                "  Fix paths before confirming enrich (confirmation will block on bad paths).",
                "dim",
            )
        )

    untagged = report.warning("missing_effort")
    if untagged:
        print(deps.colorize(f"  Note: {untagged.total} step(s) have no effort tag.", "yellow"))
        print(
            deps.colorize(
                "  Consider: desloppify plan cluster update <name> --update-step N --effort small",
                "dim",
            )
        )


def run_stage_enrich(
    args: argparse.Namespace,
    *,
    services: TriageServices | None,
    deps: EnrichStageDeps | None = None,
) -> None:
    """Record the ENRICH stage with validation and optional auto-confirm."""
    resolved_deps = deps or EnrichStageDeps()
    resolved_services, plan, state, stages, report, attestation = _resolve_enrich_stage_context(
        args=args,
        services=services,
        deps=resolved_deps,
    )

    if not resolved_deps.has_triage_in_queue(plan):
        print(resolved_deps.colorize("  No planning stages in the queue — nothing to enrich.", "yellow"))
        return

    existing_stage = stages.get("enrich")
    report, is_reuse = resolved_deps.resolve_reusable_report(report, existing_stage)

    if not resolved_deps.require_organize_stage_for_enrich(stages):
        return

    if not _require_confirmed_organize_stage(
        plan=plan,
        stages=stages,
        attestation=attestation,
        services=resolved_services,
        deps=resolved_deps,
    ):
        return

    if not is_reuse and not _require_cluster_update_activity(
        plan=plan,
        state=state,
        stages=stages,
        attestation=attestation,
        deps=resolved_deps,
    ):
        return

    get_project_root = resolved_deps.get_project_root
    if get_project_root is None:
        from desloppify.base.discovery.paths import get_project_root

    triage_ids = active_triage_issue_scope(plan, state)
    quality_report = evaluate_enrich_quality(
        plan,
        get_project_root(),
        phase_label="enrich",
        bad_paths_severity="warning",
        missing_effort_severity="warning",
        include_missing_issue_refs=False,
        include_vague_detail=False,
        stale_issue_refs_severity=None,
        triage_issue_ids=triage_ids,
    )
    underspec = quality_report.failure("underspecified")
    total_bare = underspec.total if underspec else 0

    if underspec:
        _print_underspecified_step_error(underspec.rows, deps=resolved_deps)
        return

    print(resolved_deps.colorize("  All steps have detail or issue_refs.", "green"))
    _print_enrich_warnings(report=quality_report, deps=resolved_deps)

    report = resolved_deps.enrich_report_or_error(report)
    if report is None:
        return

    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    cleared = resolved_deps.record_enrich_stage(
        stages,
        report=report,
        shallow_count=total_bare,
        existing_stage=existing_stage,
        is_reuse=is_reuse,
    )

    resolved_services.save_plan(plan)

    resolved_services.append_log_entry(
        plan,
        "triage_enrich",
        actor="user",
        detail={"shallow_count": total_bare, "reuse": is_reuse},
    )
    resolved_services.save_plan(plan)

    print(
        resolved_deps.colorize(
            f"  Enrich stage recorded: {total_bare} step(s) still without detail.",
            "green",
        )
    )
    if is_reuse:
        print(resolved_deps.colorize("  Enrich data preserved (no changes).", "dim"))
        if cleared:
            resolved_deps.print_cascade_clear_feedback(cleared, stages)
    else:
        print(resolved_deps.colorize("  Now confirm the enrichment.", "yellow"))
        print(resolved_deps.colorize("    desloppify plan triage --confirm enrich", "dim"))

    resolved_deps.print_user_message(
        "Enrich recorded. Before confirming — check the subagent's"
        " work. Could a developer who has never seen this code"
        " execute every step without asking a question? Every step"
        " needs: file path, specific location, specific action."
        " 'Refactor X' fails. 'Extract lines 45-89 into Y' passes."
    )


def cmd_stage_enrich(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for enrich stage recording."""
    run_stage_enrich(args, services=services)


__all__ = ["ColorizeFn", "EnrichStageDeps", "cmd_stage_enrich", "run_stage_enrich"]
