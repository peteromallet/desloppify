"""Direct tests for state_internal.scoring helpers."""

from __future__ import annotations

import desloppify.engine.state_internal.scoring as scoring_mod


def test_count_findings_tracks_status_and_tiers():
    findings = {
        "f1": {"status": "open", "tier": 2},
        "f2": {"status": "fixed", "tier": 2},
        "f3": {"status": "auto_resolved", "tier": 3},
    }

    counters, by_tier = scoring_mod._count_findings(findings)
    assert counters["open"] == 1
    assert counters["fixed"] == 1
    assert counters["auto_resolved"] == 1
    assert by_tier[2]["open"] == 1
    assert by_tier[2]["fixed"] == 1
    assert by_tier[3]["auto_resolved"] == 1


def test_update_objective_health_verified_strict_penalizes_manual_fixed():
    from desloppify.intelligence.review.dimensions.file import DEFAULT_DIMENSIONS

    state = {
        "potentials": {"python": {"unused": 10}},
        "subjective_assessments": {dim: {"score": 100} for dim in DEFAULT_DIMENSIONS},
    }
    findings = {
        "f1": {
            "detector": "unused",
            "status": "fixed",
            "confidence": "high",
            "file": "a.py",
            "zone": "production",
            "tier": 2,
        }
    }

    scoring_mod._update_objective_health(state, findings)
    assert state["strict_score"] == 100.0
    assert state["verified_strict_score"] < state["strict_score"]


def test_suppression_metrics_aggregates_recent_history():
    state = {
        "scan_history": [
            {"ignored": 2, "raw_findings": 10, "ignore_patterns": 1},
            {
                "ignored": 1,
                "raw_findings": 5,
                "ignore_patterns": 1,
                "suppressed_pct": 20.0,
            },
        ]
    }

    metrics = scoring_mod.suppression_metrics(state, window=2)
    assert metrics["last_ignored"] == 1
    assert metrics["last_raw_findings"] == 5
    assert metrics["last_suppressed_pct"] == 20.0
    assert metrics["recent_ignored"] == 3
    assert metrics["recent_raw_findings"] == 15
    assert metrics["recent_suppressed_pct"] == 20.0


def test_update_objective_health_resets_two_target_matched_subjective_dimensions():
    state = {
        "potentials": {"python": {"unused": 0}},
        "subjective_assessments": {
            "naming_quality": {"score": 95},
            "logic_clarity": {"score": 95},
            "ai_generated_debt": {"score": 90},
        },
    }

    scoring_mod._update_objective_health(
        state,
        findings={},
        subjective_integrity_target=95.0,
    )

    dim_scores = state["dimension_scores"]
    assert dim_scores["Naming Quality"]["score"] == 0.0
    assert dim_scores["Logic Clarity"]["score"] == 0.0
    assert dim_scores["AI Generated Debt"]["score"] == 100.0
    assert (
        dim_scores["AI Generated Debt"]["detectors"]["subjective_assessment"][
            "assessment_score"
        ]
        == 90.0
    )
    assert state["subjective_integrity"]["status"] == "penalized"
    assert state["subjective_integrity"]["matched_count"] == 2
    assert state["subjective_integrity"]["reset_dimensions"] == [
        "logic_clarity",
        "naming_quality",
    ]


def test_update_objective_health_warns_single_target_matched_subjective_dimension():
    state = {
        "potentials": {"python": {"unused": 0}},
        "subjective_assessments": {
            "naming_quality": {"score": 95},
            "logic_clarity": {"score": 93},
        },
    }

    scoring_mod._update_objective_health(
        state,
        findings={},
        subjective_integrity_target=95.0,
    )

    dim_scores = state["dimension_scores"]
    assert dim_scores["Naming Quality"]["score"] == 100.0
    assert (
        dim_scores["Naming Quality"]["detectors"]["subjective_assessment"][
            "assessment_score"
        ]
        == 95.0
    )
    assert state["subjective_integrity"]["status"] == "warn"
    assert state["subjective_integrity"]["matched_count"] == 1
    assert state["subjective_integrity"]["reset_dimensions"] == []
