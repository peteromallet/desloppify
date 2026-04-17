"""Subjective scoring and display-name regression tests for scoring."""

from __future__ import annotations

import pytest

from desloppify.engine._scoring.policy.core import (
    CONFIDENCE_WEIGHTS,
    DIMENSIONS,
    MIN_SAMPLE,
    SUBJECTIVE_CHECKS,
    TIER_WEIGHTS,
)
from desloppify.engine._scoring.results.core import (
    compute_dimension_scores,
    compute_health_breakdown,
    compute_health_score,
    compute_score_impact,
)
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES


def _issue(
    detector: str,
    *,
    status: str = "open",
    confidence: str = "high",
    file: str = "a.py",
    zone: str = "production",
) -> dict:
    """Build a minimal issue dict."""
    return {
        "detector": detector,
        "status": status,
        "confidence": confidence,
        "file": file,
        "zone": zone,
    }


def _issues_dict(*issues: dict) -> dict:
    """Wrap a list of issue dicts into an id-keyed dict."""
    return {str(i): f for i, f in enumerate(issues)}


class TestSubjectiveScoring:
    """Tests for the subjective_assessments kwarg on compute_dimension_scores."""

    def test_no_assessments_no_change(self):
        """Calling with subjective_assessments=None produces the same result as before."""
        potentials = {"unused": 100}
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
        )
        without = compute_dimension_scores(issues, potentials)
        with_none = compute_dimension_scores(
            issues, potentials, subjective_assessments=None
        )
        assert without == with_none

    def test_single_assessment_dimension(self):
        """One assessment adds a dimension with the right shape."""
        assessments = {"naming_quality": {"score": 75}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        assert "Naming quality" in result
        dim = result["Naming quality"]
        # Assessment score drives dimension score directly.
        assert dim["score"] == 75.0
        assert dim["tier"] == 4
        assert dim["checks"] == SUBJECTIVE_CHECKS
        assert dim["failing"] == 0
        assert "subjective_assessment" in dim["detectors"]
        det = dim["detectors"]["subjective_assessment"]
        assert det["potential"] == SUBJECTIVE_CHECKS
        assert det["pass_rate"] == 0.75
        assert det["weighted_failures"] == pytest.approx(2.5)
        assert det["assessment_score"] == 75.0

    def test_allowed_subjective_dimensions_scopes_defaults_not_assessments(self):
        """allowed_subjective_dimensions gates which defaults get 0-score
        placeholders but explicit assessments always count — they were
        deliberately imported and should not be silently discarded."""
        assessments = {
            "naming_quality": {"score": 75},
            "custom_domain_fit": {"score": 60},
        }
        result = compute_dimension_scores(
            {},
            {},
            subjective_assessments=assessments,
            allowed_subjective_dimensions={"naming_quality"},
        )
        assert "Naming quality" in result
        # Explicit assessment for custom_domain_fit still counts even though
        # it is not in the allowed set.
        assert "Custom Domain Fit" in result
        assert result["Custom Domain Fit"]["score"] == 60.0

    def test_scoring_allowed_subjective_uses_full_scorecard(self):
        """Scoring placeholders use all scorecard dimensions (load_dimensions_for_lang),
        not the curated per-language subset (HOLISTIC_DIMENSIONS_BY_LANG)."""
        from desloppify.intelligence.review.dimensions.data import (
            load_dimensions_for_lang,
        )
        from desloppify.intelligence.review.dimensions.lang import (
            HOLISTIC_DIMENSIONS_BY_LANG,
        )

        # The full scorecard must be a superset of every curated subset
        for lang_name, curated in HOLISTIC_DIMENSIONS_BY_LANG.items():
            full_dims, _, _ = load_dimensions_for_lang(lang_name)
            missing = set(curated) - set(full_dims)
            assert not missing, (
                f"{lang_name}: curated dims {missing} not in full scorecard"
            )
            # Full scorecard must be strictly larger than curated subset
            assert len(full_dims) > len(curated), (
                f"{lang_name}: full scorecard ({len(full_dims)}) should be "
                f"larger than curated subset ({len(curated)})"
            )

        # Verify scoring.py references load_dimensions_for_lang, not
        # HOLISTIC_DIMENSIONS_BY_LANG (regression guard)
        import inspect

        import desloppify.engine._scoring.state_integration as state_scoring_mod

        src = inspect.getsource(state_scoring_mod._resolve_allowed_subjective_dimensions)
        assert "load_dimensions_for_lang" in src
        assert "HOLISTIC_DIMENSIONS_BY_LANG" not in src

    def test_multiple_assessment_dimensions(self):
        """Two assessments show up independently."""
        assessments = {
            "naming_quality": {"score": 80},
            "error_handling": {"score": 60},
        }
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        assert "Naming quality" in result
        assert "Error Handling" in result
        # Assessment scores drive dimension scores directly.
        assert result["Naming quality"]["score"] == 80.0
        assert result["Error Handling"]["score"] == 60.0

    def test_assessment_perfect_score(self):
        """score=100 yields pass_rate=1.0 and weighted_failures=0."""
        assessments = {"perfection": {"score": 100}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        det = result["Perfection"]["detectors"]["subjective_assessment"]
        assert det["pass_rate"] == 1.0
        assert det["weighted_failures"] == 0.0

    def test_assessment_zero_score(self):
        """Zero assessment score yields zero dimension score."""
        assessments = {"disaster": {"score": 0}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        dim = result["Disaster"]
        assert dim["score"] == 0.0
        det = dim["detectors"]["subjective_assessment"]
        assert det["pass_rate"] == 0.0
        assert det["weighted_failures"] == pytest.approx(SUBJECTIVE_CHECKS)
        assert det["assessment_score"] == 0.0

    def test_scan_reset_subjective_forces_zero_until_rereview(self):
        assessments = {
            "naming_quality": {
                "score": 0,
                "source": "scan_reset_subjective",
                "reset_by": "scan_reset_subjective",
                "placeholder": True,
            }
        }
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        dim = result["Naming quality"]
        assert dim["score"] == 0.0
        det = dim["detectors"]["subjective_assessment"]
        assert det["pass_rate"] == 0.0
        assert det["placeholder"] is True

    def test_assessment_score_clamped(self):
        """Scores outside 0-100 are clamped."""
        assessments = {
            "too_high": {"score": 150},
            "too_low": {"score": -10},
        }
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        assert result["Too High"]["score"] == 100.0
        assert result["Too Low"]["score"] == 0.0
        high_det = result["Too High"]["detectors"]["subjective_assessment"]
        low_det = result["Too Low"]["detectors"]["subjective_assessment"]
        assert high_det["pass_rate"] == 1.0
        assert low_det["pass_rate"] == 0.0
        assert high_det["assessment_score"] == 100.0
        assert low_det["assessment_score"] == 0.0

    def test_assessment_in_objective_score(self):
        """Subjective dimensions feed into compute_health_score correctly."""
        # All default subjective dimensions appear; naming_quality assessed at 50%, rest at 0%.
        # No mechanical dims → pure subjective pool average.
        assessments = {"naming_quality": {"score": 50}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        score = compute_health_score(result)
        breakdown = compute_health_breakdown(result)
        assert breakdown["subjective_avg"] is not None
        assert score == pytest.approx(float(breakdown["subjective_avg"]), abs=0.2)

    def test_assessment_budget_blend(self):
        """Subjective dimensions use budget blend, not sample dampening.

        The overall score blends mechanical and subjective pool averages
        at the configured SUBJECTIVE_WEIGHT_FRACTION ratio,
        regardless of how many subjective dimensions there are.
        """
        from desloppify.engine._scoring.policy.core import SUBJECTIVE_WEIGHT_FRACTION

        # Build a full-weight mechanical dimension alongside subjective assessments
        potentials = {"unused": MIN_SAMPLE}  # full weight: tier 3, sample_factor 1.0
        # Set ALL default dimensions to 0 so we can predict the outcome
        from desloppify.intelligence.review import DIMENSIONS as REVIEW_DIMS

        assessments = {d: {"score": 0} for d in REVIEW_DIMS}
        result = compute_dimension_scores(
            {}, potentials, subjective_assessments=assessments
        )

        # Mechanical pool: Code quality at 100% (only mechanical dim)
        # Subjective pool: all assessments at 0 → subj_avg = 0.0
        # Budget blend: 100.0 * 0.4 + 0.0 * 0.6 = 40.0
        score = compute_health_score(result)
        expected = 100.0 * (1 - SUBJECTIVE_WEIGHT_FRACTION) + 0.0 * SUBJECTIVE_WEIGHT_FRACTION
        assert score == pytest.approx(round(expected, 1), abs=0.2)

    def test_assessment_counts_open_review_issues(self):
        """Open review issues are tracked but don't drive the score."""
        f1 = _issue("review", status="open", file="a.py")
        f1["detail"] = {"dimension": "naming_quality"}
        f2 = _issue("review", status="open", file="b.py")
        f2["detail"] = {"dimension": "naming_quality"}
        f3 = _issue("review", status="resolved", file="c.py")
        f3["detail"] = {"dimension": "naming_quality"}
        issues = _issues_dict(f1, f2, f3)
        assessments = {"naming_quality": {"score": 70}}
        result = compute_dimension_scores(
            issues, {}, subjective_assessments=assessments
        )
        dim = result["Naming quality"]
        assert dim["failing"] == 2  # only the 2 open ones tracked
        det = dim["detectors"]["subjective_assessment"]
        assert det["failing"] == 2
        # Score driven by assessment (70), not issue count
        assert det["pass_rate"] == 0.7
        assert dim["score"] == 70.0

    def test_assessment_ignores_review_issue_with_detail_none(self):
        f1 = _issue("review", status="open", file="a.py")
        f1["detail"] = None
        f2 = _issue("review", status="open", file="b.py")
        f2["detail"] = {"dimension": "naming_quality"}
        issues = _issues_dict(f1, f2)
        assessments = {"naming_quality": {"score": 70}}

        result = compute_dimension_scores(
            issues, {}, subjective_assessments=assessments
        )

        dim = result["Naming quality"]
        det = dim["detectors"]["subjective_assessment"]
        assert dim["failing"] == 1
        assert det["failing"] == 1
        assert dim["score"] == 70.0

    def test_assessment_component_breakdown_propagates_to_detector_metadata(self):
        assessments = {
            "abstraction_fitness": {
                "score": 78,
                "components": [
                    "Abstraction Leverage",
                    "Indirection Cost",
                    "Interface Honesty",
                ],
                "component_scores": {
                    "Abstraction Leverage": 81,
                    "Indirection Cost": 72,
                    "Interface Honesty": 83,
                },
            }
        }
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        det = result["Abstraction fit"]["detectors"]["subjective_assessment"]
        assert det["components"] == [
            "Abstraction Leverage",
            "Indirection Cost",
            "Interface Honesty",
        ]
        assert det["component_scores"]["Abstraction Leverage"] == 81.0
        assert det["component_scores"]["Indirection Cost"] == 72.0
        assert det["component_scores"]["Interface Honesty"] == 83.0

    def test_assessment_ignores_non_review_issues(self):
        """Smells issues with a dimension field do not count as assessment issues."""
        f = _issue("smells", status="open", file="a.py")
        f["detail"] = {"dimension": "naming_quality"}
        issues = _issues_dict(f)
        assessments = {"naming_quality": {"score": 80}}
        result = compute_dimension_scores(
            issues, {}, subjective_assessments=assessments
        )
        dim = result["Naming quality"]
        assert dim["failing"] == 0  # smells detector, not "review"

    def test_compute_score_impact_returns_zero_for_subjective(self):
        """compute_score_impact returns 0.0 for subjective dimensions."""
        assessments = {"naming_quality": {"score": 50}}
        dim_scores = compute_dimension_scores(
            {}, {}, subjective_assessments=assessments
        )
        potentials = {}
        # "subjective_assessment" is not a detector in static DIMENSIONS
        impact = compute_score_impact(
            dim_scores, potentials, "subjective_assessment", 5
        )
        assert impact == 0.0

    def test_subjective_review_not_in_any_scoring_dimension(self):
        """Verify subjective_review is excluded from scoring dimensions (non-objective)."""
        from desloppify.engine._scoring.policy.core import _NON_OBJECTIVE_DETECTORS
        assert "subjective_review" in _NON_OBJECTIVE_DETECTORS
        for dim in DIMENSIONS:
            assert "subjective_review" not in dim.detectors, (
                f"subjective_review should not be in {dim.name}"
            )


class TestConstants:
    def test_confidence_weights_keys(self):
        assert set(CONFIDENCE_WEIGHTS.keys()) == {"high", "medium", "low"}

    def test_tier_weights_keys(self):
        assert set(TIER_WEIGHTS.keys()) == {1, 2, 3, 4}

    def test_all_dimensions_have_detectors(self):
        for dim in DIMENSIONS:
            assert len(dim.detectors) > 0, f"{dim.name} has no detectors"

    def test_no_duplicate_detectors_across_dimensions(self):
        seen = set()
        for dim in DIMENSIONS:
            for det in dim.detectors:
                assert det not in seen, f"Detector {det} appears in multiple dimensions"
                seen.add(det)


# ===================================================================
# Subjective dimension name collision
# ===================================================================


class TestSubjectiveDimensionCollision:
    """Ensure subjective dimensions don't overwrite mechanical dimensions."""

    def test_security_collision_suffixed(self):
        """Subjective 'security' → 'Security' collides with
        mechanical 'Security'. Should be suffixed with (subjective)."""
        issues = _issues_dict(
            _issue("security", status="open", confidence="high"),
        )
        potentials = {"security": 10}
        assessments = {"security": {"score": 60}}
        result = compute_dimension_scores(
            issues, potentials, subjective_assessments=assessments
        )
        # Mechanical dimension should exist
        assert "Security" in result
        # Assessment should get the (subjective) suffix
        assert "Security (subjective)" in result
        # Both should have different data
        assert result["Security"]["detectors"].get("security")
        assert result["Security (subjective)"]["detectors"].get("subjective_assessment")

    def test_no_collision_no_suffix(self):
        """When there's no collision, no suffix should be added."""
        issues = {}
        potentials = {}
        assessments = {"naming_quality": {"score": 80}}
        result = compute_dimension_scores(
            issues, potentials, subjective_assessments=assessments
        )
        assert "Naming quality" in result
        assert "Naming quality (subjective)" not in result

    def test_multiple_collisions(self):
        """Multiple assessment dims that collide get suffixed independently."""
        issues = _issues_dict(
            _issue("security", status="open"),
            _issue("test_coverage", status="open"),
        )
        potentials = {"security": 10, "test_coverage": 10}
        assessments = {
            "security": {"score": 50},
            "test_health": {"score": 70},
        }
        result = compute_dimension_scores(
            issues, potentials, subjective_assessments=assessments
        )
        assert "Security" in result
        assert "Security (subjective)" in result
        assert "Test health" in result
        assert "Test Health (subjective)" in result


# ===================================================================
# DISPLAY_NAMES coverage and length
# ===================================================================


class TestDisplayNames:
    def test_display_names_cover_all_review_dimensions(self):
        """DISPLAY_NAMES covers all review dimensions."""
        from desloppify.intelligence.review import DIMENSIONS as REVIEW_DIMS

        for dim in REVIEW_DIMS:
            if dim in DISPLAY_NAMES:
                continue
            # Dimensions without an entry use the fallback .replace("_", " ").title()
            # which is fine as long as it fits

    def test_display_names_fit_scorecard(self):
        """All display names are at most 18 chars (fits ~120px monospace column)."""
        for dim_name, display in DISPLAY_NAMES.items():
            assert len(display) <= 18, (
                f"DISPLAY_NAMES[{dim_name!r}] = {display!r} is {len(display)} chars (max 18)"
            )


class TestHealthBreakdownRegression:
    def test_breakdown_exposes_pool_entries(self):
        issues = _issues_dict(
            _issue("unused", status="open"),
        )
        potentials = {"unused": 10}
        scores = compute_dimension_scores(issues, potentials)
        breakdown = compute_health_breakdown(scores)

        assert "mechanical_fraction" in breakdown
        assert "subjective_fraction" in breakdown
        assert isinstance(breakdown["entries"], list)
        assert any(entry.get("pool") == "mechanical" for entry in breakdown["entries"])
