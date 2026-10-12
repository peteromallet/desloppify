"""Skipped subjective refreshes must not gate other execution phases."""

from __future__ import annotations

from desloppify.base.subjective_dimensions import DISPLAY_NAMES
from desloppify.engine._plan.constants import WORKFLOW_RUN_SCAN_ID
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine._work_queue.snapshot import build_queue_snapshot
from desloppify.engine.planning.queue_policy import build_execution_queue

DIMENSION_KEY = "design_coherence"
SUBJECTIVE_ID = f"subjective::{DIMENSION_KEY}"


def _stale_subjective_state(*, with_mechanical_issue: bool) -> dict:
    work_items: dict[str, dict] = {}
    if with_mechanical_issue:
        issue_id = "unused::src/a.py::obsolete-import"
        work_items[issue_id] = {
            "id": issue_id,
            "detector": "unused",
            "status": "open",
            "file": "src/a.py",
            "tier": 2,
            "confidence": "high",
            "summary": "Unused import",
            "detail": {},
        }

    display_name = DISPLAY_NAMES[DIMENSION_KEY]
    return {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 3,
        "config": {"target_strict_score": 95.0},
        "dimension_scores": {
            display_name: {
                "score": 79.0,
                "strict": 79.0,
                "failing": 1,
                "checks": 1,
                "detectors": {
                    "subjective_assessment": {
                        "placeholder": False,
                        "dimension_key": DIMENSION_KEY,
                    }
                },
            }
        },
        "subjective_assessments": {
            DIMENSION_KEY: {
                "score": 79.0,
                "needs_review_refresh": True,
                "refresh_reason": "review_issue_deferred",
            }
        },
    }


def _plan(*, with_mechanical_issue: bool) -> dict:
    queue_order = ["unused::src/a.py::obsolete-import"] if with_mechanical_issue else []
    return {
        "queue_order": queue_order,
        "skipped": {SUBJECTIVE_ID: {"kind": "temporary"}},
        "plan_start_scores": {"strict": 75.0},
        "refresh_state": {
            "lifecycle_phase": "plan",
            "postflight_scan_completed_at_scan_count": 3,
        },
    }


def test_skipped_stale_assessment_does_not_hide_planned_mechanical_work() -> None:
    state = _stale_subjective_state(with_mechanical_issue=True)
    plan = _plan(with_mechanical_issue=True)

    snapshot = build_queue_snapshot(state, plan=plan)
    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(plan=plan, count=None),
    )

    assert snapshot.phase == "execute"
    assert [item["id"] for item in snapshot.execution_items] == [
        "unused::src/a.py::obsolete-import"
    ]
    assert [item["id"] for item in queue["items"]] == [
        "unused::src/a.py::obsolete-import"
    ]
    assert SUBJECTIVE_ID not in {item["id"] for item in queue["items"]}


def test_skipped_stale_assessment_does_not_hide_pending_scan() -> None:
    state = _stale_subjective_state(with_mechanical_issue=False)
    plan = _plan(with_mechanical_issue=False)
    plan["refresh_state"].pop("postflight_scan_completed_at_scan_count")

    snapshot = build_queue_snapshot(state, plan=plan)
    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(plan=plan, count=None),
    )

    assert snapshot.phase == "scan"
    assert [item["id"] for item in snapshot.execution_items] == [WORKFLOW_RUN_SCAN_ID]
    assert [item["id"] for item in queue["items"]] == [WORKFLOW_RUN_SCAN_ID]
