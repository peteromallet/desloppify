"""Only new corroboration changes scan deltas or assessment freshness."""

from __future__ import annotations

import copy

import pytest

import desloppify.engine._state.merge as merge_mod
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.schema import empty_state

EARLY = "2026-01-01T10:00:00+00:00"
FIRST_SCAN = "2026-01-01T11:00:00+00:00"
REVIEW = "2026-01-01T12:00:00+00:00"
AUDIT = "2026-01-01T12:00:01+00:00"
NEXT_SCAN = "2026-01-01T13:00:00+00:00"
LATER_SCAN = "2026-01-01T14:00:00+00:00"


def _state_with_resolution(status):
    state = empty_state()
    issue = make_issue(
        "structural",
        "src/example.py",
        "large",
        tier=3,
        confidence="high",
        summary="Synthetic structural concern",
        detail={"loc": 500},
    )
    issue.update(status=status, last_seen=EARLY, resolved_at=EARLY)
    issue["resolution_attestation"] = {
        "kind": "manual",
        "text": "Reviewed synthetic issue",
        "attested_at": EARLY,
        "scan_verified": False,
    }
    state["work_items"][issue["id"]] = issue
    return state, issue


def _fresh_review(state):
    state["subjective_assessments"] = {
        "design_coherence": {
            "score": 80.0,
            "assessed_at": REVIEW,
            "source": "holistic",
        },
    }
    # The audit can legitimately be written a second after assessment storage.
    # Idempotence must not depend on the timestamp reconciliation escape hatch.
    state["assessment_import_audit"] = [
        {"mode": "trusted_internal", "timestamp": AUDIT}
    ]


@pytest.mark.parametrize("status", ["fixed", "false_positive", "wontfix"])
@pytest.mark.parametrize("scan_path", [".", "other"])
def test_repeated_absence_preserves_review_and_has_no_resolution_delta(
    monkeypatch,
    status,
    scan_path,
):
    state, issue = _state_with_resolution(status)
    options = merge_mod.MergeScanOptions(
        lang="python",
        scan_path=scan_path,
        force_resolve=True,
        potentials={"structural": 1},
    )
    monkeypatch.setattr(merge_mod, "utc_now", lambda: FIRST_SCAN)
    first = merge_mod.merge_scan(state, [], options)
    assert first["auto_resolved"] + first["resolved_out_of_scope"] == 1
    _fresh_review(state)
    expected_assessment = copy.deepcopy(state["subjective_assessments"])
    original_attestation = issue["resolution_attestation"]["text"]

    for timestamp in (NEXT_SCAN, LATER_SCAN):
        monkeypatch.setattr(merge_mod, "utc_now", lambda timestamp=timestamp: timestamp)
        result = merge_mod.merge_scan(state, [], options)
        assert result["auto_resolved"] == 0
        assert result["resolved_out_of_scope"] == 0
        assert state["scan_history"][-1]["diff_resolved"] == 0
        assert state["subjective_assessments"] == expected_assessment
        assert issue["status"] == status
        assert issue["resolution_attestation"]["scan_verified"] is True
        assert issue["resolution_attestation"]["scan_verified_at"] == timestamp
        assert issue["resolution_attestation"]["text"] == original_attestation


@pytest.mark.parametrize("status", ["fixed", "false_positive", "wontfix"])
def test_first_verification_still_marks_affected_assessments_stale(monkeypatch, status):
    state, issue = _state_with_resolution(status)
    state["subjective_assessments"] = {"design_coherence": {"score": 80.0}}
    monkeypatch.setattr(merge_mod, "utc_now", lambda: FIRST_SCAN)

    result = merge_mod.merge_scan(
        state,
        [],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )

    assert result["auto_resolved"] == 1
    assert (
        state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]
        is True
    )
    assert issue["resolution_attestation"]["scan_verified"] is True


def test_new_issue_still_invalidates_after_prior_absence_verification(monkeypatch):
    state, _ = _state_with_resolution("fixed")
    monkeypatch.setattr(merge_mod, "utc_now", lambda: FIRST_SCAN)
    merge_mod.merge_scan(
        state,
        [],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )
    _fresh_review(state)
    # Complete one reconciliation scan so a later genuine change must stale it.
    monkeypatch.setattr(merge_mod, "utc_now", lambda: NEXT_SCAN)
    merge_mod.merge_scan(
        state,
        [],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )
    state["subjective_assessments"]["design_coherence"].pop(
        "needs_review_refresh", None
    )
    new_issue = make_issue(
        "structural",
        "src/other.py",
        "large",
        tier=3,
        confidence="high",
        summary="New synthetic concern",
        detail={"loc": 600},
    )
    monkeypatch.setattr(merge_mod, "utc_now", lambda: LATER_SCAN)

    result = merge_mod.merge_scan(
        state,
        [new_issue],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )

    assert result["new"] == 1
    assert (
        state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]
        is True
    )


def test_wontfix_reappearance_then_absence_is_new_evidence(monkeypatch):
    state, issue = _state_with_resolution("wontfix")
    monkeypatch.setattr(merge_mod, "utc_now", lambda: FIRST_SCAN)
    merge_mod.merge_scan(
        state,
        [],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )
    _fresh_review(state)
    monkeypatch.setattr(merge_mod, "utc_now", lambda: NEXT_SCAN)
    current_issue = copy.deepcopy(issue)
    current_issue["status"] = "open"
    merge_mod.merge_scan(
        state,
        [current_issue],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )
    assert issue["status"] == "wontfix"
    monkeypatch.setattr(merge_mod, "utc_now", lambda: LATER_SCAN)

    result = merge_mod.merge_scan(
        state,
        [],
        merge_mod.MergeScanOptions(force_resolve=True, potentials={"structural": 1}),
    )

    assert result["auto_resolved"] == 1
    assert (
        state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]
        is True
    )
