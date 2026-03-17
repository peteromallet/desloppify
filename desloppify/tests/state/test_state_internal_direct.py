"""Direct tests for _state modules flagged as transitive-only."""

from __future__ import annotations

import json

import desloppify.engine._state.filtering as filtering_mod
import desloppify.engine._state.issue_semantics as issue_semantics_mod
import desloppify.engine._state.noise as noise_mod
import desloppify.engine._state.persistence as persistence_mod
import desloppify.engine._state.resolution as resolution_mod
import desloppify.engine._state.schema as schema_mod


def test_noise_budget_resolution_and_capping():
    per_budget, global_budget, warning = noise_mod.resolve_issue_noise_settings(
        {
            "issue_noise_budget": "bad",
            "issue_noise_global_budget": -5,
        }
    )

    assert per_budget == noise_mod.DEFAULT_ISSUE_NOISE_BUDGET
    assert global_budget == 0
    assert warning is not None
    assert "issue_noise_budget" in warning
    assert "issue_noise_global_budget" in warning

    issues = [
        {
            "id": "a1",
            "detector": "smells",
            "tier": 2,
            "confidence": "high",
            "file": "a.py",
        },
        {
            "id": "a2",
            "detector": "smells",
            "tier": 3,
            "confidence": "low",
            "file": "a.py",
        },
        {
            "id": "b1",
            "detector": "structural",
            "tier": 3,
            "confidence": "medium",
            "file": "b.py",
        },
    ]
    surfaced, hidden = noise_mod.apply_issue_noise_budget(
        issues, budget=1, global_budget=1
    )
    assert len(surfaced) == 1
    assert surfaced[0]["id"] in {"a1", "b1"}
    assert hidden["smells"] >= 1


def test_load_state_missing_and_backup_fallback(tmp_path):
    missing = tmp_path / "missing-state.json"
    loaded = persistence_mod.load_state(missing)
    assert isinstance(loaded, dict)
    assert loaded["version"] == schema_mod.CURRENT_VERSION
    assert loaded["issues"] == {}

    primary = tmp_path / "state.json"
    backup = tmp_path / "state.json.bak"
    primary.write_text("{not-json")
    backup.write_text(json.dumps(schema_mod.empty_state()))

    recovered = persistence_mod.load_state(primary)
    assert recovered["version"] == schema_mod.CURRENT_VERSION
    assert recovered["issues"] == {}
    assert recovered["strict_score"] == 0


def test_issue_semantics_normalize_legacy_detector_rows():
    review_issue = {"id": "review::src/a.py::naming", "detector": "review", "detail": {}}
    concern_issue = {"id": "concerns::src/a.py::dup", "detector": "concerns", "detail": {}}
    request_issue = {
        "id": "subjective_review::.::holistic_unreviewed",
        "detector": "subjective_review",
        "detail": {},
    }
    mechanical_issue = {"id": "unused::src/a.py::x", "detector": "unused", "detail": {}}

    issue_semantics_mod.ensure_work_item_semantics(review_issue)
    issue_semantics_mod.ensure_work_item_semantics(concern_issue)
    issue_semantics_mod.ensure_work_item_semantics(request_issue)
    issue_semantics_mod.ensure_work_item_semantics(mechanical_issue)

    assert review_issue["work_item_kind"] == issue_semantics_mod.REVIEW_DEFECT
    assert review_issue["issue_kind"] == issue_semantics_mod.REVIEW_DEFECT
    assert review_issue["origin"] == issue_semantics_mod.REVIEW_IMPORT_ORIGIN
    assert concern_issue["work_item_kind"] == issue_semantics_mod.REVIEW_CONCERN
    assert concern_issue["issue_kind"] == issue_semantics_mod.REVIEW_CONCERN
    assert request_issue["work_item_kind"] == issue_semantics_mod.ASSESSMENT_REQUEST
    assert request_issue["issue_kind"] == issue_semantics_mod.ASSESSMENT_REQUEST
    assert request_issue["origin"] == issue_semantics_mod.SYNTHETIC_TASK_ORIGIN
    assert mechanical_issue["work_item_kind"] == issue_semantics_mod.MECHANICAL_DEFECT
    assert mechanical_issue["issue_kind"] == issue_semantics_mod.MECHANICAL_DEFECT
    assert mechanical_issue["origin"] == issue_semantics_mod.SCAN_ORIGIN


def test_validate_state_invariants_rejects_invalid_issue_semantics():
    state = schema_mod.empty_state()
    state["work_items"] = {
        "bad": {
            "id": "bad",
            "detector": "unused",
            "file": "src/a.py",
            "tier": 2,
            "confidence": "high",
            "summary": "bad",
            "detail": {},
            "status": "open",
            "note": None,
            "first_seen": "2025-01-01T00:00:00+00:00",
            "last_seen": "2025-01-01T00:00:00+00:00",
            "resolved_at": None,
            "reopen_count": 0,
            "issue_kind": "not_real",
            "origin": issue_semantics_mod.SCAN_ORIGIN,
        }
    }

    try:
        schema_mod.validate_state_invariants(state)
    except ValueError as exc:
        assert "work_item_kind" in str(exc)
    else:
        raise AssertionError("validate_state_invariants should reject invalid issue_kind")


def test_state_persistence_defaults_follow_runtime_project_root(tmp_path):
    from desloppify.base.runtime_state import RuntimeContext, runtime_scope

    state = schema_mod.empty_state()
    ctx = RuntimeContext(project_root=tmp_path)
    with runtime_scope(ctx):
        persistence_mod.save_state(state)
        loaded = persistence_mod.load_state()

    expected = tmp_path / ".desloppify" / "state.json"
    assert expected.exists()
    assert loaded["version"] == schema_mod.CURRENT_VERSION
    assert loaded["issues"] == {}


def test_state_persistence_honors_monkeypatched_state_file(monkeypatch, tmp_path):
    custom_state_file = tmp_path / "custom" / "state.json"
    monkeypatch.setattr(persistence_mod, "STATE_FILE", custom_state_file)

    state = schema_mod.empty_state()
    persistence_mod.save_state(state)
    loaded = persistence_mod.load_state()

    assert custom_state_file.exists()
    assert loaded["version"] == schema_mod.CURRENT_VERSION
    assert loaded["issues"] == {}


def test_state_persistence_serializes_dataclass_values_in_review_cache(tmp_path):
    from desloppify.languages._framework.frameworks.types import EcosystemFrameworkDetection

    state_path = tmp_path / "state.json"
    state = schema_mod.empty_state()
    state["review_cache"] = {
        "holistic": {
            "ecosystems": {
                "framework_detections": [
                    EcosystemFrameworkDetection(
                        ecosystem="node",
                        package_root=tmp_path,
                        package_json_relpath=None,
                        present={"nextjs": {"deps": ["next"]}},
                    )
                ]
            }
        }
    }

    persistence_mod.save_state(state, state_path)

    loaded = persistence_mod.load_state(state_path)
    detections = (
        loaded.get("review_cache", {})
        .get("holistic", {})
        .get("ecosystems", {})
        .get("framework_detections", [])
    )
    assert isinstance(detections, list)
    assert detections
    assert isinstance(detections[0], dict)
    assert detections[0]["ecosystem"] == "node"


def test_match_and_resolve_issues_updates_state():
    state = schema_mod.empty_state()
    open_issue = filtering_mod.make_issue(
        "unused",
        "pkg/a.py",
        "name",
        tier=2,
        confidence="high",
        summary="unused name",
    )
    hidden_issue = filtering_mod.make_issue(
        "unused",
        "pkg/b.py",
        "name",
        tier=2,
        confidence="high",
        summary="unused name",
    )
    hidden_issue["suppressed"] = True

    state["work_items"] = {
        open_issue["id"]: open_issue,
        hidden_issue["id"]: hidden_issue,
    }

    matches = resolution_mod.match_issues(state, "unused", status_filter="open")
    assert len(matches) == 1
    assert matches[0]["id"] == open_issue["id"]

    resolved_ids = resolution_mod.resolve_issues(
        state,
        "unused",
        status="fixed",
        note="done",
        attestation="I fixed this",
    )

    assert resolved_ids == [open_issue["id"]]
    resolved = state["work_items"][open_issue["id"]]
    assert resolved["status"] == "fixed"
    assert resolved["note"] == "done"
    assert resolved["resolved_at"] is not None
    assert resolved["resolution_attestation"]["text"] == "I fixed this"
    assert resolved["resolution_attestation"]["scan_verified"] is False


def test_open_scope_breakdown_splits_in_scope_and_out_of_scope():
    issues = {
        "smells::src/a.py::x": {
            "status": "open",
            "detector": "smells",
            "file": "src/a.py",
        },
        "smells::scripts/b.py::x": {
            "status": "open",
            "detector": "smells",
            "file": "scripts/b.py",
        },
        "subjective_review::.::holistic_unreviewed": {
            "status": "open",
            "detector": "subjective_review",
            "file": ".",
        },
        "smells::src/c.py::closed": {
            "status": "fixed",
            "detector": "smells",
            "file": "src/c.py",
        },
    }

    counts = filtering_mod.open_scope_breakdown(issues, "src")
    assert counts == {"in_scope": 2, "out_of_scope": 1, "global": 3}

    subjective_counts = filtering_mod.open_scope_breakdown(
        issues,
        "src",
        detector="subjective_review",
    )
    assert subjective_counts == {"in_scope": 1, "out_of_scope": 0, "global": 1}


def test_resolve_fixed_review_marks_assessment_stale_preserves_score():
    """Resolving a review issue as fixed marks assessment stale but keeps score."""
    state = schema_mod.empty_state()
    review_issue = filtering_mod.make_issue(
        "review",
        "pkg/a.py",
        "naming",
        tier=3,
        confidence="high",
        summary="naming issue",
        detail={"dimension": "naming_quality"},
    )
    state["work_items"] = {review_issue["id"]: review_issue}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"},
        "logic_clarity": {"score": 74, "source": "holistic"},
    }

    resolution_mod.resolve_issues(
        state,
        "review::",
        status="fixed",
        note="renamed symbols",
        attestation="I have actually fixed this and I am not gaming the score.",
    )

    naming = state["subjective_assessments"]["naming_quality"]
    logic = state["subjective_assessments"]["logic_clarity"]
    # Score preserved (not zeroed) — only a fresh review changes scores.
    assert naming["score"] == 82
    assert naming["needs_review_refresh"] is True
    assert naming["refresh_reason"] == "review_issue_fixed"
    assert naming["stale_since"] is not None
    # Untouched dimension is unchanged.
    assert logic["score"] == 74
    assert "needs_review_refresh" not in logic


def test_resolve_wontfix_review_marks_assessment_stale():
    """Resolving a review issue as wontfix also marks assessment stale."""
    state = schema_mod.empty_state()
    review_issue = filtering_mod.make_issue(
        "review",
        "pkg/a.py",
        "naming",
        tier=3,
        confidence="high",
        summary="naming issue",
        detail={"dimension": "naming_quality"},
    )
    state["work_items"] = {review_issue["id"]: review_issue}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"}
    }

    resolution_mod.resolve_issues(
        state,
        "review::",
        status="wontfix",
        note="intentional",
        attestation="I have actually reviewed this and I am not gaming the score.",
    )

    naming = state["subjective_assessments"]["naming_quality"]
    assert naming["score"] == 82
    assert naming["needs_review_refresh"] is True
    assert naming["refresh_reason"] == "review_issue_wontfix"
    assert naming["stale_since"] is not None


def test_resolve_false_positive_review_marks_assessment_stale():
    """Resolving a review issue as false_positive also marks assessment stale."""
    state = schema_mod.empty_state()
    review_issue = filtering_mod.make_issue(
        "review",
        "pkg/a.py",
        "naming",
        tier=3,
        confidence="high",
        summary="naming issue",
        detail={"dimension": "naming_quality"},
    )
    state["work_items"] = {review_issue["id"]: review_issue}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"}
    }

    resolution_mod.resolve_issues(
        state,
        "review::",
        status="false_positive",
        note="not a real issue",
        attestation="This is not an actual defect.",
    )

    naming = state["subjective_assessments"]["naming_quality"]
    assert naming["score"] == 82
    assert naming["needs_review_refresh"] is True
    assert naming["refresh_reason"] == "review_issue_false_positive"


def test_resolve_non_review_issue_does_not_mark_stale():
    """Resolving a non-review issue does not touch subjective assessments."""
    state = schema_mod.empty_state()
    issue = filtering_mod.make_issue(
        "unused",
        "pkg/a.py",
        "name",
        tier=2,
        confidence="high",
        summary="unused name",
    )
    state["work_items"] = {issue["id"]: issue}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"}
    }

    resolution_mod.resolve_issues(
        state,
        "unused",
        status="fixed",
        note="done",
        attestation="Fixed it.",
    )

    naming = state["subjective_assessments"]["naming_quality"]
    assert naming["score"] == 82
    assert "needs_review_refresh" not in naming


def test_resolve_wontfix_captures_snapshot_metadata():
    state = schema_mod.empty_state()
    state["scan_count"] = 17
    issue = filtering_mod.make_issue(
        "structural",
        "pkg/a.py",
        "",
        tier=3,
        confidence="medium",
        summary="large module",
        detail={"loc": 210, "complexity_score": 42},
    )
    state["work_items"] = {issue["id"]: issue}

    resolution_mod.resolve_issues(
        state,
        "structural::",
        status="wontfix",
        note="intentional for now",
        attestation="I have actually reviewed this and I am not gaming the score.",
    )

    resolved = state["work_items"][issue["id"]]
    assert resolved["status"] == "wontfix"
    assert resolved["wontfix_scan_count"] == 17
    assert resolved["wontfix_snapshot"]["scan_count"] == 17
    assert resolved["wontfix_snapshot"]["detail"]["loc"] == 210
    assert resolved["wontfix_snapshot"]["detail"]["complexity_score"] == 42


def test_resolve_stale_wontfix_refreshes_original_wontfix_snapshot():
    state = schema_mod.empty_state()
    state["scan_count"] = 24
    original = filtering_mod.make_issue(
        "smells",
        "pkg/a.py",
        "monster_function",
        tier=3,
        confidence="medium",
        summary="large function",
        detail={"loc": 240, "complexity_score": 51},
    )
    original["status"] = "wontfix"
    original["wontfix_scan_count"] = 1
    original["wontfix_snapshot"] = {
        "scan_count": 1,
        "detail": {"loc": 180, "complexity_score": 40},
    }
    stale = filtering_mod.make_issue(
        "stale_wontfix",
        "pkg/a.py",
        original["id"],
        tier=3,
        confidence="medium",
        summary="stale wontfix",
        detail={"original_issue_id": original["id"], "reasons": ["scan_decay"]},
    )
    state["work_items"] = {
        original["id"]: original,
        stale["id"]: stale,
    }

    resolution_mod.resolve_issues(
        state,
        stale["id"],
        status="fixed",
        note="re-reviewed",
        attestation="I have actually re-reviewed this wontfix and I am not gaming the score.",
    )

    refreshed = state["work_items"][original["id"]]
    assert refreshed["status"] == "wontfix"
    assert refreshed["wontfix_scan_count"] == 24
    assert refreshed["wontfix_snapshot"]["scan_count"] == 24
    assert refreshed["wontfix_snapshot"]["detail"]["loc"] == 240
    assert refreshed["wontfix_snapshot"]["detail"]["complexity_score"] == 51


def test_resolve_open_reopens_non_open_issue_and_increments_reopen_count():
    state = schema_mod.empty_state()
    issue = filtering_mod.make_issue(
        "review",
        "pkg/a.py",
        "naming",
        tier=3,
        confidence="high",
        summary="naming issue",
        detail={"dimension": "naming_quality"},
    )
    issue["status"] = "fixed"
    issue["resolved_at"] = "2026-01-01T10:00:00+00:00"
    issue["note"] = "fixed earlier"
    issue["reopen_count"] = 2
    state["work_items"] = {issue["id"]: issue}

    resolved_ids = resolution_mod.resolve_issues(
        state,
        "review::",
        status="open",
        note="needs deeper fix",
        attestation=None,
    )

    assert resolved_ids == [issue["id"]]
    reopened = state["work_items"][issue["id"]]
    assert reopened["status"] == "open"
    assert reopened["resolved_at"] is None
    assert reopened["note"] == "needs deeper fix"
    assert reopened["reopen_count"] == 3
    attestation = reopened.get("resolution_attestation") or {}
    assert attestation.get("kind") == "manual_reopen"
    assert attestation.get("previous_status") == "fixed"
