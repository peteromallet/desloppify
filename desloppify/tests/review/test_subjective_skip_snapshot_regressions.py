"""Synthetic skip visibility and never-reviewed dimension lifecycle regressions."""

from __future__ import annotations

from copy import deepcopy

import pytest

from desloppify.base.subjective_dimensions import DISPLAY_NAMES
from desloppify.engine._plan.constants import WORKFLOW_DEFERRED_DISPOSITION_ID
from desloppify.engine._plan.operations.skip import skip_items, unskip_items
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT,
    LIFECYCLE_PHASE_REVIEW_INITIAL,
    LIFECYCLE_PHASE_SCAN,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync import reconcile_plan
from desloppify.engine._work_queue.core import QueueBuildOptions, build_work_queue
from desloppify.engine._work_queue.snapshot import build_queue_snapshot


def _subjective_state(*dimension_keys: str, initial: bool = False) -> dict:
    score = 0.0 if initial else 70.0
    dimension_scores = {}
    assessments = {}
    for dimension_key in dimension_keys:
        dimension_scores[DISPLAY_NAMES[dimension_key]] = {
            "score": score,
            "strict": score,
            "failing": 0,
            "checks": 0 if initial else 1,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dimension_key,
                    "placeholder": initial,
                },
            },
        }
        assessments[dimension_key] = {
            "score": score,
            "placeholder": initial,
            "needs_review_refresh": not initial,
        }
    issues: dict[str, dict] = {}
    return {
        "issues": issues,
        "work_items": issues,
        "scan_count": 5,
        "dimension_scores": dimension_scores,
        "subjective_assessments": assessments,
        "assessment_import_audit": [],
    }


def _plan_with_subjective_items(*dimension_keys: str) -> dict:
    plan = empty_plan()
    plan["queue_order"] = [f"subjective::{key}" for key in dimension_keys]
    plan["refresh_state"] = {
        "lifecycle_phase": "plan",
        "postflight_scan_completed_at_scan_count": 5,
    }
    return plan


def _visible_ids(state: dict, plan: dict) -> set[str]:
    queue = build_work_queue(
        state,
        options=QueueBuildOptions(count=None, include_subjective=True, plan=plan),
    )
    return {item["id"] for item in queue["items"]}


@pytest.mark.parametrize("initial", [True, False], ids=["initial", "postflight"])
def test_skip_unskip_filters_only_the_matching_synthetic_dimension(initial: bool) -> None:
    state = _subjective_state("naming_quality", "error_consistency", initial=initial)
    original_state = deepcopy(state)
    plan = _plan_with_subjective_items("naming_quality", "error_consistency")
    skipped_id = "subjective::naming_quality"
    remaining_id = "subjective::error_consistency"
    expected_phase = (
        LIFECYCLE_PHASE_REVIEW_INITIAL
        if initial
        else LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT
    )

    assert _visible_ids(state, plan) == {skipped_id, remaining_id}
    assert skip_items(plan, [skipped_id]) == 1

    snapshot = build_queue_snapshot(state, plan=plan)
    assert snapshot.phase == expected_phase
    assert _visible_ids(state, plan) == {remaining_id}
    assert {item["id"] for item in snapshot.execution_items} == {remaining_id}
    assert skipped_id not in {item["id"] for item in snapshot.backlog_items}
    assert snapshot.subjective_initial_count == (1 if initial else 0)
    assert snapshot.subjective_postflight_count == (0 if initial else 1)
    assert snapshot.assessment_postflight_count == (0 if initial else 1)

    assert unskip_items(plan, [skipped_id]) == (1, [skipped_id], [])
    restored = build_queue_snapshot(state, plan=plan)
    assert restored.phase == expected_phase
    assert _visible_ids(state, plan) == {skipped_id, remaining_id}
    assert restored.subjective_initial_count == (2 if initial else 0)
    assert restored.subjective_postflight_count == (0 if initial else 2)
    assert restored.assessment_postflight_count == (0 if initial else 2)
    assert state == original_state


@pytest.mark.parametrize("initial", [True, False], ids=["initial", "postflight"])
def test_skipping_last_subjective_item_releases_phase_until_unskipped(initial: bool) -> None:
    state = _subjective_state("naming_quality", initial=initial)
    original_state = deepcopy(state)
    plan = _plan_with_subjective_items("naming_quality")
    subjective_id = "subjective::naming_quality"
    expected_phase = (
        LIFECYCLE_PHASE_REVIEW_INITIAL
        if initial
        else LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT
    )
    assert build_queue_snapshot(state, plan=plan).phase == expected_phase

    skip_items(plan, [subjective_id])

    snapshot = build_queue_snapshot(state, plan=plan)
    assert snapshot.phase == LIFECYCLE_PHASE_SCAN
    assert _visible_ids(state, plan) == set()
    assert WORKFLOW_DEFERRED_DISPOSITION_ID not in {
        item["id"] for item in snapshot.all_scan_items
    }
    assert snapshot.subjective_initial_count == 0
    assert snapshot.subjective_postflight_count == 0
    assert snapshot.assessment_postflight_count == 0
    assert subjective_id not in {item["id"] for item in snapshot.backlog_items}

    unskip_items(plan, [subjective_id])

    assert build_queue_snapshot(state, plan=plan).phase == expected_phase
    assert _visible_ids(state, plan) == {subjective_id}
    assert state == original_state


def test_unrelated_synthetic_skip_preserves_subjective_visibility_and_assessments() -> None:
    state = _subjective_state("naming_quality", "error_consistency")
    original_state = deepcopy(state)
    plan = _plan_with_subjective_items("naming_quality", "error_consistency")

    skip_items(plan, ["subjective::abstraction_fit"])

    snapshot = build_queue_snapshot(state, plan=plan)
    assert snapshot.phase == LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT
    assert _visible_ids(state, plan) == {
        "subjective::naming_quality",
        "subjective::error_consistency",
    }
    assert snapshot.subjective_postflight_count == 2
    assert snapshot.assessment_postflight_count == 2
    assert state == original_state


@pytest.mark.parametrize("skip_kind", ["temporary", "permanent"])
def test_fresh_cycle_reconciliation_resurfaces_skipped_never_reviewed_dimensions(
    skip_kind: str,
) -> None:
    state = _subjective_state("naming_quality", initial=True)
    original_state = deepcopy(state)
    plan = empty_plan()
    subjective_id = "subjective::naming_quality"
    skip_items(plan, [subjective_id], kind=skip_kind)
    assert _visible_ids(state, plan).isdisjoint({subjective_id})

    result = reconcile_plan(plan, state, target_strict=95.0)

    snapshot = build_queue_snapshot(state, plan=plan)
    assert subjective_id in result.subjective.resurfaced
    assert subjective_id not in plan["skipped"]
    assert subjective_id in plan["queue_order"]
    assert snapshot.phase == LIFECYCLE_PHASE_REVIEW_INITIAL
    assert snapshot.subjective_initial_count == 1
    assert snapshot.subjective_postflight_count == 0
    assert _visible_ids(state, plan) == {subjective_id}
    assert state == original_state
