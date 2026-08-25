"""Enrich and sense-check triage confirmation handlers."""

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
from ..services import TriageServices, default_triage_services
from ..stages.helpers import active_triage_issue_scope, scoped_manual_clusters_with_issues
from ..validation.enrich_quality import (
    EnrichQualityIssue as _ConfirmationCheckIssue,
    EnrichQualityReport as _ConfirmationCheckReport,
    evaluate_enrich_quality,
)


def _print_confirmation_failure(
    *,
    issue: _ConfirmationCheckIssue | None,
    header: str,
    row_printer,
    hints: tuple[str, ...] = (),
) -> bool:
    if issue is None:
        return False
    print(colorize(header.format(total=issue.total), "red"))
    row_printer(issue)
    for hint in hints:
        print(colorize(hint, "dim"))
    return True


def _collect_enrich_level_confirmation_checks(
    plan: dict,
    *,
    include_stale_issue_ref_warning: bool,
    triage_issue_ids: set[str] | None = None,
) -> _ConfirmationCheckReport:
    from desloppify.base.discovery.paths import get_project_root

    return evaluate_enrich_quality(
        plan,
        get_project_root(),
        phase_label="sense-check" if not include_stale_issue_ref_warning else "enrich",
        bad_paths_severity="failure",
        missing_effort_severity="failure",
        include_missing_issue_refs=True,
        include_vague_detail=True,
        stale_issue_refs_severity="warning" if include_stale_issue_ref_warning else None,
        triage_issue_ids=triage_issue_ids,
    )


def _print_underspecified_rows(issue: _ConfirmationCheckIssue) -> None:
    for name, bare, total in issue.rows[:5]:
        print(colorize(f"    {name}: {bare}/{total} steps", "yellow"))
    print()


def _print_bad_path_rows(issue: _ConfirmationCheckIssue) -> None:
    for name, step_num, paths in issue.rows:
        for path_str in paths:
            print(colorize(f"    {name} step {step_num}: {path_str}", "yellow"))


def _print_missing_ratio_rows(issue: _ConfirmationCheckIssue, *, suffix: str) -> None:
    for name, missing, total in issue.rows[:5]:
        print(colorize(f"    {name}: {missing}/{total} steps {suffix}", "yellow"))


def _print_vague_detail_rows(issue: _ConfirmationCheckIssue) -> None:
    for name, step_num, title in issue.rows[:5]:
        print(colorize(f"    {name} step {step_num}: {title}", "yellow"))


def _handle_enrich_failures(checks: _ConfirmationCheckReport) -> bool:
    if _print_confirmation_failure(
        issue=checks.failure("underspecified"),
        header="\n  Cannot confirm: {total} step(s) still lack detail or issue_refs.",
        row_printer=_print_underspecified_rows,
        hints=(
            "  Every step needs --detail (sub-points) or --issue-refs (for auto-completion).",
            '  Fix: desloppify plan cluster update <name> --update-step N --detail "sub-details"',
        ),
    ):
        return True
    print(colorize("  All steps have detail or issue_refs.", "green"))
    if _print_confirmation_failure(
        issue=checks.failure("bad_paths"),
        header="\n  Cannot confirm: {total} file path(s) in step details don't exist on disk.",
        row_printer=_print_bad_path_rows,
        hints=("  Fix paths with: desloppify plan cluster update <name> --update-step N --detail '...'",),
    ):
        return True
    if _print_confirmation_failure(
        issue=checks.failure("missing_effort"),
        header="\n  Cannot confirm: {total} step(s) have no effort tag.",
        row_printer=lambda issue: _print_missing_ratio_rows(issue, suffix="missing effort"),
        hints=(
            "  Every step needs --effort (trivial/small/medium/large).",
            "  Fix: desloppify plan cluster update <name> --update-step N --effort small",
        ),
    ):
        return True
    if _print_confirmation_failure(
        issue=checks.failure("missing_issue_refs"),
        header="\n  Cannot confirm: {total} step(s) have no issue_refs.",
        row_printer=lambda issue: _print_missing_ratio_rows(issue, suffix="missing refs"),
        hints=(
            "  Every step needs --issue-refs linking it to the review issue(s) it addresses.",
            "  Fix: desloppify plan cluster update <name> --update-step N --issue-refs <hash1> <hash2>",
        ),
    ):
        return True
    return _print_confirmation_failure(
        issue=checks.failure("vague_detail"),
        header="\n  Cannot confirm: {total} step(s) have vague detail (< 80 chars, no file paths).",
        row_printer=_print_vague_detail_rows,
        hints=(
            "  Executor-ready means: someone with zero context knows which file to open and what to change.",
            "  Add file paths and specific instructions to each step's --detail.",
        ),
    )


def _print_stale_ref_warning(issue: _ConfirmationCheckIssue | None) -> None:
    if issue is None:
        return
    print(colorize(f"\n  Warning: {issue.total} step issue_ref(s) point to skipped/wontfixed issues.", "yellow"))
    for name, step_num, ids in issue.rows[:5]:
        print(colorize(f"    {name} step {step_num}: {', '.join(ids[:3])}", "yellow"))
    print(colorize("  Consider removing stale refs or removing the step if it's no longer needed.", "dim"))


def _handle_sense_check_failures(checks: _ConfirmationCheckReport) -> bool:
    failure_messages = {
        "underspecified": "still lack detail or issue_refs.",
        "bad_paths": "file path(s) in step details don't exist on disk.",
        "missing_effort": "step(s) have no effort tag.",
        "missing_issue_refs": "step(s) have no issue_refs.",
        "vague_detail": "step(s) have vague detail.",
    }
    for code, suffix in failure_messages.items():
        issue = checks.failure(code)
        if issue is None:
            continue
        print(colorize(f"\n  Cannot confirm: {issue.total} {suffix}", "red"))
        if code == "underspecified":
            _print_underspecified_rows(issue)
        elif code == "bad_paths":
            _print_bad_path_rows(issue)
        return True
    return False


def confirm_enrich(
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
    *,
    services: TriageServices | None = None,
) -> None:
    """Show enrich summary and record confirmation if attestation is valid."""
    resolved_services = services or default_triage_services()
    if not ensure_stage_is_confirmable(stages, stage="enrich"):
        return
    state = resolved_services.command_runtime(args).state

    checks = _collect_enrich_level_confirmation_checks(
        plan,
        include_stale_issue_ref_warning=True,
        triage_issue_ids=active_triage_issue_scope(plan, state),
    )

    print(colorize("  Stage: ENRICH — Make steps executor-ready (detail, refs)", "bold"))
    print(colorize("  " + "─" * 54, "dim"))

    if _handle_enrich_failures(checks):
        return

    _print_stale_ref_warning(checks.warning("stale_issue_refs"))

    enrich_clusters = scoped_manual_clusters_with_issues(plan, state)

    if not finalize_stage_confirmation(
        plan=plan,
        stages=stages,
        request=StageConfirmationRequest(
            stage="enrich",
            attestation=attestation,
            min_attestation_len=MIN_ATTESTATION_LEN,
            command_hint='desloppify plan triage --confirm enrich --attestation "Steps are executor-ready..."',
            validation_stage="enrich",
            validate_attestation_fn=validate_attestation,
            validation_kwargs={"cluster_names": enrich_clusters},
            log_action="triage_confirm_enrich",
        ),
        services=resolved_services,
    ):
        return
    print_user_message(
        "Hey — enrich is confirmed. Run `desloppify plan triage"
        " --stage sense-check --report \"...\"` to verify step"
        " accuracy and cross-cluster dependencies."
    )


def confirm_sense_check(
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
    *,
    services: TriageServices | None = None,
) -> None:
    """Show sense-check summary and record confirmation if attestation is valid."""
    resolved_services = services or default_triage_services()
    if not ensure_stage_is_confirmable(stages, stage="sense-check"):
        return
    state = resolved_services.command_runtime(args).state

    checks = _collect_enrich_level_confirmation_checks(
        plan,
        include_stale_issue_ref_warning=False,
        triage_issue_ids=active_triage_issue_scope(plan, state),
    )

    print(colorize("  Stage: SENSE-CHECK — Verify accuracy & cross-cluster deps", "bold"))
    print(colorize("  " + "─" * 57, "dim"))

    if _handle_sense_check_failures(checks):
        return

    print(colorize("  All enrich-level checks pass.", "green"))

    sense_check_clusters = scoped_manual_clusters_with_issues(plan, state)

    if not finalize_stage_confirmation(
        plan=plan,
        stages=stages,
        request=StageConfirmationRequest(
            stage="sense-check",
            attestation=attestation,
            min_attestation_len=MIN_ATTESTATION_LEN,
            command_hint='desloppify plan triage --confirm sense-check --attestation "Content and structure verified..."',
            validation_stage="sense-check",
            validate_attestation_fn=validate_attestation,
            validation_kwargs={"cluster_names": sense_check_clusters},
            log_action="triage_confirm_sense_check",
        ),
        services=resolved_services,
    ):
        return
    print_user_message(
        "Hey — sense-check is confirmed. Run `desloppify plan triage"
        " --complete --strategy \"...\"` to finish triage."
    )


__all__ = ["confirm_enrich", "confirm_sense_check"]
