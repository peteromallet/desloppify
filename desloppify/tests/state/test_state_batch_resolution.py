"""Exact-ID batch resolution preserves policy without repeated full-state work."""

from __future__ import annotations

import copy
from unittest.mock import Mock

import pytest

from desloppify import state as state_mod
from desloppify.app.commands.plan.override import skip as skip_mod
from desloppify.engine._state import resolution


_NOW = "2026-03-01T12:00:00+00:00"
_STATUSES = [
    "open",
    "fixed",
    "wontfix",
    "false_positive",
    "auto_resolved",
    "deferred",
    "triaged_out",
]


def _add(state, name, *, status="open", detector="unused", detail=None):
    issue = state_mod.make_issue(
        detector,
        "src/example.py",
        name,
        tier=2,
        confidence="high",
        summary=name,
        detail=detail or {},
    )
    issue["status"] = status
    state["work_items"][issue["id"]] = issue
    return issue


def test_exact_ids_ignore_patterns_unknowns_duplicates_and_preserve_order():
    state = state_mod.empty_state()
    first = _add(state, "literal*name")
    neighbor = _add(state, "literalXname")
    second = _add(state, "second")
    requested = [second["id"], "unused::*", "missing", first["id"], second["id"]]

    affected = state_mod.resolve_issue_ids(state, iter(requested), "false_positive")

    assert affected == [second["id"], first["id"]]
    assert first["status"] == second["status"] == "false_positive"
    assert neighbor["status"] == "open"


@pytest.mark.parametrize("target", ["fixed", "open"])
def test_batch_respects_existing_status_and_suppression_filters(target):
    state = state_mod.empty_state()
    issues = [_add(state, status, status=status) for status in _STATUSES]
    hidden = _add(state, "hidden", status="wontfix" if target == "open" else "open")
    hidden["suppressed"] = True
    before_hidden = copy.deepcopy(hidden)

    affected = state_mod.resolve_issue_ids(
        state, [issue["id"] for issue in issues] + [hidden["id"]], target
    )

    expected = issues[1:] if target == "open" else issues[:1]
    assert affected == [issue["id"] for issue in expected]
    assert hidden["status"] == before_hidden["status"]
    assert hidden["suppressed"] is True
    assert all(issue["status"] == target for issue in expected)
    if target == "open":
        assert issues[0]["reopen_count"] == 0
        assert all(issue["reopen_count"] == 1 for issue in expected)
    else:
        assert [issue["status"] for issue in issues[1:]] == _STATUSES[1:]


@pytest.mark.parametrize("target", _STATUSES)
def test_batch_matches_canonical_resolution_semantics(monkeypatch, target):
    monkeypatch.setattr(resolution, "utc_now", lambda: _NOW)
    state = state_mod.empty_state()
    state["scan_count"] = 17
    state["subjective_integrity"] = {"target_score": 91.0}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"},
        "logic_clarity": 74,
    }
    prior_status = "wontfix" if target == "open" else "open"
    review = _add(
        state,
        "review",
        detector="review",
        status=prior_status,
        detail={"dimension": "naming_quality"},
    )
    mechanical = _add(
        state, "mechanical", status=prior_status, detail={"nested": {"value": 3}}
    )
    mechanical["note"] = "prior rationale"
    if target == "open":
        mechanical["wontfix_scan_count"] = 1
        mechanical["wontfix_snapshot"] = {"scan_count": 1}
    original = _add(state, "original", status="wontfix", detail={"loc": 240})
    original["wontfix_scan_count"] = 1
    original["wontfix_snapshot"] = {"scan_count": 1, "detail": {"loc": 180}}
    stale = _add(
        state,
        "stale",
        detector="stale_wontfix",
        status=prior_status,
        detail={"original_issue_id": original["id"]},
    )
    ids = [review["id"], mechanical["id"], stale["id"]]
    canonical = copy.deepcopy(state)
    expected_ids = []
    for issue_id in ids:
        expected_ids.extend(
            state_mod.resolve_issues(
                canonical, issue_id, target, note=None, attestation="reviewed evidence"
            )
        )

    affected = state_mod.resolve_issue_ids(
        state, ids, target, note=None, attestation="reviewed evidence"
    )

    assert affected == expected_ids
    assert state == canonical
    assessment = state["subjective_assessments"]["naming_quality"]
    assert assessment["score"] == 82
    assert assessment["refresh_reason"] == f"review_issue_{target}"
    assert assessment["stale_since"] == _NOW
    if target == "fixed":
        assert original["wontfix_scan_count"] == 17
        assert original["wontfix_snapshot"]["detail"] == {"loc": 240}
    if target == "wontfix":
        mechanical["detail"]["nested"]["value"] = 99
        assert mechanical["wontfix_snapshot"]["detail"]["nested"]["value"] == 3
    if target == "open":
        assert mechanical["note"] == "prior rationale"
        assert mechanical["resolved_at"] is None
        assert "wontfix_snapshot" not in mechanical
        assert mechanical["resolution_attestation"]["previous_status"] == "wontfix"


def test_batch_reopen_duplicates_increment_once():
    state = state_mod.empty_state()
    issue = _add(state, "closed", status="wontfix")

    assert state_mod.resolve_issue_ids(state, [issue["id"]] * 3, "open") == [
        issue["id"]
    ]
    assert issue["reopen_count"] == 1


def test_batch_validates_state_invariants():
    state = state_mod.empty_state()
    issue = _add(state, "invalid-tier")
    issue["tier"] = 0

    with pytest.raises(ValueError, match="invalid tier"):
        state_mod.resolve_issue_ids(state, [issue["id"]], "false_positive")


def test_large_batch_normalizes_recomputes_and_validates_once(monkeypatch):
    state = state_mod.empty_state()
    ids = [_add(state, str(index))["id"] for index in range(500)]
    normalize = Mock(wraps=resolution.ensure_state_defaults)
    recompute = Mock(wraps=resolution._recompute_stats)
    validate = Mock(wraps=resolution.validate_state_invariants)
    monkeypatch.setattr(resolution, "ensure_state_defaults", normalize)
    monkeypatch.setattr(resolution, "_recompute_stats", recompute)
    monkeypatch.setattr(resolution, "validate_state_invariants", validate)
    monkeypatch.setattr(
        resolution,
        "match_issues",
        Mock(
            side_effect=AssertionError(
                "exact-ID batches must not rescan the inventory as patterns"
            )
        ),
    )

    assert state_mod.resolve_issue_ids(state, ids, "false_positive") == ids
    normalize.assert_called_once_with(state)
    recompute.assert_called_once()
    validate.assert_called_once_with(state)


@pytest.mark.parametrize(
    "kind,status", [("permanent", "wontfix"), ("false_positive", "false_positive")]
)
def test_skip_resolves_selected_ids_as_one_canonical_batch(monkeypatch, kind, status):
    state = state_mod.empty_state()
    ids = [_add(state, str(index))["id"] for index in range(25)]
    neighbor = _add(state, "unselected")
    recompute = Mock(wraps=resolution._recompute_stats)
    monkeypatch.setattr(resolution, "_recompute_stats", recompute)
    monkeypatch.setattr(skip_mod.state_mod, "load_state", lambda _path: state)
    monkeypatch.setattr(
        skip_mod.state_mod,
        "resolve_issues",
        Mock(side_effect=AssertionError("skip must not resolve IDs individually")),
    )

    result = skip_mod._apply_state_skip_resolution(
        kind=kind,
        state_file=None,
        issue_ids=ids,
        note="reviewed code",
        attestation="I have actually reviewed this and I am not gaming the score.",
    )

    assert result is state
    assert neighbor["status"] == "open"
    assert all(state["work_items"][issue_id]["status"] == status for issue_id in ids)
    assert all(
        state["work_items"][issue_id]["note"] == "reviewed code" for issue_id in ids
    )
    assert all(
        state["work_items"][issue_id]["resolution_attestation"]["text"].startswith(
            "I have actually reviewed"
        )
        for issue_id in ids
    )
    recompute.assert_called_once()


def test_pattern_resolution_normalizes_legacy_state_before_matching():
    issue_id = "unused::src/legacy.py::legacy"
    state = {
        "issues": {
            issue_id: {
                "detector": "unused",
                "file": "src/legacy.py",
                "status": "resolved",
                "note": "prior rationale",
            }
        }
    }

    affected = state_mod.resolve_issues(state, "unused", "open")

    assert affected == [issue_id]
    assert state["issues"] is state["work_items"]
    issue = state["work_items"][issue_id]
    assert issue["id"] == issue_id
    assert issue["status"] == "open"
    assert issue["note"] == "prior rationale"
    assert issue["reopen_count"] == 1
    assert issue["resolution_attestation"]["previous_status"] == "fixed"
    state_mod.validate_state_invariants(state)
