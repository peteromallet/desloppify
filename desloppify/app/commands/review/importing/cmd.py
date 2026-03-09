"""Import flow helpers for review command."""

from __future__ import annotations

import copy
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.scan.reporting import (
    dimensions as reporting_dimensions_mod,
)
from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.base.output.terminal import colorize
from desloppify.intelligence import integrity as subjective_integrity_mod
from desloppify.intelligence import review as review_mod
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


def do_import(
    import_file,
    state,
    lang,
    state_file,
    *,
    config: dict | None = None,
    allow_partial: bool = False,
    trusted_assessment_source: bool = False,
    trusted_assessment_label: str | None = None,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    dry_run: bool = False,
) -> None:
    """Import mode: ingest agent-produced issues."""
    import_config = ReviewImportConfig(
        config=config,
        allow_partial=allow_partial,
        trusted_assessment_source=trusted_assessment_source,
        trusted_assessment_label=trusted_assessment_label,
        attested_external=attested_external,
        manual_override=manual_override,
        manual_attest=manual_attest,
    )
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
                lang_name=lang.name,
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

    prev = state_mod.score_snapshot(state)

    state_path = Path(state_file) if state_file is not None else None
    if state_path is not None and state_path.exists():
        working_state = copy.deepcopy(state_mod.load_state(state_path))
    else:
        working_state = copy.deepcopy(state)

    diff = review_mod.import_holistic_issues(issues_data, working_state, lang.name)
    label = "Holistic review"
    assessment_keys = imported_assessment_keys(issues_data)
    provisional_count = 0
    if assessment_policy.mode == "manual_override":
        provisional_count = mark_manual_override_assessments_provisional(
            working_state,
            assessment_keys=assessment_keys,
        )
    elif assessment_policy.mode in {"trusted_internal", "attested_external"}:
        clear_provisional_override_flags(
            working_state,
            assessment_keys=assessment_keys,
        )

    if diff.get("skipped", 0) > 0 and not import_config.allow_partial:
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

    if assessment_policy.assessments_present:
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

    if not dry_run:
        state.clear()
        state.update(working_state)
        state_mod.save_state(state, state_file)
        sync_plan_after_import(state, diff, assessment_policy.mode)

    display_state = state if not dry_run else working_state
    print_import_results(
        state=display_state,
        lang_name=lang.name,
        config=import_config.config,
        diff=diff,
        prev=prev,
        label=label,
        provisional_count=provisional_count,
        assessment_policy=assessment_policy,
        scorecard_subjective_at_target_fn=_SCORECARD_SUBJECTIVE_AT_TARGET,
    )


def do_validate_import(
    import_file,
    lang,
    *,
    allow_partial: bool = False,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
) -> None:
    """Validate import payload/policy and print mode without mutating state."""
    import_config = ReviewImportConfig(
        allow_partial=allow_partial,
        attested_external=attested_external,
        manual_override=manual_override,
        manual_attest=manual_attest,
    )
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
                lang_name=lang.name,
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
