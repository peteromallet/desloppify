"""Import flow helpers for review command."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

from desloppify import state as state_mod
import desloppify.engine.plan_queue as plan_queue_mod
from desloppify.app.commands.scan.reporting import (
    dimensions as reporting_dimensions_mod,
)
from desloppify.app.commands.scan.artifacts import emit_scorecard_badge
from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.base.output.terminal import colorize
from desloppify.intelligence import integrity as subjective_integrity_mod
from desloppify.intelligence.review.importing.holistic import import_holistic_issues
from desloppify.intelligence.review.importing.contracts_models import (
    AssessmentImportPolicyModel,
)

from ..assessment_integrity import (
    bind_scorecard_subjective_at_target,
    subjective_at_target_dimensions,
)
from . import helpers as import_helpers_mod
from .flags import (
    ImportFlagValidationError,
    ReviewImportConfig,
    build_import_load_config,
    clear_provisional_override_flags,
    imported_assessment_keys,
    mark_manual_override_assessments_provisional,
    validate_import_flag_combos,
)
from .plan_sync import sync_plan_after_import
from .results import print_import_results

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
    override_enabled, override_attest = import_helpers_mod.resolve_override_context(
        manual_override=import_config.manual_override,
        manual_attest=import_config.manual_attest,
    )
    try:
        validate_import_flag_combos(
            attested_external=import_config.attested_external,
            allow_partial=import_config.allow_partial,
            override_enabled=override_enabled,
            override_attest=override_attest,
        )
    except ImportFlagValidationError as exc:
        raise CommandError(str(exc), exit_code=1) from exc

    try:
        issues_data = import_helpers_mod.load_import_issues_data(
            import_file,
            config=build_import_load_config(
                lang_name=lang_name,
                import_config=import_config,
                override_enabled=override_enabled,
                override_attest=override_attest,
            ),
        )
    except import_helpers_mod.ImportPayloadLoadError as exc:
        import_helpers_mod.print_import_load_errors(
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
        return copy.deepcopy(state_mod.load_state(state_path))
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
) -> None:
    """Record audit metadata for assessment-bearing import payloads."""
    if not assessment_policy.assessments_present:
        return
    audit = working_state.setdefault("assessment_import_audit", [])
    audit.append(
        {
            "timestamp": state_mod.utc_now(),
            "mode": assessment_policy.mode,
            "trusted": bool(assessment_policy.trusted),
            "reason": assessment_policy.reason,
            "override_used": bool(assessment_policy.mode == "manual_override"),
            "attested_external": bool(assessment_policy.mode == "attested_external"),
            "provisional": bool(assessment_policy.mode == "manual_override"),
            "provisional_count": int(provisional_count),
            "attest": (override_attest or "").strip(),
            "import_file": str(import_file),
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
    state_mod.save_state(state, state_file)
    sync_plan_after_import(
        state,
        diff,
        assessment_mode,
        state_file=state_file,
        config=config,
        import_file=import_file,
        import_payload=import_payload,
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
    plan_path = plan_queue_mod.plan_path_for_state(Path(state_file))
    if not plan_queue_mod.has_living_plan(plan_path):
        return
    plan = plan_queue_mod.load_plan(plan_path)
    if plan_queue_mod.WORKFLOW_IMPORT_SCORES_ID not in plan.get("queue_order", []):
        return
    pending_meta = plan_queue_mod.pending_import_scores_meta(plan, state)
    matches, reason = plan_queue_mod.import_scores_meta_matches(
        pending_meta,
        import_file=import_file,
        import_payload=issues_data,
    )
    if matches:
        return
    expected_file = ""
    if isinstance(pending_meta, dict):
        expected_file = str(pending_meta.get("import_file", "")).strip()
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
        import_helpers_mod.assessment_policy_model_from_payload(issues_data)
    )
    import_helpers_mod.print_assessment_mode_banner(
        assessment_policy.to_dict(),
        colorize_fn=colorize,
    )
    import_helpers_mod.print_assessment_policy_notice(
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

    prev = state_mod.score_snapshot(state)
    working_state = _build_working_state(state, state_file)

    diff = import_holistic_issues(issues_data, working_state, lang.name)
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
    print_import_results(
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
    override_enabled, override_attest = import_helpers_mod.resolve_override_context(
        manual_override=resolved_import_config.manual_override,
        manual_attest=resolved_import_config.manual_attest,
    )
    try:
        validate_import_flag_combos(
            attested_external=resolved_import_config.attested_external,
            allow_partial=resolved_import_config.allow_partial,
            override_enabled=override_enabled,
            override_attest=override_attest,
        )
    except ImportFlagValidationError as exc:
        raise CommandError(str(exc), exit_code=1) from exc

    try:
        issues_data = import_helpers_mod.load_import_issues_data(
            import_file,
            config=build_import_load_config(
                lang_name=lang.name,
                import_config=resolved_import_config,
                override_enabled=override_enabled,
                override_attest=override_attest,
            ),
        )
    except import_helpers_mod.ImportPayloadLoadError as exc:
        import_helpers_mod.print_import_load_errors(
            exc.errors,
            import_file=str(import_file),
            colorize_fn=colorize,
        )
        raise PacketValidationError("import payload validation failed", exit_code=1) from exc

    assessment_policy = import_helpers_mod.assessment_policy_model_from_payload(
        issues_data
    )
    import_helpers_mod.print_assessment_mode_banner(
        assessment_policy.to_dict(),
        colorize_fn=colorize,
    )
    import_helpers_mod.print_assessment_policy_notice(
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
    "ImportFlagValidationError",
    "ReviewImportConfig",
    "do_import",
    "do_validate_import",
    "subjective_at_target_dimensions",
]
