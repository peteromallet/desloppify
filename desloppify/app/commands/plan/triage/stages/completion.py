"""Completion/confirm command handlers for triage flow."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message

from ..completion_flow import apply_completion
from ..review_coverage import (
    manual_clusters_with_issues,
    sync_undispositioned_triage_meta,
    triage_coverage,
    triage_open_review_ids_from_state,
)
from ..services import TriageServices, default_triage_services
from ..stage_queue import has_triage_in_queue
from ..validation.completion_policy import (
    _completion_strategy_valid,
    _confirm_existing_stages_valid,
    _confirm_note_valid,
    _confirm_strategy_valid,
    _confirmed_text_or_error,
    _note_cites_new_issues_or_error,
    _require_prior_strategy_for_confirm,
    _resolve_completion_strategy,
    _resolve_confirm_existing_strategy,
    evaluate_completion_readiness,
)
from ..validation.completion_stages import (
    _auto_confirm_enrich_for_complete,
    _auto_confirm_stage_for_complete,
    _require_enrich_stage_for_complete,
    _require_organize_stage_for_complete,
    _require_sense_check_stage_for_complete,
)
from ..validation.enrich_checks import _underspecified_steps
from .helpers import active_triage_issue_scope, triage_scoped_plan
from .records import record_confirm_existing_completion
from .rendering import _print_complete_summary


def _print_completion_coverage_warning(*, organized: int, total: int) -> None:
    """Print warnings for incomplete cluster coverage at completion time."""
    if total <= 0:
        return
    if organized == 0:
        print(colorize("  Cannot complete: no issues have been organized into clusters.", "red"))
        print(colorize(f"  {total} issues are waiting.", "dim"))
        return
    if organized < total:
        remaining = total - organized
        print(
            colorize(
                f"  Warning: {remaining}/{total} issues are not yet in any cluster.",
                "yellow",
            )
        )


def _print_completion_jump_back_guidance() -> None:
    """Print the post-summary guidance for revisiting earlier triage stages."""
    print()
    print(
        colorize(
            "  To revise an earlier stage: desloppify plan triage --stage <observe|reflect|organize|enrich|sense-check>",
            "dim",
        )
    )
    print(colorize("  Pass --report to update, or omit to keep existing analysis.", "dim"))


def _record_incomplete_recovery(
    *,
    plan: dict,
    state: dict,
    services: TriageServices,
    reason: str,
) -> list[str]:
    """Persist the current missing-disposition set for recovery guidance."""
    missing = sync_undispositioned_triage_meta(plan, state)
    services.save_plan(plan)
    if missing:
        print(
            colorize(
                f"  Triage recovery blocked: {len(missing)} issue(s) still need cluster/skip dispositions ({reason}).",
                "yellow",
            )
        )
        for issue_id in missing[:5]:
            print(colorize(f"    {issue_id}", "dim"))
        if len(missing) > 5:
            print(colorize(f"    ... and {len(missing) - 5} more", "dim"))
    return missing


def _resolve_confirm_existing_context(
    *,
    args: argparse.Namespace,
    plan: dict,
    services: TriageServices,
    stages: dict,
) -> tuple[object, bool] | None:
    """Load confirm-existing triage context and validate the stage prerequisites."""
    runtime = services.command_runtime(args)
    state = runtime.state
    si = services.collect_triage_input(plan, state)
    has_only_additions = bool(si.new_since_last) and not si.resolved_since_last
    if not _confirm_existing_stages_valid(
        stages=stages,
        has_only_additions=has_only_additions,
        si=si,
    ):
        return None
    return si, has_only_additions


def _resolve_confirm_existing_inputs(
    *,
    note: str | None,
    strategy: str | None,
    confirmed: str | None,
    plan: dict,
    state: dict,
    meta: dict,
    si,
    has_only_additions: bool,
) -> tuple[str, str, str] | None:
    """Validate and resolve note/strategy/confirmed inputs for confirm-existing."""
    if not _confirm_note_valid(note):
        return None
    resolved_strategy = _resolve_confirm_existing_strategy(
        strategy,
        has_only_additions=has_only_additions,
        meta=meta,
    )
    if resolved_strategy is None:
        return None
    if not _confirm_strategy_valid(resolved_strategy):
        return None
    confirmed_text = _confirmed_text_or_error(
        plan=plan,
        state=state,
        confirmed=confirmed,
    )
    if confirmed_text is None:
        return None
    if not _note_cites_new_issues_or_error(note, si):
        return None
    return note or "", resolved_strategy, confirmed_text


def _cmd_triage_complete(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Complete triage — requires organize stage (or confirm-existing path)."""
    resolved_services = services or default_triage_services()
    strategy: str | None = getattr(args, "strategy", None)
    attestation: str | None = getattr(args, "attestation", None)
    plan = resolved_services.load_plan()

    if not has_triage_in_queue(plan):
        print(colorize("  No planning stages in the queue — nothing to complete.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})

    state = resolved_services.command_runtime(args).state
    triage_scope = active_triage_issue_scope(plan, state)
    review_ids = (
        triage_open_review_ids_from_state(plan, state)
        if triage_scope is None
        else triage_scope
    )

    # Organize gate
    if not _require_organize_stage_for_complete(plan=plan, meta=meta, stages=stages):
        return
    if not _auto_confirm_stage_for_complete(
        plan=plan, stages=stages, stage="organize",
        attestation=attestation, save_plan_fn=resolved_services.save_plan,
    ):
        return

    # Enrich gate — compute underspecified steps once, share across require + confirm
    underspec = _underspecified_steps(triage_scoped_plan(plan, state))
    if not _require_enrich_stage_for_complete(
        plan=plan, meta=meta, stages=stages, underspec=underspec,
    ):
        return
    if not _auto_confirm_enrich_for_complete(
        plan=plan, stages=stages, attestation=attestation,
        save_plan_fn=resolved_services.save_plan, underspec=underspec,
    ):
        return

    # Sense-check gate
    if not _require_sense_check_stage_for_complete(plan=plan, meta=meta, stages=stages):
        return
    if not _auto_confirm_stage_for_complete(
        plan=plan, stages=stages, stage="sense-check",
        attestation=attestation, save_plan_fn=resolved_services.save_plan,
    ):
        return

    readiness = evaluate_completion_readiness(
        plan,
        state,
        require_confirmed_stages=False,
    )
    if not readiness.ok:
        _record_incomplete_recovery(
            plan=plan,
            state=state,
            services=resolved_services,
            reason="completion validation failed",
        )
        return

    organized = readiness.organized
    total = readiness.total
    if total > 0 and organized == 0:
        _print_completion_coverage_warning(organized=organized, total=total)
        return
    _print_completion_coverage_warning(organized=organized, total=total)

    strategy = _resolve_completion_strategy(strategy, meta=meta)
    if strategy is None:
        return
    if not _completion_strategy_valid(strategy):
        return

    # Show summary
    _print_complete_summary(plan, stages)

    organized, total, _ = triage_coverage(plan, open_review_ids=review_ids)

    _print_completion_jump_back_guidance()

    resolved_services.append_log_entry(
        plan,
        "triage_complete",
        actor="user",
        detail={
            "strategy_len": len(strategy.strip()),
            "coverage": f"{organized}/{total}",
        },
    )

    apply_completion(args, plan, strategy, services=resolved_services)

    print_user_message(
        "Hey — triage is done. Run `desloppify next` and start"
        " executing the plan. Don't stop until you're done —"
        " unless I've told you otherwise, just go."
    )


def _cmd_confirm_existing(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Fast-track: confirm existing plan structure is still valid."""
    resolved_services = services or default_triage_services()
    note: str | None = getattr(args, "note", None)
    strategy: str | None = getattr(args, "strategy", None)
    confirmed: str | None = getattr(args, "confirmed", None)
    plan = resolved_services.load_plan()

    if not has_triage_in_queue(plan):
        print(colorize("  No planning stages in the queue — nothing to confirm.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})

    # Require a prior completed triage — can't skip the full flow on first run
    if not _require_prior_strategy_for_confirm(meta):
        return

    context = _resolve_confirm_existing_context(
        args=args,
        plan=plan,
        services=resolved_services,
        stages=stages,
    )
    if context is None:
        return
    si, has_only_additions = context
    state = resolved_services.command_runtime(args).state

    clusters_with_issues = manual_clusters_with_issues(plan)
    if not clusters_with_issues:
        print(colorize("  Cannot confirm existing: no clusters with issues exist.", "red"))
        print(colorize("  Use the full organize flow instead.", "dim"))
        return

    resolved_inputs = _resolve_confirm_existing_inputs(
        note=note,
        strategy=strategy,
        confirmed=confirmed,
        plan=plan,
        state=state,
        meta=meta,
        si=si,
        has_only_additions=has_only_additions,
    )
    if resolved_inputs is None:
        return
    note_text, strategy, confirmed_text = resolved_inputs

    # Record organize as confirmed-existing and complete
    stages = meta.setdefault("triage_stages", {})
    record_confirm_existing_completion(
        stages=stages,
        note=note_text,
        issue_count=len(clusters_with_issues),
        confirmed_text=confirmed_text,
    )

    resolved_services.append_log_entry(
        plan,
        "triage_confirm_existing",
        actor="user",
        detail={"confirmed_text": confirmed_text},
    )

    apply_completion(
        args,
        plan,
        strategy,
        services=resolved_services,
        completion_mode="confirm_existing",
        completion_note=note_text,
    )
    print(
        colorize(
            "  Confirmed existing plan — reused the current enriched cluster plan.",
            "green",
        )
    )


def cmd_triage_complete(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for triage completion."""
    _cmd_triage_complete(args, services=services)


def cmd_confirm_existing(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Public entrypoint for confirm-existing completion path."""
    _cmd_confirm_existing(args, services=services)


__all__ = [
    "cmd_confirm_existing",
    "cmd_triage_complete",
    "_cmd_confirm_existing",
    "_cmd_triage_complete",
]
