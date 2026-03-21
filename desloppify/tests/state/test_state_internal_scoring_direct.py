"""Direct tests for state-integration scoring helpers."""

from __future__ import annotations

import desloppify.engine._scoring.state_integration as scoring_mod
from desloppify.engine._state.scoring import suppression_metrics


def test_count_issues_tracks_status_and_tiers():
    issues = {
        "f1": {"status": "open", "tier": 2},
        "f2": {"status": "fixed", "tier": 2},
        "f3": {"status": "auto_resolved", "tier": 3},
    }

    counters, by_tier = scoring_mod._count_issues(issues)
    assert counters["open"] == 1
    assert counters["fixed"] == 1
    assert counters["auto_resolved"] == 1
    assert by_tier[2]["open"] == 1
    assert by_tier[2]["fixed"] == 1
    assert by_tier[3]["auto_resolved"] == 1


def test_update_objective_health_verified_strict_penalizes_manual_fixed():
    from desloppify.intelligence.review.dimensions.holistic import DIMENSIONS

    state = {
        "potentials": {"python": {"unused": 10}},
        "subjective_assessments": {dim: {"score": 100} for dim in DIMENSIONS},
    }
    issues = {
        "f1": {
            "detector": "unused",
            "status": "fixed",
            "confidence": "high",
            "file": "a.py",
            "zone": "production",
            "tier": 2,
        }
    }

    scoring_mod._update_objective_health(state, issues)
    assert state["strict_score"] == 100.0
    assert state["verified_strict_score"] < state["strict_score"]


def test_suppression_metrics_aggregates_recent_history():
    state = {
        "scan_history": [
            {"ignored": 2, "raw_issues": 10, "ignore_patterns": 1},
            {
                "ignored": 1,
                "raw_issues": 5,
                "ignore_patterns": 1,
                "suppressed_pct": 20.0,
            },
        ]
    }

    metrics = suppression_metrics(state, window=2)
    assert metrics["last_ignored"] == 1
    assert metrics["last_raw_issues"] == 5
    assert metrics["last_suppressed_pct"] == 20.0
    assert metrics["recent_ignored"] == 3
    assert metrics["recent_raw_issues"] == 15
    assert metrics["recent_suppressed_pct"] == 20.0


def test_update_objective_health_preserves_two_target_matched_subjective_dimensions():
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
        issues={},
        subjective_integrity_target=95.0,
    )

    dim_scores = state["dimension_scores"]
    # Scores are preserved — integrity policy is disabled
    assert dim_scores["Naming quality"]["score"] == 95.0
    assert dim_scores["Logic clarity"]["score"] == 95.0
    assert dim_scores["AI generated debt"]["score"] == 90.0
    assert (
        dim_scores["AI generated debt"]["detectors"]["subjective_assessment"][
            "assessment_score"
        ]
        == 90.0
    )
    assert state["subjective_integrity"]["status"] == "disabled"
    assert state["subjective_integrity"]["matched_count"] == 0
    assert state["subjective_integrity"]["reset_dimensions"] == []


def test_update_objective_health_disabled_single_target_matched_subjective_dimension():
    state = {
        "potentials": {"python": {"unused": 0}},
        "subjective_assessments": {
            "naming_quality": {"score": 95},
            "logic_clarity": {"score": 93},
        },
    }

    scoring_mod._update_objective_health(
        state,
        issues={},
        subjective_integrity_target=95.0,
    )

    dim_scores = state["dimension_scores"]
    assert dim_scores["Naming quality"]["score"] == 95.0
    assert (
        dim_scores["Naming quality"]["detectors"]["subjective_assessment"][
            "assessment_score"
        ]
        == 95.0
    )
    # Integrity policy is disabled — no warn/penalize status
    assert state["subjective_integrity"]["status"] == "disabled"
    assert state["subjective_integrity"]["matched_count"] == 0
    assert state["subjective_integrity"]["reset_dimensions"] == []


def test_update_objective_health_applies_scan_coverage_confidence_metadata():
    state = {
        "lang": "python",
        "potentials": {"python": {"security": 10}},
        "scan_coverage": {
            "python": {
                "detectors": {
                    "security": {
                        "status": "reduced",
                        "confidence": 0.6,
                        "summary": "bandit missing",
                        "impact": "Python-specific security checks skipped.",
                        "remediation": "Install Bandit: pip install bandit",
                    }
                }
            }
        },
    }

    scoring_mod._update_objective_health(state, issues={})

    security_dim = state["dimension_scores"]["Security"]
    detector_meta = security_dim["detectors"]["security"]
    assert detector_meta["coverage_status"] == "reduced"
    assert detector_meta["coverage_confidence"] == 0.6
    assert security_dim["coverage_status"] == "reduced"
    assert security_dim["coverage_confidence"] == 0.6
    assert state["score_confidence"]["status"] == "reduced"
    assert "Security" in state["score_confidence"]["dimensions"]
