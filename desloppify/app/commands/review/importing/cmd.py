"""Import flow helpers for review command."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

from desloppify.app.commands.scan.artifacts import emit_scorecard_badge
from desloppify.app.commands.scan.reporting import (
    dimensions as reporting_dimensions_mod,
)
from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.constants import WORKFLOW_IMPORT_SCORES_ID
from desloppify.engine._plan.persistence import (
    has_living_plan,
    load_plan,
    plan_path_for_state,
)
from desloppify.engine._plan.sync.workflow_gates import (
    import_scores_meta_matches,
    pending_import_scores_meta,
)
from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._state.persistence import load_state, save_state
from desloppify.engine._state.schema import utc_now
from desloppify.intelligence import integrity as subjective_integrity_mod
from desloppify.intelligence.review.importing.contracts_models import (
    AssessmentImportPolicyModel,
)
from desloppify.intelligence.review.importing.holistic import import_holistic_issues
from desloppify.state_score_snapshot import score_snapshot

from ..assessment_integrity import (
    bind_scorecard_subjective_at_target,
    subjective_at_target_dimensions,
)
from ..state_payloads import append_assessment_import_audit
from .flags import (
    ReviewImportConfig,
    build_import_load_config,
    clear_provisional_override_flags,
    imported_assessment_keys,
    mark_manual_override_assessments_provisional,
)
from .output import (
    print_assessment_mode_banner,
    print_assessment_policy_notice,
    print_import_load_errors,
)
from .parse import (
    ImportPayloadLoadError,
    load_import_issues_data,
    resolve_override_context,
)
from .plan_sync import PlanImportSyncRequest, sync_plan_after_import
from .policy import assessment_policy_model_from_payload
from .results import report_review_import_outcome

_SCORECARD_SUBJECTIVE_AT_TARGET = bind_scorecard_subjective_at_target(
    reporting_dimensions_mod=reporting_dimensions_mod,
    subjective_integrity_mod=subjective_integrity_mod,
)


def _resolve_import_payload(
    import_file,
    *,
    lang_name: str,
    import_config: ReviewImportConfig,
) -> tuple[dict, bool, str | None]:
    """Validate import flags and load payload with policy checks."""
    override_enabled, override_attest = resolve_override_context(
        manual_override=import_config.manual_override,
        manual_attest=import_config.manual_attest,
    )
    try:
        issues_data = load_import_issues_data(
            import_file,
            options=build_import_load_config(
                lang_name=lang_name,
                import_config=import_config,
                override_enabled=override_enabled,
                override_attest=override_attest,
            ),
        )
    except ImportPayloadLoadError as exc:
        print_import_load_errors(
            exc.errors,
            import_file=str(import_file),
            colorize_fn=colorize,
        )
        raise PacketValidationError("import payload validation failed", exit_code=1) from exc

    return issues_data, override_enabled, override_attest


def _build_working_state(state: dict, state_file) -> dict:
    """Return state snapshot used for import mutation/dry-run rendering."""
    state_path = Path(state_file) if state_file is not None else None
    if state_path is not None and state_path.exists():
        return copy.deepcopy(load_state(state_path))
    return copy.deepcopy(state)


def _apply_assessment_policy(
    *,
    working_state: dict,
    issues_data: dict,
    assessment_policy: AssessmentImportPolicyModel,
) -> int:
    """Apply provisional/clear flags based on assessment policy mode."""
    assessment_keys = imported_assessment_keys(issues_data)
    if assessment_policy.mode == "manual_override":
        return mark_manual_override_assessments_provisional(
            working_state,
            assessment_keys=assessment_keys,
        )
    if assessment_policy.mode in {"trusted_internal", "attested_external"}:
        clear_provisional_override_flags(
            working_state,
            assessment_keys=assessment_keys,
        )
    return 0


def _raise_on_partial_skip(diff: dict, *, allow_partial: bool) -> None:
    """Refuse import when payload skips issues and partial imports are disabled."""
    if diff.get("skipped", 0) <= 0 or allow_partial:
        return
    details_lines: list[str] = []
    for detail in diff.get("skipped_details", []):
        reasons = "; ".join(detail.get("missing", []))
        details_lines.append(
            f"  #{detail.get('index', '?')} ({detail.get('identifier', '<none>')}): {reasons}"
        )
    msg = "import produced skipped issue(s); refusing partial import."
    if details_lines:
        msg += "\n" + "\n".join(details_lines)
    msg += "\nFix the payload and retry, or pass --allow-partial to override."
    raise CommandError(msg, exit_code=1)


def _append_assessment_import_audit(
    *,
    working_state: dict,
    assessment_policy: AssessmentImportPolicyModel,
    provisional_count: int,
    override_attest: str | None,
    import_file,
    import_payload: dict,
) -> None:
    """Record audit metadata for assessment-bearing import payloads."""
    if not assessment_policy.assessments_present:
        return
    provenance = import_payload.get("provenance")
    provenance_dict = provenance if isinstance(provenance, dict) else {}
    append_assessment_import_audit(
        working_state,
        {
            "timestamp": utc_now(),
            "mode": assessment_policy.mode,
            "trusted": bool(assessment_policy.trusted),
            "reason": assessment_policy.reason,
            "override_used": bool(assessment_policy.mode == "manual_override"),
            "attested_external": bool(assessment_policy.mode == "attested_external"),
            "provisional": bool(assessment_policy.mode == "manual_override"),
            "provisional_count": int(provisional_count),
            "attest": (override_attest or "").strip(),
            "import_file": str(import_file),
            "packet_sha256": str(provenance_dict.get("packet_sha256", "")).strip(),
        }
    )


def _persist_import_state(
    *,
    state: dict,
    working_state: dict,
    state_file,
    diff: dict,
    assessment_mode: str,
    config: dict | None,
    import_file: str,
    import_payload: dict,
) -> None:
    """Persist imported state and synchronize the work plan."""
    state.clear()
    state.update(working_state)
    save_state(state, state_file)
    sync_plan_after_import(
        state,
        diff,
        assessment_mode,
        request=PlanImportSyncRequest(
            state_file=state_file,
            config=config,
            import_file=import_file,
            import_payload=import_payload,
        ),
    )


def _guard_pending_import_scores_match(
    *,
    state: dict,
    state_file,
    import_file: str,
    issues_data: dict,
    assessment_policy: AssessmentImportPolicyModel,
) -> None:
    """Refuse durable imports that do not match the queued score-import batch."""
    if assessment_policy.mode not in {"trusted_internal", "attested_external"}:
        return
    plan_path = plan_path_for_state(Path(state_file))
    if not has_living_plan(plan_path):
        return
    plan = load_plan(plan_path)
    if WORKFLOW_IMPORT_SCORES_ID not in plan.get("queue_order", []):
        return
    pending_meta = pending_import_scores_meta(plan, state)
    matches, reason = import_scores_meta_matches(
        pending_meta,
        import_file=import_file,
        import_payload=issues_data,
    )
    if matches:
        return
    expected_file = ""
    if pending_meta is not None:
        expected_file = pending_meta.import_file.strip()
    raise CommandError(
        "Refusing durable score import: the pending "
        "`workflow::import-scores` task is bound to a different review batch.\n"
        f"  - {reason}\n"
        + (f"Expected queued import file: {expected_file}\n" if expected_file else "")
        + "Use the exact file shown by `desloppify next`, or clear the stale workflow item first.",
        exit_code=1,
    )


def _has_refreshable_scorecard_context(state: dict) -> bool:
    """Return True when state has scan-backed scorecard context.

    Review imports can run against minimal/synthetic states (for example test
    fixtures or pre-scan workflows). Refreshing the badge from those states can
    overwrite scorecard.png with a misleading partial card.
    """
    if not state.get("last_scan"):
        return False

    dim_scores = state.get("dimension_scores")
    if not isinstance(dim_scores, dict) or not dim_scores:
        return False

    for data in dim_scores.values():
        if not isinstance(data, dict):
            continue
        detectors = data.get("detectors", {})
        if not isinstance(detectors, dict):
            continue
        if "subjective_assessment" in detectors:
            continue
        if int(data.get("checks", 0) or 0) <= 0:
            continue
        return True
    return False


def _protected_review_issue_ids_for_import(state_file) -> set[str]:
    """Return user-held review IDs that an import must never auto-resolve."""
    if state_file is None:
        return set()
    plan_path = plan_path_for_state(Path(state_file))
    if not has_living_plan(plan_path):
        return set()
    return protected_review_issue_ids(load_plan(plan_path))


def _refresh_scorecard_after_import(
    *,
    state: dict,
    config: dict | None,
    assessment_policy: AssessmentImportPolicyModel,
) -> bool:
    """Refresh the scorecard badge when a trusted import updates live scores."""
    if not assessment_policy.assessments_present or not assessment_policy.trusted:
        return False
    if not _has_refreshable_scorecard_context(state):
        return False
    emit_scorecard_badge(
        SimpleNamespace(no_badge=False, badge_path=None),
        config or {},
        state,
    )
    return True


def do_import(
    import_file,
    state,
    lang,
    state_file,
    *,
    import_config: ReviewImportConfig | None = None,
    dry_run: bool = False,
) -> None:
    """Import mode: ingest agent-produced issues."""
    resolved_import_config = import_config or ReviewImportConfig()
    issues_data, _override_enabled, override_attest = _resolve_import_payload(
        import_file,
        lang_name=lang.name,
        import_config=resolved_import_config,
    )

    assessment_policy: AssessmentImportPolicyModel = (
        assessment_policy_model_from_payload(issues_data)
    )
    print_assessment_mode_banner(
        assessment_policy.to_dict(),
        colorize_fn=colorize,
    )
    print_assessment_policy_notice(
        assessment_policy.to_dict(),
        import_file=str(import_file),
        colorize_fn=colorize,
    )
    _guard_pending_import_scores_match(
        state=state,
        state_file=state_file,
        import_file=str(import_file),
        issues_data=issues_data,
        assessment_policy=assessment_policy,
    )

    prev = score_snapshot(state)
    working_state = _build_working_state(state, state_file)

    diff = import_holistic_issues(
        issues_data,
        working_state,
        lang.name,
        preserve_open_issue_ids=_protected_review_issue_ids_for_import(state_file),
    )
    label = "Holistic review"
    provisional_count = _apply_assessment_policy(
        working_state=working_state,
        issues_data=issues_data,
        assessment_policy=assessment_policy,
    )
    _raise_on_partial_skip(diff, allow_partial=resolved_import_config.allow_partial)
    _append_assessment_import_audit(
        working_state=working_state,
        assessment_policy=assessment_policy,
        provisional_count=provisional_count,
        override_attest=override_attest,
        import_file=import_file,
        import_payload=issues_data,
    )

    if not dry_run:
        _persist_import_state(
            state=state,
            working_state=working_state,
            state_file=state_file,
            diff=diff,
            assessment_mode=assessment_policy.mode,
            config=resolved_import_config.config,
            import_file=str(import_file),
            import_payload=issues_data,
        )

    display_state = state if not dry_run else working_state
    report_review_import_outcome(
        state=display_state,
        lang_name=lang.name,
        config=resolved_import_config.config,
        diff=diff,
        prev=prev,
        label=label,
        provisional_count=provisional_count,
        assessment_policy=assessment_policy,
        scorecard_subjective_at_target_fn=_SCORECARD_SUBJECTIVE_AT_TARGET,
    )
    if not dry_run:
        _refresh_scorecard_after_import(
            state=state,
            config=resolved_import_config.config,
            assessment_policy=assessment_policy,
        )


def do_validate_import(
    import_file,
    lang,
    *,
    import_config: ReviewImportConfig | None = None,
) -> None:
    """Validate import payload/policy and print mode without mutating state."""
    resolved_import_config = import_config or ReviewImportConfig()
    override_enabled, override_attest = resolve_override_context(
        manual_override=resolved_import_config.manual_override,
        manual_attest=resolved_import_config.manual_attest,
    )
    try:
        issues_data = load_import_issues_data(
            import_file,
            options=build_import_load_config(
                lang_name=lang.name,
                import_config=resolved_import_config,
                override_enabled=override_enabled,
                override_attest=override_attest,
            ),
        )
    except ImportPayloadLoadError as exc:
        print_import_load_errors(
            exc.errors,
            import_file=str(import_file),
            colorize_fn=colorize,
        )
        raise PacketValidationError("import payload validation failed", exit_code=1) from exc

    assessment_policy = assessment_policy_model_from_payload(
        issues_data
    )
    print_assessment_mode_banner(
        assessment_policy.to_dict(),
        colorize_fn=colorize,
    )
    print_assessment_policy_notice(
        assessment_policy.to_dict(),
        import_file=str(import_file),
        colorize_fn=colorize,
    )

    issues_count = len(issues_data["issues"])
    print(colorize("\n  Import payload validation passed.", "bold"))
    print(colorize(f"  Issues parsed: {issues_count}", "dim"))
    if assessment_policy.assessments_present:
        count = int(assessment_policy.assessment_count)
        print(colorize(f"  Assessment entries in payload: {count}", "dim"))
    print(colorize("  No state changes were made (--validate-import).", "dim"))


__all__ = [
    "ReviewImportConfig",
    "do_import",
    "do_validate_import",
    "subjective_at_target_dimensions",
]
