"""Behavioral coverage for canonical execution and backlog partitions."""

from __future__ import annotations

from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.snapshot import build_queue_snapshot


def test_backlog_has_unique_ids_across_mixed_work_item_kinds() -> None:
    planned_id = "smells::src/a.py::planned"
    mechanical_id = "smells::src/b.py::unplanned"
    review_id = "review::src/b.py::naming"
    assessment_id = "subjective_review::src/b.py::assessment"
    state = {
        "work_items": {
            item_id: {
                "id": item_id,
                "detector": detector,
                "work_item_kind": work_item_kind,
                "file": "src/b.py",
                "status": "open",
                "confidence": "high",
                "tier": 3,
                "summary": item_id,
                "detail": {},
            }
            for item_id, detector, work_item_kind in (
                (planned_id, "smells", "mechanical_defect"),
                (mechanical_id, "smells", "mechanical_defect"),
                (review_id, "review", "review_defect"),
                (assessment_id, "subjective_review", "assessment_request"),
            )
        },
    }
    plan = empty_plan()
    plan["queue_order"] = [planned_id]
    plan["plan_start_scores"] = {"strict": 75.0}
    plan["refresh_state"] = {
        "lifecycle_phase": "execute",
        "postflight_scan_completed_at_scan_count": 1,
    }

    snapshot = build_queue_snapshot(state, plan=plan)

    assert [item["id"] for item in snapshot.execution_items] == [planned_id]
    assert [item["id"] for item in snapshot.backlog_items] == [
        mechanical_id,
        assessment_id,
        review_id,
    ]
