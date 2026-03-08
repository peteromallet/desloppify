"""Import flow helpers for review command."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desloppify.engine.plan import ReviewImportSyncResult

from desloppify import state as state_mod
from desloppify.app.commands.helpers.display import short_issue_id
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.queue_progress import show_score_with_plan_context
from desloppify.base.config import target_strict_score_from_config
from desloppify.app.commands.scan.reporting import (
    dimensions as reporting_dimensions_mod,
)
from desloppify.base.exception_sets import (
    PLAN_LOAD_EXCEPTIONS,
    CommandError,
    PacketValidationError,
)
from desloppify.base.output.terminal import colorize
from desloppify.intelligence import integrity as subjective_integrity_mod
import desloppify.intelligence.narrative.core as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.intelligence.narrative.core import NarrativeContext
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.intelligence.review.importing.contracts_models import (
    AssessmentImportPolicyModel,
)
from desloppify.intelligence.review.importing.contracts_types import (
    ReviewImportPayload,
)

from ..assessment_integrity import (
    bind_scorecard_subjective_at_target,
    subjective_at_target_dimensions,
)
from . import helpers as import_helpers_mod

_SCORECARD_SUBJECTIVE_AT_TARGET = bind_scorecard_subjective_at_target(
    reporting_dimensions_mod=reporting_dimensions_mod,
    subjective_integrity_mod=subjective_integrity_mod,
)


class ImportFlagValidationError(ValueError):
    """Raised when review import CLI flags are mutually incompatible."""


@dataclass(frozen=True)
class ReviewImportConfig:
    """Configuration bundle for review import/validate flows."""

    config: dict | None = None
    allow_partial: bool = False
    trusted_assessment_source: bool = False
    trusted_assessment_label: str | None = None
    attested_external: bool = False
    manual_override: bool = False
    manual_attest: str | None = None


def _build_import_load_config(
    *,
    lang_name: str | None,
    import_config: ReviewImportConfig,
    override_enabled: bool,
    override_attest: str | None,
) -> import_helpers_mod.ImportLoadConfig:
    return import_helpers_mod.ImportLoadConfig(
        lang_name=lang_name,
        allow_partial=import_config.allow_partial,
        trusted_assessment_source=import_config.trusted_assessment_source,
        trusted_assessment_label=import_config.trusted_assessment_label,
        attested_external=import_config.attested_external,
        manual_override=override_enabled,
        manual_attest=override_attest,
    )


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


def _imported_assessment_keys(issues_data: ReviewImportPayload) -> set[str]:
    """Return normalized assessment dimension keys from payload."""
    raw_assessments = issues_data["assessments"]
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



def _print_review_import_sync(state: dict, result: ReviewImportSyncResult) -> None:
    """Print summary of plan changes after review import sync."""
    new_ids = result.new_ids
    print(colorize(
        f"\n  Plan updated: {len(new_ids)} new review issue(s) added to queue.",
        "bold",
    ))
    issues = state.get("issues", {})
    for fid in sorted(new_ids)[:10]:
        f = issues.get(fid, {})
        print(f"    * [{short_issue_id(fid)}] {f.get('summary', '')}")
    if len(new_ids) > 10:
        print(colorize(f"    ... and {len(new_ids) - 10} more", "dim"))
    print()
    print(colorize("  New items added to end of queue.", "dim"))
    print()
    print(colorize("  View queue:            desloppify plan queue", "dim"))
    print(colorize("  View newest first:     desloppify plan queue --sort recent", "dim"))
    print()
    print(colorize("  NEXT STEP:  desloppify plan triage", "yellow"))
    print(colorize(
        "  (Review new issues and decide whether to re-plan or accept current queue.)",
        "dim",
    ))


def _sync_plan_after_import(state: dict, diff: dict, assessment_mode: str) -> None:
    """All post-import plan syncs. Load once, save once.

    Phase 1 (issue sync): Only when new/reopened issues arrived — adds them
    to queue, auto-resolves covered subjective items.
    Phase 2 (workflow items): Always — injects score-checkpoint, create-plan,
    import-scores, and communicate-score workflow items as needed.
    """
    try:
        from desloppify.engine.plan import (
            append_log_entry,
            current_unscored_ids,
            has_living_plan,
            load_plan,
            purge_ids,
            save_plan,
            sync_communicate_score_needed,
            sync_create_plan_needed,
            sync_import_scores_needed,
            sync_plan_after_review_import,
            sync_score_checkpoint_needed,
        )

        if not has_living_plan():
            return

        plan = load_plan()
        dirty = False

        # Phase 1: Issue sync (only when new/reopened issues arrived)
        has_new_issues = (
            int(diff.get("new", 0) or 0) > 0
            or int(diff.get("reopened", 0) or 0) > 0
        )
        import_result = None
        covered_ids: list[str] = []
        if has_new_issues:
            import_result = sync_plan_after_review_import(plan, state)
            if import_result is not None:
                dirty = True

            # Auto-resolve subjective dimension items that are no longer unscored
            still_unscored = current_unscored_ids(state)
            order = plan.get("queue_order", [])
            covered_ids = [
                fid for fid in order
                if fid.startswith("subjective::") and fid not in still_unscored
            ]
            if covered_ids:
                purge_ids(plan, covered_ids)
                dirty = True

        # Phase 2: Workflow items (always)
        injected_parts: list[str] = []

        checkpoint_result = sync_score_checkpoint_needed(plan, state)
        if checkpoint_result.changes:
            dirty = True
            injected_parts.append("`workflow::score-checkpoint`")

        scores_imported = assessment_mode in (
            "trusted_internal", "attested_external", "manual_override",
        )
        import_scores_result = sync_import_scores_needed(
            plan, state, assessment_mode=assessment_mode,
        )
        if import_scores_result.changes:
            dirty = True
            injected_parts.append("`workflow::import-scores`")

        communicate_result = sync_communicate_score_needed(
            plan, state, scores_just_imported=scores_imported,
        )
        if communicate_result.changes:
            dirty = True
            injected_parts.append("`workflow::communicate-score`")

        create_plan_result = sync_create_plan_needed(plan, state)
        if create_plan_result.changes:
            dirty = True
            injected_parts.append("`workflow::create-plan`")

        # Save once
        if dirty:
            if import_result is not None:
                append_log_entry(
                    plan,
                    "review_import_sync",
                    actor="system",
                    detail={
                        "trigger": "review_import",
                        "new_ids": sorted(import_result.new_ids),
                        "added_to_queue": import_result.added_to_queue,
                        "diff_new": diff.get("new", 0),
                        "diff_reopened": diff.get("reopened", 0),
                        "covered_subjective": covered_ids,
                    },
                )
            save_plan(plan)

        # Print results
        if import_result is not None:
            _print_review_import_sync(state, import_result)
        if injected_parts:
            print(colorize(
                f"  Plan: {' and '.join(injected_parts)} queued. Run `desloppify next`.",
                "cyan",
            ))
    except PLAN_LOAD_EXCEPTIONS as exc:
        print(
            colorize(
                f"  Note: skipped plan sync after review import ({exc}).",
                "dim",
            )
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
        _validate_import_flag_combos(
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
            config=_build_import_load_config(
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

    # Transactional import: only persist if all post-import guards pass.
    # Rebase on the latest on-disk state when available so long-running review
    # sessions don't clobber newer imports/scans that completed while batches ran.
    state_path = Path(state_file) if state_file is not None else None
    if state_path is not None and state_path.exists():
        working_state = copy.deepcopy(state_mod.load_state(state_path))
    else:
        working_state = copy.deepcopy(state)
    diff = review_mod.import_holistic_issues(issues_data, working_state, lang.name)
    label = "Holistic review"
    imported_assessment_keys = _imported_assessment_keys(issues_data)
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

        # Sync plan: issue sync (if new issues) + workflow items (always).
        _sync_plan_after_import(state, diff, assessment_policy.mode)

    # In dry-run mode, state was never updated — use working_state for display.
    display_state = state if not dry_run else working_state
    _print_import_results(
        state=display_state,
        lang_name=lang.name,
        config=import_config.config,
        diff=diff,
        prev=prev,
        label=label,
        provisional_count=provisional_count,
        assessment_policy=assessment_policy,
    )


def _print_import_results(
    *,
    state: dict,
    lang_name: str,
    config: dict | None,
    diff: dict,
    prev: dict,
    label: str,
    provisional_count: int,
    assessment_policy,
) -> None:
    """Print import results, scores, and write query.json."""
    narrative = narrative_mod.compute_narrative(
        state, NarrativeContext(lang=lang_name, command="review")
    )

    print(colorize(f"\n  {label} imported:", "bold"))
    issue_count = int(diff.get("new", 0) or 0)
    print(
        colorize(
            f"  +{issue_count} new issue{'s' if issue_count != 1 else ''} "
            f"(review issues), "
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
                "a trusted review path (see skill doc for options).",
                "yellow",
            )
        )
    import_helpers_mod.print_skipped_validation_details(diff, colorize_fn=colorize)
    import_helpers_mod.print_assessments_summary(state, colorize_fn=colorize)
    next_command = import_helpers_mod.print_open_review_summary(
        state, colorize_fn=colorize
    )
    show_score_with_plan_context(state, prev)
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
        _validate_import_flag_combos(
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
            config=_build_import_load_config(
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
