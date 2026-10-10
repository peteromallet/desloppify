from __future__ import annotations

from types import SimpleNamespace

import pytest

from desloppify.app.commands.scan.plan_reconcile import reconcile_plan_post_scan
from desloppify.base.subjective_dimensions import DISPLAY_NAMES
from desloppify.engine._plan.operations.lifecycle import purge_ids
from desloppify.engine._plan.persistence import load_plan, save_plan
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_REVIEW_INITIAL,
    LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT,
    current_lifecycle_phase,
    mark_postflight_scan_completed,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync import reconcile_plan
from desloppify.engine._work_queue.snapshot import build_queue_snapshot


def _placeholder_state() -> dict:
    display = DISPLAY_NAMES["naming_quality"]
    return {
        "issues": {},
        "work_items": {},
        "dimension_scores": {
            display: {
                "score": 0,
                "strict": 0,
                "failing": 0,
                "checks": 0,
                "detectors": {
                    "subjective_assessment": {
                        "placeholder": True,
                        "dimension_key": "naming_quality",
                    }
                },
            }
        },
        "subjective_assessments": {
            "naming_quality": {
                "score": 0,
                "placeholder": True,
            }
        },
        "assessment_import_audit": [],
    }


def _mark_review_complete(state: dict) -> None:
    display = DISPLAY_NAMES["naming_quality"]
    state["dimension_scores"][display] = {
        "score": 88.0,
        "strict": 88.0,
        "failing": 0,
        "checks": 1,
        "detectors": {
            "subjective_assessment": {
                "placeholder": False,
                "dimension_key": "naming_quality",
            }
        },
    }
    state["subjective_assessments"]["naming_quality"] = {
        "score": 88.0,
        "placeholder": False,
        "assessed_at": "2026-03-13T12:00:00+00:00",
    }
    state["issues"]["unused::src/app.ts::x"] = {
        "id": "unused::src/app.ts::x",
        "detector": "unused",
        "status": "open",
        "file": "src/app.ts",
        "tier": 1,
        "confidence": "high",
        "summary": "unused import",
        "detail": {},
    }
    state["work_items"] = state["issues"]


def test_postflight_progresses_review_then_workflow() -> None:
    state = _placeholder_state()
    plan = empty_plan()

    reconcile_plan(plan, state, target_strict=95.0)
    initial_snapshot = build_queue_snapshot(state, plan=plan)

    assert current_lifecycle_phase(plan) == "plan"
    assert initial_snapshot.phase == LIFECYCLE_PHASE_REVIEW_INITIAL
    assert [item["id"] for item in initial_snapshot.execution_items] == [
        "subjective::naming_quality"
    ]

    _mark_review_complete(state)
    purge_ids(plan, ["subjective::naming_quality"])
    mark_postflight_scan_completed(plan, scan_count=1)
    reconcile_plan(plan, state, target_strict=95.0)
    workflow_snapshot = build_queue_snapshot(state, plan=plan)

    assert current_lifecycle_phase(plan) == "plan"
    assert workflow_snapshot.phase == LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT
    assert not any(fid.startswith("subjective::") for fid in plan["queue_order"])
    assert all(item["id"].startswith("workflow::") for item in workflow_snapshot.execution_items)


@pytest.mark.parametrize("frozen_baseline", [False, True])
def test_first_scan_exposes_initial_review_after_freezing_scores(
    set_project_root, frozen_baseline
) -> None:
    state = _placeholder_state()
    state.update({"scan_count": 1, "strict_score": 20.0, "overall_score": 20.0})
    state["work_items"]["unused::src/app.ts::x"] = {
        "id": "unused::src/app.ts::x",
        "detector": "unused",
        "status": "open",
        "file": "src/app.ts",
        "tier": 1,
        "confidence": "high",
        "summary": "unused import",
        "detail": {},
    }
    plan_path = set_project_root / ".desloppify" / "plan.json"
    plan = empty_plan()
    if frozen_baseline:
        # An existing first-scan plan must recover without editing its markers.
        plan["queue_order"] = ["subjective::naming_quality"]
        plan["plan_start_scores"] = {"strict": 20.0}
        plan["refresh_state"] = {"lifecycle_phase": "plan"}
        assert build_queue_snapshot(state, plan=plan).phase == LIFECYCLE_PHASE_REVIEW_INITIAL
    save_plan(plan, plan_path)
    runtime = SimpleNamespace(
        state=state,
        state_path=plan_path.parent / "state-typescript.json",
        config={},
        force_rescan=False,
    )

    reconcile_plan_post_scan(runtime)
    plan = load_plan(plan_path)
    snapshot = build_queue_snapshot(state, plan=plan)

    if not frozen_baseline:
        assert plan["plan_start_scores"]["strict"] == 20.0
    assert snapshot.phase == LIFECYCLE_PHASE_REVIEW_INITIAL
    assert [item["id"] for item in snapshot.execution_items] == [
        "subjective::naming_quality"
    ]

    result = reconcile_plan(plan, state, target_strict=95.0)
    assert result.lifecycle_phase == snapshot.phase


def test_completed_review_still_requires_postflight_scan(set_project_root) -> None:
    state = _placeholder_state()
    display = DISPLAY_NAMES["naming_quality"]
    state["dimension_scores"][display]["score"] = 100.0
    state["dimension_scores"][display]["strict"] = 100.0
    state["dimension_scores"][display]["detectors"]["subjective_assessment"][
        "placeholder"
    ] = False
    state["subjective_assessments"]["naming_quality"] = {
        "score": 100.0,
        "placeholder": False,
    }
    state.update({"scan_count": 1, "strict_score": 100.0, "overall_score": 100.0})
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 75.0}
    plan["scan_count_at_plan_start"] = 1
    plan["refresh_state"] = {
        "lifecycle_phase": "execute",
        "subjective_review_completed_at_scan_count": 1,
    }
    before_scan = build_queue_snapshot(state, plan=plan)

    assert before_scan.phase == "scan"
    assert [item["id"] for item in before_scan.execution_items] == [
        "workflow::run-scan"
    ]

    plan_path = set_project_root / ".desloppify" / "plan.json"
    save_plan(plan, plan_path)
    state["scan_count"] = 2
    runtime = SimpleNamespace(
        state=state,
        state_path=plan_path.parent / "state-typescript.json",
        config={},
        force_rescan=False,
    )
    reconcile_plan_post_scan(runtime)
    plan = load_plan(plan_path)

    assert plan["refresh_state"]["postflight_scan_completed_at_scan_count"] == 2
    assert "workflow::run-scan" not in {
        item["id"] for item in build_queue_snapshot(state, plan=plan).execution_items
    }
