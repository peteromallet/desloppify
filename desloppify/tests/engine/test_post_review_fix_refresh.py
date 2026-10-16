"""A fix made after an assessment must remain available for reassessment."""

from copy import deepcopy

import pytest

from desloppify.engine._work_queue.synthetic import build_subjective_items

IMPORT_TIME = "2026-01-01T10:00:00+00:00"
FIX_TIME = "2026-01-01T10:20:00+00:00"
DIMENSION_ID = "subjective::naming_quality"


def _state():
    return {
        "scan_count": 2,
        "assessment_import_audit": [
            {"timestamp": IMPORT_TIME, "mode": "trusted_internal"}
        ],
        "dimension_scores": {
            "Naming quality": {
                "score": 60.0,
                "strict": 60.0,
                "checks": 1,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            }
        },
        "subjective_assessments": {
            "naming_quality": {
                "score": 60.0,
                "assessed_at": IMPORT_TIME,
                "needs_review_refresh": True,
                "refresh_reason": "review_issue_fixed",
                "stale_since": FIX_TIME,
            }
        },
    }


def _plan(phase="plan"):
    return {
        "queue_order": [DIMENSION_ID],
        "refresh_state": {
            "lifecycle_phase": phase,
            "postflight_scan_completed_at_scan_count": 2,
            "subjective_review_completed_at_scan_count": 1,
        },
    }


def _ids(state, plan=None):
    return [
        item["id"]
        for item in build_subjective_items(
            state, {}, threshold=95.0, plan=plan or _plan()
        )
    ]


def test_fix_after_import_remains_available_without_mutating_inputs():
    state = _state()
    plan = _plan()
    original_state, original_plan = deepcopy(state), deepcopy(plan)

    assert _ids(state, plan) == [DIMENSION_ID]
    assert state == original_state
    assert plan == original_plan


def test_fix_already_covered_by_trusted_assessment_stays_suppressed():
    state = _state()
    state["subjective_assessments"]["naming_quality"]["stale_since"] = (
        "2026-01-01T09:59:00+00:00"
    )

    assert _ids(state) == []


def test_equal_second_fix_timing_is_ambiguous_and_remains_visible():
    state = _state()
    state["subjective_assessments"]["naming_quality"]["stale_since"] = IMPORT_TIME

    assert _ids(state) == [DIMENSION_ID]


def test_a_later_assessment_demonstrably_covers_an_earlier_fix():
    state = _state()
    state["subjective_assessments"]["naming_quality"]["assessed_at"] = (
        "2026-01-01T10:30:00+00:00"
    )

    assert _ids(state) == []


@pytest.mark.parametrize("field", ["stale_since", "assessed_at"])
@pytest.mark.parametrize("value", [None, "", "invalid", "2026-01-01T10:00:00"])
def test_unverifiable_fix_timing_is_not_suppressed(field, value):
    state = _state()
    payload = state["subjective_assessments"]["naming_quality"]
    if value is None:
        payload.pop(field)
    else:
        payload[field] = value

    assert _ids(state) == [DIMENSION_ID]


@pytest.mark.parametrize("audit_time", ["", "invalid", "2026-01-01T10:00:00"])
def test_unverifiable_trusted_import_timing_does_not_hide_a_fix(audit_time):
    state = _state()
    state["assessment_import_audit"][0]["timestamp"] = audit_time
    state["subjective_assessments"]["naming_quality"]["stale_since"] = IMPORT_TIME

    assert _ids(state) == [DIMENSION_ID]


@pytest.mark.parametrize("audit_mode", ["trusted_internal", "attested_external"])
def test_equivalent_timezone_offsets_preserve_same_import_suppression(audit_mode):
    state = _state()
    state["assessment_import_audit"][0]["mode"] = audit_mode
    payload = state["subjective_assessments"]["naming_quality"]
    payload["assessed_at"] = "2026-01-01T05:00:00-05:00"
    payload["stale_since"] = "2026-01-01T09:59:00+00:00"

    assert _ids(state) == []


def test_equal_instants_with_different_offsets_remain_ambiguous():
    state = _state()
    state["subjective_assessments"]["naming_quality"]["stale_since"] = (
        "2026-01-01T05:00:00-05:00"
    )

    assert _ids(state) == [DIMENSION_ID]


def test_later_fix_with_different_timezone_is_not_self_invalidation():
    state = _state()
    state["subjective_assessments"]["naming_quality"]["stale_since"] = (
        "2026-01-01T05:20:00-05:00"
    )

    assert _ids(state) == [DIMENSION_ID]


@pytest.mark.parametrize("reason", ["mechanical_issues_changed", "time_elapsed"])
def test_unrelated_refresh_reasons_remain_visible(reason):
    state = _state()
    state["subjective_assessments"]["naming_quality"]["refresh_reason"] = reason

    assert _ids(state) == [DIMENSION_ID]


@pytest.mark.parametrize("reason", ["review_issue_wontfix", "review_issue_imported"])
def test_non_fix_same_cycle_refresh_policy_is_preserved(reason):
    state = _state()
    state["subjective_assessments"]["naming_quality"]["refresh_reason"] = reason

    assert _ids(state) == []


def test_execution_phase_does_not_apply_planning_suppression():
    assert _ids(_state(), _plan("execute")) == [DIMENSION_ID]


def test_assessment_older_than_latest_trusted_import_is_not_suppressed():
    state = _state()
    state["assessment_import_audit"][0]["timestamp"] = FIX_TIME
    state["subjective_assessments"]["naming_quality"]["stale_since"] = IMPORT_TIME

    assert _ids(state) == [DIMENSION_ID]


def test_fresh_below_target_review_still_follows_postflight_completion():
    state = _state()
    state["subjective_assessments"]["naming_quality"].pop("needs_review_refresh")
    plan = _plan()
    assert _ids(state, plan) == [DIMENSION_ID]

    plan["refresh_state"]["subjective_review_completed_at_scan_count"] = 2
    assert _ids(state, plan) == []
