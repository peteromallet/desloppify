"""Post-import plan sync for review importing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from desloppify.app.commands.helpers.display import short_issue_id
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize

if TYPE_CHECKING:
    from desloppify.engine.plan import ReviewImportSyncResult


def _print_review_import_sync(state: dict, result: ReviewImportSyncResult) -> None:
    """Print summary of plan changes after review import sync."""
    new_ids = result.new_ids
    print(colorize(
        f"\n  Plan updated: {len(new_ids)} new review issue(s) added to queue.",
        "bold",
    ))
    issues = state.get("issues", {})
    for finding_id in sorted(new_ids)[:10]:
        finding = issues.get(finding_id, {})
        print(f"    * [{short_issue_id(finding_id)}] {finding.get('summary', '')}")
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


def sync_plan_after_import(state: dict, diff: dict, assessment_mode: str) -> None:
    """Apply issue/workflow syncs after import in one load/save cycle."""
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

            still_unscored = current_unscored_ids(state)
            order = plan.get("queue_order", [])
            covered_ids = [
                finding_id for finding_id in order
                if finding_id.startswith("subjective::") and finding_id not in still_unscored
            ]
            if covered_ids:
                purge_ids(plan, covered_ids)
                dirty = True

        injected_parts: list[str] = []

        checkpoint_result = sync_score_checkpoint_needed(plan, state)
        if checkpoint_result.changes:
            dirty = True
            injected_parts.append("`workflow::score-checkpoint`")

        scores_imported = assessment_mode in (
            "trusted_internal",
            "attested_external",
            "manual_override",
        )
        import_scores_result = sync_import_scores_needed(
            plan,
            state,
            assessment_mode=assessment_mode,
        )
        if import_scores_result.changes:
            dirty = True
            injected_parts.append("`workflow::import-scores`")

        communicate_result = sync_communicate_score_needed(
            plan,
            state,
            scores_just_imported=scores_imported,
        )
        if communicate_result.changes:
            dirty = True
            injected_parts.append("`workflow::communicate-score`")

        create_plan_result = sync_create_plan_needed(plan, state)
        if create_plan_result.changes:
            dirty = True
            injected_parts.append("`workflow::create-plan`")

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


__all__ = ["sync_plan_after_import"]
