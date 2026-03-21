from __future__ import annotations

from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_EXECUTE,
    LIFECYCLE_PHASE_REVIEW_POSTFLIGHT,
    LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync.phase_cleanup import prune_synthetic_for_phase


def test_workflow_cleanup_prunes_only_subjective_items() -> None:
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::naming_quality",
        "workflow::communicate-score",
        "triage::observe",
        "unused::src/a.ts::x",
    ]
    plan["overrides"] = {
        "subjective::naming_quality": {"issue_id": "subjective::naming_quality"},
        "workflow::communicate-score": {"issue_id": "workflow::communicate-score"},
    }
    plan["clusters"] = {
        "mixed": {
            "name": "mixed",
            "issue_ids": [
                "subjective::naming_quality",
                "workflow::communicate-score",
                "unused::src/a.ts::x",
            ],
        }
    }

    pruned = prune_synthetic_for_phase(plan, LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT)

    assert pruned == []
    assert plan["queue_order"] == [
        "subjective::naming_quality",
        "workflow::communicate-score",
        "triage::observe",
        "unused::src/a.ts::x",
    ]
    assert "subjective::naming_quality" in plan["overrides"]
    assert plan["clusters"]["mixed"]["issue_ids"] == [
        "subjective::naming_quality",
        "workflow::communicate-score",
        "unused::src/a.ts::x",
    ]


def test_review_postflight_cleanup_prunes_subjective_and_workflow() -> None:
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::naming_quality",
        "workflow::communicate-score",
        "review::src/a.ts::naming",
    ]

    pruned = prune_synthetic_for_phase(plan, LIFECYCLE_PHASE_REVIEW_POSTFLIGHT)

    assert pruned == ["workflow::communicate-score"]
    assert plan["queue_order"] == [
        "subjective::naming_quality",
        "review::src/a.ts::naming",
    ]


def test_execute_cleanup_prunes_all_synthetic_prefixes() -> None:
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::naming_quality",
        "workflow::communicate-score",
        "triage::observe",
        "unused::src/a.ts::x",
    ]

    pruned = prune_synthetic_for_phase(plan, LIFECYCLE_PHASE_EXECUTE)

    assert pruned == [
        "workflow::communicate-score",
        "triage::observe",
    ]
    assert plan["queue_order"] == [
        "subjective::naming_quality",
        "unused::src/a.ts::x",
    ]
