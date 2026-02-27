"""Import flow helpers for review command."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.helpers.score_update import print_score_update
from desloppify.app.commands.scan import (
    scan_reporting_dimensions as reporting_dimensions_mod,
)
from desloppify.app.commands.review.assessment_integrity import (
    bind_scorecard_subjective_at_target,
    subjective_at_target_dimensions,
)
from desloppify.app.commands.review import import_helpers as import_helpers_mod
from desloppify.intelligence import integrity as subjective_integrity_mod
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.intelligence.narrative.core import NarrativeContext
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.intelligence.review.importing.contracts import (
    AssessmentImportPolicyModel,
    ReviewImportPayload,
)
from desloppify.core.output_api import colorize

_SCORECARD_SUBJECTIVE_AT_TARGET = bind_scorecard_subjective_at_target(
    reporting_dimensions_mod=reporting_dimensions_mod,
    subjective_integrity_mod=subjective_integrity_mod,
)


class ImportFlagValidationError(ValueError):
    """Raised when review import CLI flags are mutually incompatible."""


def _validate_import_flag_combos(
    *,
    attested_external: bool,
    allow_partial: bool,
    override_enabled: bool,
    override_attest: str | None,
) -> None:
    """Fail fast on conflicting import flags to keep behavior explicit."""
    if attested_external and override_enabled:
        raise ImportFlagValidationError(
            "--attested-external cannot be combined with --manual-override"
        )
    if attested_external and allow_partial:
        raise ImportFlagValidationError(
            "--attested-external cannot be combined with --allow-partial"
        )
    if override_enabled and allow_partial:
        raise ImportFlagValidationError(
            "--manual-override cannot be combined with --allow-partial"
        )
    if override_enabled and (
        not isinstance(override_attest, str) or not override_attest.strip()
    ):
        raise ImportFlagValidationError("--manual-override requires --attest")


def _imported_assessment_keys(findings_data: ReviewImportPayload) -> set[str]:
    """Return normalized assessment dimension keys from payload."""
    raw_assessments = findings_data["assessments"]
    keys: set[str] = set()
    for raw_key in raw_assessments:
        normalized = normalize_dimension_name(str(raw_key))
        if normalized:
            keys.add(normalized)
    return keys


def _mark_manual_override_assessments_provisional(
    state: dict,
    *,
    assessment_keys: set[str],
) -> int:
    """Mark imported manual override assessments as provisional until next scan."""
    if not assessment_keys:
        return 0
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        return 0

    now = state_mod.utc_now()
    expires_scan = int(state.get("scan_count", 0) or 0) + 1
    marked = 0
    for key in sorted(assessment_keys):
        payload = store.get(key)
        if not isinstance(payload, dict):
            continue
        payload["source"] = "manual_override"
        payload["assessed_at"] = now
        payload["provisional_override"] = True
        payload["provisional_until_scan"] = expires_scan
        payload.pop("placeholder", None)
        marked += 1
    return marked


def _clear_provisional_override_flags(
    state: dict,
    *,
    assessment_keys: set[str],
) -> int:
    """Clear provisional override flags when trusted internal assessments replace them."""
    if not assessment_keys:
        return 0
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        return 0

    cleared = 0
    for key in sorted(assessment_keys):
        payload = store.get(key)
        if not isinstance(payload, dict):
            continue
        if payload.pop("provisional_override", None) is not None:
            cleared += 1
        payload.pop("provisional_until_scan", None)
        if payload.get("source") == "manual_override":
            payload["source"] = "holistic"
    return cleared


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
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> None:
    """Import mode: ingest agent-produced findings."""
    override_enabled, override_attest = import_helpers_mod.resolve_override_context(
        manual_override=manual_override,
        manual_attest=manual_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    try:
        _validate_import_flag_combos(
            attested_external=attested_external,
            allow_partial=allow_partial,
            override_enabled=override_enabled,
            override_attest=override_attest,
        )
    except ImportFlagValidationError as exc:
        print(colorize(f"  Error: {exc}", "red"), file=sys.stderr)
        sys.exit(1)

    try:
        findings_data = import_helpers_mod.load_import_findings_data(
            import_file,
            lang_name=lang.name,
            allow_partial=allow_partial,
            trusted_assessment_source=trusted_assessment_source,
            trusted_assessment_label=trusted_assessment_label,
            attested_external=attested_external,
            manual_override=override_enabled,
            manual_attest=override_attest,
            assessment_override=assessment_override,
            assessment_note=assessment_note,
        )
    except import_helpers_mod.ImportPayloadLoadError as exc:
        import_helpers_mod.print_import_load_errors(
            exc.errors,
            import_file=str(import_file),
            colorize_fn=colorize,
        )
        sys.exit(1)
    assessment_policy: AssessmentImportPolicyModel = (
        import_helpers_mod.assessment_policy_model_from_payload(findings_data)
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

    # Transactional import: only persist if all post-import guards pass.
    # Rebase on the latest on-disk state when available so long-running review
    # sessions don't clobber newer imports/scans that completed while batches ran.
    state_path = Path(state_file) if state_file is not None else None
    if state_path is not None and state_path.exists():
        working_state = copy.deepcopy(state_mod.load_state(state_path))
    else:
        working_state = copy.deepcopy(state)
    diff = review_mod.import_holistic_findings(findings_data, working_state, lang.name)
    label = "Holistic review"
    imported_assessment_keys = _imported_assessment_keys(findings_data)
    provisional_count = 0
    if assessment_policy.mode == "manual_override":
        provisional_count = _mark_manual_override_assessments_provisional(
            working_state,
            assessment_keys=imported_assessment_keys,
        )
    elif assessment_policy.mode in {"trusted_internal", "attested_external"}:
        _clear_provisional_override_flags(
            working_state,
            assessment_keys=imported_assessment_keys,
        )

    if diff.get("skipped", 0) > 0 and not allow_partial:
        print(
            colorize(
                "  Error: import produced skipped finding(s); refusing partial import.",
                "red",
            ),
            file=sys.stderr,
        )
        for detail in diff.get("skipped_details", []):
            reasons = "; ".join(detail.get("missing", []))
            print(
                colorize(
                    f"    #{detail.get('index', '?')} ({detail.get('identifier', '<none>')}): {reasons}",
                    "red",
                ),
                file=sys.stderr,
            )
        print(
            colorize(
                "  Fix the payload and retry, or pass --allow-partial to override.",
                "yellow",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

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
    state.clear()
    state.update(working_state)
    state_mod.save_state(state, state_file)

    lang_name = lang.name
    narrative = narrative_mod.compute_narrative(
        state, NarrativeContext(lang=lang_name, command="review")
    )

    print(colorize(f"\n  {label} imported:", "bold"))
    issue_count = int(diff.get("new", 0) or 0)
    print(
        colorize(
            f"  +{issue_count} new issue{'s' if issue_count != 1 else ''} "
            f"(review findings), "
            f"{diff['auto_resolved']} resolved, "
            f"{diff['reopened']} reopened",
            "dim",
        )
    )
    if provisional_count > 0:
        print(
            colorize(
                "  WARNING: manual override assessments are provisional and will "
                "reset on the next scan unless replaced by "
                "`review --run-batches --runner codex --parallel --scan-after-import`.",
                "yellow",
            )
        )
    import_helpers_mod.print_skipped_validation_details(diff, colorize_fn=colorize)
    import_helpers_mod.print_assessments_summary(state, colorize_fn=colorize)
    next_command = import_helpers_mod.print_open_review_summary(
        state, colorize_fn=colorize
    )
    print_score_update(state, prev, config=config)
    at_target = import_helpers_mod.print_review_import_scores_and_integrity(
        state,
        config or {},
        state_mod=state_mod,
        target_strict_score_from_config_fn=target_strict_score_from_config,
        subjective_at_target_fn=_SCORECARD_SUBJECTIVE_AT_TARGET,
        subjective_rerun_command_fn=reporting_dimensions_mod.subjective_rerun_command,
        colorize_fn=colorize,
    )

    print(
        colorize(
            f"  Next command to improve subjective scores: `{next_command}`", "dim"
        )
    )
    write_query(
            {
                "command": "review",
                "action": "import",
                "mode": "holistic",
                "diff": diff,
            "next_command": next_command,
            "subjective_at_target": [
                {"dimension": entry["name"], "score": entry["score"]}
                for entry in at_target
            ],
            "assessment_import": {
                "mode": assessment_policy.mode,
                "trusted": bool(assessment_policy.trusted),
                "reason": assessment_policy.reason,
            },
            "narrative": narrative,
        }
    )


def do_validate_import(
    import_file,
    lang,
    *,
    allow_partial: bool = False,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> None:
    """Validate import payload/policy and print mode without mutating state."""
    override_enabled, override_attest = import_helpers_mod.resolve_override_context(
        manual_override=manual_override,
        manual_attest=manual_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    try:
        _validate_import_flag_combos(
            attested_external=attested_external,
            allow_partial=allow_partial,
            override_enabled=override_enabled,
            override_attest=override_attest,
        )
    except ImportFlagValidationError as exc:
        print(colorize(f"  Error: {exc}", "red"), file=sys.stderr)
        sys.exit(1)

    try:
        findings_data = import_helpers_mod.load_import_findings_data(
            import_file,
            lang_name=lang.name,
            allow_partial=allow_partial,
            attested_external=attested_external,
            manual_override=override_enabled,
            manual_attest=override_attest,
            assessment_override=assessment_override,
            assessment_note=assessment_note,
        )
    except import_helpers_mod.ImportPayloadLoadError as exc:
        import_helpers_mod.print_import_load_errors(
            exc.errors,
            import_file=str(import_file),
            colorize_fn=colorize,
        )
        sys.exit(1)
    assessment_policy = import_helpers_mod.assessment_policy_model_from_payload(
        findings_data
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

    findings_count = len(findings_data["findings"])
    print(colorize("\n  Import payload validation passed.", "bold"))
    print(colorize(f"  Findings parsed: {findings_count}", "dim"))
    if assessment_policy.assessments_present:
        count = int(assessment_policy.assessment_count)
        print(colorize(f"  Assessment entries in payload: {count}", "dim"))
    print(colorize("  No state changes were made (--validate-import).", "dim"))


__all__ = [
    "ImportFlagValidationError",
    "do_import",
    "do_validate_import",
    "subjective_at_target_dimensions",
]
