"""Direct tests for state_internal modules flagged as transitive-only."""

from __future__ import annotations

import json

import desloppify.engine.state_internal.filtering as filtering_mod
import desloppify.engine.state_internal.noise as noise_mod
import desloppify.engine.state_internal.persistence as persistence_mod
import desloppify.engine.state_internal.resolution as resolution_mod
import desloppify.engine.state_internal.schema as schema_mod


def test_noise_budget_resolution_and_capping():
    per_budget, global_budget, warning = noise_mod.resolve_finding_noise_settings(
        {
            "finding_noise_budget": "bad",
            "finding_noise_global_budget": -5,
        }
    )

    assert per_budget == noise_mod.DEFAULT_FINDING_NOISE_BUDGET
    assert global_budget == 0
    assert warning is not None
    assert "finding_noise_budget" in warning
    assert "finding_noise_global_budget" in warning

    findings = [
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
    surfaced, hidden = noise_mod.apply_finding_noise_budget(
        findings, budget=1, global_budget=1
    )
    assert len(surfaced) == 1
    assert surfaced[0]["id"] in {"a1", "b1"}
    assert hidden["smells"] >= 1


def test_load_state_missing_and_backup_fallback(tmp_path):
    missing = tmp_path / "missing-state.json"
    loaded = persistence_mod.load_state(missing)
    assert isinstance(loaded, dict)
    assert loaded["version"] == schema_mod.CURRENT_VERSION
    assert loaded["findings"] == {}

    primary = tmp_path / "state.json"
    backup = tmp_path / "state.json.bak"
    primary.write_text("{not-json")
    backup.write_text(json.dumps(schema_mod.empty_state()))

    recovered = persistence_mod.load_state(primary)
    assert recovered["version"] == schema_mod.CURRENT_VERSION
    assert recovered["findings"] == {}
    assert recovered["strict_score"] == 0


def test_match_and_resolve_findings_updates_state():
    state = schema_mod.empty_state()
    open_finding = filtering_mod.make_finding(
        "unused",
        "pkg/a.py",
        "name",
        tier=2,
        confidence="high",
        summary="unused name",
    )
    hidden_finding = filtering_mod.make_finding(
        "unused",
        "pkg/b.py",
        "name",
        tier=2,
        confidence="high",
        summary="unused name",
    )
    hidden_finding["suppressed"] = True

    state["findings"] = {
        open_finding["id"]: open_finding,
        hidden_finding["id"]: hidden_finding,
    }

    matches = resolution_mod.match_findings(state, "unused", status_filter="open")
    assert len(matches) == 1
    assert matches[0]["id"] == open_finding["id"]

    resolved_ids = resolution_mod.resolve_findings(
        state,
        "unused",
        status="fixed",
        note="done",
        attestation="I fixed this",
    )

    assert resolved_ids == [open_finding["id"]]
    resolved = state["findings"][open_finding["id"]]
    assert resolved["status"] == "fixed"
    assert resolved["note"] == "done"
    assert resolved["resolved_at"] is not None
    assert resolved["resolution_attestation"]["text"] == "I fixed this"
    assert resolved["resolution_attestation"]["scan_verified"] is False


def test_resolve_fixed_review_resets_related_subjective_assessment():
    state = schema_mod.empty_state()
    review_finding = filtering_mod.make_finding(
        "review",
        "pkg/a.py",
        "naming",
        tier=3,
        confidence="high",
        summary="naming issue",
        detail={"dimension": "naming_quality"},
    )
    state["findings"] = {review_finding["id"]: review_finding}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"},
        "logic_clarity": {"score": 74, "source": "holistic"},
    }

    resolution_mod.resolve_findings(
        state,
        "review::",
        status="fixed",
        note="renamed symbols",
        attestation="I have actually fixed this and I am not gaming the score.",
    )

    naming = state["subjective_assessments"]["naming_quality"]
    logic = state["subjective_assessments"]["logic_clarity"]
    assert naming["score"] == 0.0
    assert naming["needs_review_refresh"] is True
    assert naming["refresh_reason"] == "review_finding_resolved"
    assert naming["assessed_at"] is not None
    assert logic["score"] == 74


def test_resolve_non_fixed_review_does_not_reset_subjective_assessment():
    state = schema_mod.empty_state()
    review_finding = filtering_mod.make_finding(
        "review",
        "pkg/a.py",
        "naming",
        tier=3,
        confidence="high",
        summary="naming issue",
        detail={"dimension": "naming_quality"},
    )
    state["findings"] = {review_finding["id"]: review_finding}
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82, "source": "holistic"}
    }

    resolution_mod.resolve_findings(
        state,
        "review::",
        status="wontfix",
        note="intentional",
        attestation="I have actually reviewed this and I am not gaming the score.",
    )

    naming = state["subjective_assessments"]["naming_quality"]
    assert naming["score"] == 82
    assert "needs_review_refresh" not in naming


def test_resolve_wontfix_captures_snapshot_metadata():
    state = schema_mod.empty_state()
    state["scan_count"] = 17
    finding = filtering_mod.make_finding(
        "structural",
        "pkg/a.py",
        "",
        tier=3,
        confidence="medium",
        summary="large module",
        detail={"loc": 210, "complexity_score": 42},
    )
    state["findings"] = {finding["id"]: finding}

    resolution_mod.resolve_findings(
        state,
        "structural::",
        status="wontfix",
        note="intentional for now",
        attestation="I have actually reviewed this and I am not gaming the score.",
    )

    resolved = state["findings"][finding["id"]]
    assert resolved["status"] == "wontfix"
    assert resolved["wontfix_scan_count"] == 17
    assert resolved["wontfix_snapshot"]["scan_count"] == 17
    assert resolved["wontfix_snapshot"]["detail"]["loc"] == 210
    assert resolved["wontfix_snapshot"]["detail"]["complexity_score"] == 42
