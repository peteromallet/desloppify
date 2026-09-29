"""Trusted partial imports must retain coverage until the next scan boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest

from desloppify.app.commands.review.importing.cmd import _append_assessment_import_audit
from desloppify.engine._work_queue.synthetic import build_subjective_items
from desloppify.intelligence.review.importing.contracts_models import (
    AssessmentImportPolicyModel,
)

BOUNDARY = "2026-03-13T04:00:00+00:00"
FIRST = "2026-03-13T04:10:00+00:00"
SECOND = "2026-03-13T04:12:00+00:00"
POSTFLIGHT = "2026-03-13T05:00:00+00:00"
DIMENSIONS = {"naming_quality": "Naming quality", "type_safety": "Type safety"}


def _partial_imports(*, legacy: bool = False) -> tuple[dict, dict]:
    state = {
        "scan_count": 3,
        "scan_history": [{"timestamp": BOUNDARY}],
        "assessment_import_audit": [],
        "dimension_scores": {},
        "subjective_assessments": {},
    }
    plan = {
        "refresh_state": {
            "lifecycle_phase": "plan",
            "postflight_scan_completed_at_scan_count": 3,
            "subjective_review_completed_at_scan_count": 3,
        },
        "execution_log": [
            {"action": "complete_postflight_scan", "timestamp": BOUNDARY}
        ],
    }
    for (dimension, display), timestamp in zip(
        DIMENSIONS.items(), (FIRST, SECOND), strict=True
    ):
        audit = {"timestamp": timestamp, "mode": "trusted_internal"}
        if not legacy:
            audit["assessment_timestamps"] = {dimension: timestamp}
            audit["scan_timestamp"] = timestamp
        state["assessment_import_audit"].append(audit)
        state["scan_history"].append({"timestamp": timestamp})
        state["dimension_scores"][display] = {
            "score": 70.0,
            "strict": 70.0,
            "failing": 1,
            "detectors": {"subjective_assessment": {"dimension_key": dimension}},
        }
        state["subjective_assessments"][dimension] = {
            "score": 70.0,
            "assessed_at": timestamp,
            "needs_review_refresh": True,
            "refresh_reason": "review_issue_wontfix",
            "stale_since": "2026-03-13T04:20:00+00:00",
        }
        plan["execution_log"].append(
            {
                "action": "review_import_sync",
                "timestamp": timestamp,
                "detail": {"covered_subjective": [f"subjective::{dimension}"]},
            }
        )
    return state, plan


def _queued_dimensions(state: dict, plan: dict) -> set[str]:
    return {
        item["detail"]["dimension"]
        for item in build_subjective_items(state, {}, threshold=95.0, plan=plan)
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_partial_trusted_imports_keep_each_dimension_fresh_in_the_cycle(
    legacy: bool,
) -> None:
    state, plan = _partial_imports(legacy=legacy)
    before = deepcopy((state, plan))

    assert _queued_dimensions(state, plan) == set()
    assert (state, plan) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_real_postflight_scan_expires_all_previous_partial_imports(
    legacy: bool,
) -> None:
    state, plan = _partial_imports(legacy=legacy)
    state["scan_count"] = 4
    plan["refresh_state"]["postflight_scan_completed_at_scan_count"] = 4
    plan["execution_log"].append(
        {"action": "complete_postflight_scan", "timestamp": POSTFLIGHT}
    )

    assert _queued_dimensions(state, plan) == set(DIMENSIONS)


def test_current_trusted_import_does_not_cover_an_unimported_dimension() -> None:
    state, plan = _partial_imports()
    # Identical timestamps are not evidence that an unrelated dimension was covered.
    state["subjective_assessments"]["naming_quality"]["assessed_at"] = SECOND

    assert _queued_dimensions(state, plan) == {"naming_quality"}


def test_audit_covers_the_exact_assessment_revision() -> None:
    state, plan = _partial_imports()
    state["subjective_assessments"]["naming_quality"]["assessed_at"] = BOUNDARY

    assert _queued_dimensions(state, plan) == {"naming_quality"}


@pytest.mark.parametrize("mode", ["manual_override", "issues_only", "untrusted"])
def test_untrusted_imports_do_not_suppress_refresh(mode: str) -> None:
    state, plan = _partial_imports()
    state["assessment_import_audit"][0]["mode"] = mode

    assert _queued_dimensions(state, plan) == {"naming_quality"}


@pytest.mark.parametrize("reason", ["mechanical_issues_changed", "assessment_expired"])
def test_other_staleness_still_requires_review(reason: str) -> None:
    state, plan = _partial_imports()
    state["subjective_assessments"]["naming_quality"]["refresh_reason"] = reason

    assert _queued_dimensions(state, plan) == {"naming_quality"}


def test_review_import_can_cross_a_clock_second() -> None:
    state, plan = _partial_imports()
    # Storing the assessment and appending the audit are separate clock reads.
    state["assessment_import_audit"][0]["timestamp"] = "2026-03-13T04:10:01+00:00"

    assert _queued_dimensions(state, plan) == set()


def test_fresh_partial_import_after_postflight_only_covers_its_dimension() -> None:
    state, plan = _partial_imports()
    plan["execution_log"].insert(
        2,
        {
            "action": "complete_postflight_scan",
            "timestamp": "2026-03-13T04:11:00+00:00",
        },
    )

    assert _queued_dimensions(state, plan) == {"naming_quality"}


def test_next_scan_expires_coverage_before_the_postflight_log_is_written() -> None:
    state, plan = _partial_imports()
    state["last_scan"] = POSTFLIGHT
    state["scan_count"] = 4
    plan["execution_log"] = []

    assert _queued_dimensions(state, plan) == set(DIMENSIONS)


@pytest.mark.parametrize("legacy", [False, True])
def test_later_partial_import_does_not_hide_a_scan_between_imports(
    legacy: bool,
) -> None:
    state, plan = _partial_imports(legacy=legacy)
    state["scan_history"].insert(2, {"timestamp": "2026-03-13T04:11:00+00:00"})
    state["last_scan"] = SECOND

    assert _queued_dimensions(state, plan) == {"naming_quality"}


def test_manual_review_merge_does_not_count_as_a_new_real_scan() -> None:
    state, plan = _partial_imports()
    timestamp = "2026-03-13T04:13:00+00:00"
    state["scan_history"].append({"timestamp": timestamp})
    state["assessment_import_audit"].append(
        {
            "timestamp": "2026-03-13T04:13:01+00:00",
            "scan_timestamp": timestamp,
            "mode": "manual_override",
            "assessment_timestamps": {},
        }
    )

    assert _queued_dimensions(state, plan) == set()


def test_issues_only_review_merge_does_not_count_as_a_new_real_scan() -> None:
    state, plan = _partial_imports()
    timestamp = "2026-03-13T04:13:00+00:00"
    state["scan_history"].append({"timestamp": timestamp})
    plan["execution_log"].append(
        {
            "action": "review_import_sync",
            "timestamp": "2026-03-13T04:13:01+00:00",
            "detail": {"scan_timestamp": timestamp, "covered_subjective": []},
        }
    )

    assert _queued_dimensions(state, plan) == set()


@pytest.mark.parametrize("flag", ["placeholder", "provisional_override"])
def test_unassessed_and_provisional_revisions_still_require_review(flag: str) -> None:
    state, plan = _partial_imports()
    state["subjective_assessments"]["naming_quality"][flag] = True

    assert _queued_dimensions(state, plan) == {"naming_quality"}


def test_import_audit_records_only_payload_dimensions_and_exact_revisions(
    monkeypatch,
) -> None:
    state, plan = _partial_imports()
    state["assessment_import_audit"] = []
    state["scan_history"] = []
    # A later clock read must not lose the actual assessment revision.
    monkeypatch.setattr(
        "desloppify.app.commands.review.importing.cmd.utc_now",
        lambda: "2026-03-13T04:12:01+00:00",
    )
    policy = AssessmentImportPolicyModel(
        assessments_present=True,
        assessment_count=1,
        trusted=True,
        mode="trusted_internal",
    )
    for dimension, timestamp in zip(DIMENSIONS, (FIRST, SECOND), strict=True):
        state["last_scan"] = timestamp
        _append_assessment_import_audit(
            working_state=state,
            assessment_policy=policy,
            provisional_count=0,
            override_attest=None,
            import_file="synthetic.json",
            import_payload={"assessments": {dimension: 70.0}},
        )
        assert state["assessment_import_audit"][-1]["assessment_timestamps"] == {
            dimension: timestamp,
        }
        assert state["assessment_import_audit"][-1]["scan_timestamp"] == timestamp

    # These imports do not share timestamps with the legacy log entries.
    assert _queued_dimensions(state, plan) == set()
