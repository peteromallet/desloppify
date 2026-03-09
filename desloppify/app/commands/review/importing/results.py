"""Result rendering helpers for review import flows."""

from __future__ import annotations

import desloppify.intelligence.narrative.core as narrative_mod
from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.queue_progress import show_score_with_plan_context
from desloppify.app.commands.scan.reporting import (
    dimensions as reporting_dimensions_mod,
)
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.output.terminal import colorize
from desloppify.intelligence.narrative.core import NarrativeContext

from . import helpers as import_helpers_mod


def print_import_results(
    *,
    state: dict,
    lang_name: str,
    config: dict | None,
    diff: dict,
    prev,
    label: str,
    provisional_count: int,
    assessment_policy,
    scorecard_subjective_at_target_fn,
) -> None:
    """Print import results, scores, and write query.json."""
    narrative = narrative_mod.compute_narrative(
        state,
        NarrativeContext(lang=lang_name, command="review"),
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
        state,
        colorize_fn=colorize,
    )
    show_score_with_plan_context(state, prev)
    at_target = import_helpers_mod.print_review_import_scores_and_integrity(
        state,
        config or {},
        state_mod=state_mod,
        target_strict_score_from_config_fn=target_strict_score_from_config,
        subjective_at_target_fn=scorecard_subjective_at_target_fn,
        subjective_rerun_command_fn=reporting_dimensions_mod.subjective_rerun_command,
        colorize_fn=colorize,
    )

    print(
        colorize(
            f"  Next command to improve subjective scores: `{next_command}`",
            "dim",
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


__all__ = ["print_import_results"]
