"""Tests for desloppify.scoring — objective dimension-based scoring system."""

from __future__ import annotations

import pytest

from desloppify.engine._scoring.detection import (
    detector_pass_rate,
    merge_potentials,
)
from desloppify.engine._scoring.policy.core import (
    SUBJECTIVE_CHECKS,
    Dimension,
)
from desloppify.engine._scoring.results.core import (
    compute_dimension_scores,
    compute_health_breakdown,
    compute_health_score,
    compute_score_bundle,
    compute_score_impact,
    get_dimension_for_detector,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ===================================================================
# merge_potentials
# ===================================================================


class TestMergePotentials:
    def test_multiple_languages(self):
        potentials_by_lang = {
            "python": {"unused": 50, "smells": 30},
            "typescript": {"unused": 100, "smells": 60},
        }
        result = merge_potentials(potentials_by_lang)
        assert result == {"unused": 150, "smells": 90}

    def test_empty_input(self):
        assert merge_potentials({}) == {}

    def test_single_language(self):
        potentials = {"python": {"unused": 10, "logs": 5}}
        result = merge_potentials(potentials)
        assert result == {"unused": 10, "logs": 5}

    def test_non_overlapping_detectors(self):
        potentials_by_lang = {
            "python": {"unused": 20},
            "typescript": {"smells": 40},
        }
        result = merge_potentials(potentials_by_lang)
        assert result == {"unused": 20, "smells": 40}

    def test_three_languages(self):
        potentials_by_lang = {
            "python": {"unused": 10},
            "typescript": {"unused": 20},
            "go": {"unused": 30},
        }
        result = merge_potentials(potentials_by_lang)
        assert result == {"unused": 60}


# ===================================================================
# detector_pass_rate
# ===================================================================


class TestDetectorPassRate:
    def test_zero_potential_returns_perfect(self):
        issues = _issues_dict(_issue("unused"))
        rate, issues, weighted = detector_pass_rate("unused", issues, 0)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_negative_potential_returns_perfect(self):
        rate, issues, weighted = detector_pass_rate("unused", {}, -5)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_all_passing_no_issues(self):
        rate, issues, weighted = detector_pass_rate("unused", {}, 100)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_all_passing_only_resolved_issues(self):
        issues = _issues_dict(
            _issue("unused", status="resolved"),
            _issue("unused", status="resolved"),
        )
        rate, issues, weighted = detector_pass_rate("unused", issues, 50)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_some_failures_high_confidence(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
            _issue("unused", status="open", confidence="high"),
        )
        # potential=10, 2 open high-confidence -> weighted_failures=2.0
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 2
        assert weighted == 2.0
        assert rate == pytest.approx(8.0 / 10.0)

    def test_some_failures_medium_confidence(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="medium"),
        )
        # potential=10, 1 open medium -> weighted_failures=0.7
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 1
        assert weighted == pytest.approx(0.7)
        assert rate == pytest.approx(9.3 / 10.0)

    def test_some_failures_low_confidence(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="low"),
        )
        # potential=10, 1 open low -> weighted_failures=0.3
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 1
        assert weighted == pytest.approx(0.3)
        assert rate == pytest.approx(9.7 / 10.0)

    def test_mixed_confidence(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
            _issue("unused", status="open", confidence="medium"),
            _issue("unused", status="open", confidence="low"),
        )
        # weighted = 1.0 + 0.7 + 0.3 = 2.0
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 3
        assert weighted == pytest.approx(2.0)
        assert rate == pytest.approx(8.0 / 10.0)

    def test_filters_by_detector(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
            _issue("logs", status="open", confidence="high"),
        )
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 1
        assert weighted == 1.0

    def test_excludes_non_production_zones(self):
        issues = _issues_dict(
            _issue("unused", status="open", zone="production"),
            _issue("unused", status="open", zone="test"),
            _issue("unused", status="open", zone="config"),
            _issue("unused", status="open", zone="generated"),
            _issue("unused", status="open", zone="vendor"),
        )
        # Only the production one counts
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 1
        assert weighted == 1.0

    def test_script_zone_not_excluded(self):
        """Script zone is NOT in EXCLUDED_ZONES, so it should count."""
        issues = _issues_dict(
            _issue("unused", status="open", zone="script"),
        )
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 1
        assert weighted == 1.0

    # -- strict mode --

    def test_lenient_mode_ignores_wontfix(self):
        issues = _issues_dict(
            _issue("unused", status="open"),
            _issue("unused", status="wontfix"),
        )
        rate, issues, weighted = detector_pass_rate(
            "unused", issues, 10, strict=False
        )
        # Only "open" counts in lenient mode
        assert issues == 1
        assert weighted == 1.0

    def test_strict_mode_counts_wontfix(self):
        issues = _issues_dict(
            _issue("unused", status="open"),
            _issue("unused", status="wontfix"),
        )
        rate, issues, weighted = detector_pass_rate(
            "unused", issues, 10, strict=True
        )
        # Both "open" and "wontfix" count in strict mode
        assert issues == 2
        assert weighted == 2.0
        assert rate == pytest.approx(8.0 / 10.0)

    # -- file-based detectors --

    def test_file_based_detector_uses_tiered_per_file_cap(self):
        """For 'smells', heavy same-file concentration lifts the per-file cap."""
        issues = _issues_dict(
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
        )
        # 3 issues in one file => tier cap 1.5
        rate, issues, weighted = detector_pass_rate("smells", issues, 10)
        assert issues == 3
        assert weighted == pytest.approx(1.5)
        assert rate == pytest.approx(8.5 / 10.0)

    def test_file_based_detector_multiple_files(self):
        """Smells across two files: each file still caps independently."""
        issues = _issues_dict(
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="b.py"),
        )
        # file a.py: 2 issues => cap 1.0; file b.py: 1 issue => cap 1.0
        rate, issues, weighted = detector_pass_rate("smells", issues, 10)
        assert issues == 3
        assert weighted == 2.0
        assert rate == pytest.approx(8.0 / 10.0)

    def test_file_based_low_confidence_no_cap_needed(self):
        """Low confidence per file doesn't exceed 1.0, no capping needed."""
        issues = _issues_dict(
            _issue("smells", status="open", confidence="low", file="a.py"),
            _issue("smells", status="open", confidence="low", file="a.py"),
        )
        # raw per-file weight = 0.3 + 0.3 = 0.6, below cap
        rate, issues, weighted = detector_pass_rate("smells", issues, 10)
        assert issues == 2
        assert weighted == pytest.approx(0.6)

    def test_file_based_high_count_uses_highest_tier_cap(self):
        """6+ issues in one file are capped at 2.0 (not 1.0)."""
        issues = _issues_dict(
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("smells", status="open", confidence="high", file="a.py"),
        )
        rate, issues, weighted = detector_pass_rate("smells", issues, 10)
        assert issues == 6
        assert weighted == pytest.approx(2.0)
        assert rate == pytest.approx(8.0 / 10.0)

    def test_file_based_tiered_cap_respects_confidence_weights(self):
        """Tiering raises the cap, but low-confidence raw weight still applies."""
        issues = _issues_dict(
            _issue("smells", status="open", confidence="low", file="a.py"),
            _issue("smells", status="open", confidence="low", file="a.py"),
            _issue("smells", status="open", confidence="low", file="a.py"),
        )
        # 3 low-confidence issues => raw 0.9, tier cap 1.5 => 0.9 retained.
        rate, issues, weighted = detector_pass_rate("smells", issues, 10)
        assert issues == 3
        assert weighted == pytest.approx(0.9)
        assert rate == pytest.approx(9.1 / 10.0)

    def test_dict_keys_is_file_based(self):
        """dict_keys detector should also use file-based tiered capping."""
        issues = _issues_dict(
            _issue("dict_keys", status="open", confidence="high", file="a.py"),
            _issue("dict_keys", status="open", confidence="high", file="a.py"),
        )
        rate, issues, weighted = detector_pass_rate("dict_keys", issues, 10)
        assert issues == 2
        assert weighted == 1.0  # capped

    def test_test_coverage_is_file_based(self):
        """test_coverage detector uses loc_weight from detail, not confidence."""
        f1 = _issue("test_coverage", status="open", confidence="high", file="a.py")
        f1["detail"] = {"loc_weight": 5.0}
        issues = _issues_dict(f1)
        rate, issues, weighted = detector_pass_rate("test_coverage", issues, 100)
        assert issues == 1
        assert weighted == pytest.approx(5.0)

    def test_test_coverage_per_file_cap(self):
        """Multiple issues for the same file are capped at one file's loc_weight."""
        f1 = _issue("test_coverage", status="open", confidence="high", file="a.py")
        f1["detail"] = {"loc_weight": 5.0}
        f2 = _issue("test_coverage", status="open", confidence="high", file="a.py")
        f2["detail"] = {"loc_weight": 5.0}
        f3 = _issue("test_coverage", status="open", confidence="high", file="a.py")
        f3["detail"] = {"loc_weight": 5.0}
        issues = _issues_dict(f1, f2, f3)
        rate, issues, weighted = detector_pass_rate("test_coverage", issues, 100)
        assert issues == 3
        # 3 issues but capped at one file's loc_weight (5.0)
        assert weighted == pytest.approx(5.0)

    def test_test_coverage_loc_weight_default(self):
        """test_coverage issues without loc_weight default to 1.0."""
        issues = _issues_dict(
            _issue("test_coverage", status="open", confidence="high", file="a.py"),
        )
        rate, issues, weighted = detector_pass_rate("test_coverage", issues, 10)
        assert issues == 1
        assert weighted == pytest.approx(1.0)

    def test_test_coverage_large_vs_small_files(self):
        """Large untested files contribute more to score than small ones."""
        import math

        # 500-LOC file: loc_weight = min(sqrt(500), 50) ≈ 22.4
        f_large = _issue("test_coverage", status="open", file="big.py")
        f_large["detail"] = {"loc_weight": min(math.sqrt(500), 50)}
        # 15-LOC file: loc_weight = min(sqrt(15), 50) ≈ 3.87
        f_small = _issue("test_coverage", status="open", file="small.py")
        f_small["detail"] = {"loc_weight": min(math.sqrt(15), 50)}

        # Only the large file
        large_only = _issues_dict(f_large)
        _, _, w_large = detector_pass_rate("test_coverage", large_only, 100)
        # Only the small file
        small_only = _issues_dict(f_small)
        _, _, w_small = detector_pass_rate("test_coverage", small_only, 100)
        # Large file contributes ~5.8x more
        assert w_large / w_small > 5

    def test_pass_rate_floor_at_zero(self):
        """Pass rate can't go below 0.0 even with huge weighted failures."""
        issues = _issues_dict(
            *[_issue("unused", status="open", confidence="high") for _ in range(20)]
        )
        rate, issues, weighted = detector_pass_rate("unused", issues, 5)
        assert rate == 0.0
        assert issues == 20
        assert weighted == 20.0

    def test_missing_confidence_defaults_to_medium(self):
        """If confidence key is missing, weight defaults to 0.7."""
        issue_no_conf = {
            "detector": "unused",
            "status": "open",
            "file": "a.py",
            "zone": "production",
        }
        issues = {"0": issue_no_conf}
        rate, issues, weighted = detector_pass_rate("unused", issues, 10)
        assert issues == 1
        assert weighted == pytest.approx(0.7)


# ===================================================================
# compute_dimension_scores
# ===================================================================


class TestComputeDimensionScores:
    def test_no_issues_all_potentials(self):
        potentials = {"unused": 100, "logs": 50}
        result = compute_dimension_scores({}, potentials)
        # Both unused and logs are in "Code quality" dimension
        assert "Code quality" in result
        assert result["Code quality"]["score"] == 100.0
        assert result["Code quality"]["tier"] == 3
        assert result["Code quality"]["checks"] == 150
        assert result["Code quality"]["failing"] == 0

    def test_skips_dimensions_with_zero_potential(self):
        potentials = {"structural": 100}
        result = compute_dimension_scores({}, potentials)
        assert "File health" in result
        # Duplication requires "dupes" which has no potential
        assert "Duplication" not in result

    def test_no_potentials_unassessed_dims_start_at_zero(self):
        """Unassessed dimensions with no review issues start at 0%."""
        result = compute_dimension_scores({}, {})
        # No mechanical dimensions
        assert "Code quality" not in result
        # Subjective placeholders are explicit 0% until assessed.
        assert "Naming quality" in result
        assert result["Naming quality"]["score"] == 0.0
        det = result["Naming quality"]["detectors"]["subjective_assessment"]
        assert det["placeholder"] is True

    def test_unassessed_dim_with_review_issues_still_zero(self):
        """Review issues don't drive score — unassessed placeholders stay at 0."""
        f = _issue("review", status="open", file="a.py")
        f["detail"] = {"dimension": "naming_quality"}
        issues = _issues_dict(f)
        result = compute_dimension_scores(issues, {})
        # Review issues are tracked but don't change placeholder score.
        assert "Naming quality" in result
        assert result["Naming quality"]["score"] == 0.0
        assert result["Naming quality"]["failing"] == 1
        det = result["Naming quality"]["detectors"]["subjective_assessment"]
        assert det["placeholder"] is True

    def test_with_some_issues(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
            _issue("unused", status="open", confidence="high"),
        )
        potentials = {"unused": 10}
        result = compute_dimension_scores(issues, potentials)
        assert "Code quality" in result
        dim = result["Code quality"]
        assert dim["score"] == 80.0  # (10 - 2) / 10 * 100
        assert dim["failing"] == 2
        assert dim["checks"] == 10
        assert "unused" in dim["detectors"]

    def test_multi_detector_dimension(self):
        """Dimension with multiple detectors pools potentials."""
        issues = _issues_dict(
            _issue("smells", status="open", confidence="high", file="a.py"),
            _issue("react", status="open", confidence="high", file="b.tsx"),
        )
        potentials = {"smells": 50, "react": 50}
        result = compute_dimension_scores(issues, potentials)
        dim = result["Code quality"]
        # smells: 1 file-based issue -> 1.0 weighted failure
        # react: 1 non-file-based issue -> 1.0 weighted failure
        # total: (100 - 2.0) / 100 * 100 = 98.0
        assert dim["score"] == 98.0
        assert dim["checks"] == 100
        assert dim["failing"] == 2
        assert "smells" in dim["detectors"]
        assert "react" in dim["detectors"]

    def test_strict_mode_propagates(self):
        issues = _issues_dict(
            _issue("unused", status="wontfix"),
        )
        potentials = {"unused": 10}

        lenient = compute_dimension_scores(issues, potentials, strict=False)
        strict = compute_dimension_scores(issues, potentials, strict=True)

        assert lenient["Code quality"]["score"] == 100.0  # wontfix ignored
        assert strict["Code quality"]["score"] == 90.0  # wontfix counted

    def test_dimension_with_partial_detectors(self):
        """Only detectors with nonzero potential contribute."""
        # Code quality has many detectors; only naming has potential here
        potentials = {"naming": 20}  # only naming has potential
        issues = _issues_dict(
            _issue("naming", status="open", confidence="high"),
        )
        result = compute_dimension_scores(issues, potentials)
        dim = result["Code quality"]
        assert dim["checks"] == 20
        assert dim["failing"] == 1
        assert "naming" in dim["detectors"]
        assert "orphaned" not in dim["detectors"]


# ===================================================================
# compute_health_score
# ===================================================================


class TestComputeHealthScore:
    def test_empty_returns_100(self):
        assert compute_health_score({}) == 100.0

    def test_single_dimension_perfect(self):
        scores = {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "failing": 0,
                "detectors": {},
            }
        }
        assert compute_health_score(scores) == 100.0


class TestComputeScoreBundle:
    def test_auto_resolved_and_false_positive_have_distinct_strict_semantics(self):
        auto_resolved = compute_score_bundle(
            _issues_dict(_issue("unused", status="auto_resolved")),
            {"unused": 10},
        )
        false_positive = compute_score_bundle(
            _issues_dict(_issue("unused", status="false_positive")),
            {"unused": 10},
        )

        assert auto_resolved.strict_dimension_scores["Code quality"]["score"] == 90.0
        assert auto_resolved.verified_strict_dimension_scores["Code quality"]["score"] == 100.0
        assert false_positive.strict_dimension_scores["Code quality"]["score"] == 100.0
        assert false_positive.verified_strict_dimension_scores["Code quality"]["score"] == 90.0

    def test_bundle_mode_dimensions(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
            _issue("unused", status="wontfix", confidence="high"),
            _issue("unused", status="fixed", confidence="high"),
        )
        bundle = compute_score_bundle(issues, {"unused": 10})

        # By mode for the same detector:
        # lenient: open only -> 1.0 weighted failure -> 90%
        # strict: open + wontfix -> 2.0 weighted failures -> 80%
        # verified_strict: open + wontfix + fixed -> 3.0 weighted failures -> 70%
        assert bundle.dimension_scores["Code quality"]["score"] == 90.0
        assert bundle.strict_dimension_scores["Code quality"]["score"] == 80.0
        assert bundle.verified_strict_dimension_scores["Code quality"]["score"] == 70.0

        # Objective score is mechanical lenient only.
        assert bundle.objective_score == 90.0

    def test_bundle_scores_match_health_function(self):
        issues = _issues_dict(
            _issue("unused", status="open", confidence="high"),
        )
        bundle = compute_score_bundle(issues, {"unused": 10})

        assert bundle.overall_score == compute_health_score(bundle.dimension_scores)
        assert bundle.strict_score == compute_health_score(
            bundle.strict_dimension_scores
        )
        assert bundle.verified_strict_score == compute_health_score(
            bundle.verified_strict_dimension_scores
        )


class TestComputeHealthScoreAdditional:
    def test_single_dimension_partial(self):
        scores = {
            "Code quality": {
                "score": 80.0,
                "tier": 3,
                "checks": 200,
                "failing": 5,
                "detectors": {},
            }
        }
        assert compute_health_score(scores) == 80.0

    def test_weighted_average(self):
        """Mechanical pool uses configured per-dimension weights (equal by default)."""
        scores = {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "failing": 0,
                "detectors": {},
            },
            "Security": {
                "score": 50.0,
                "tier": 4,
                "checks": 200,
                "failing": 10,
                "detectors": {},
            },
        }
        # Both have checks >= MIN_SAMPLE (200), so full configured weights (1.0 each).
        # weighted_sum = 100*1 + 50*1 = 150
        # weight_total = 2
        # result = 75.0
        assert compute_health_score(scores) == pytest.approx(75.0, abs=0.1)

    def test_sample_dampening(self):
        """Dimensions with fewer than MIN_SAMPLE checks get dampened weight."""
        scores = {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "failing": 0,
                "detectors": {},
            },
            "Security": {
                "score": 0.0,
                "tier": 4,
                "checks": 20,
                "failing": 10,
                "detectors": {},
            },
        }
        # Code quality: weight = 1.0 * 1.0 = 1.0 (200 >= 200)
        # Security: weight = 1.0 * (20/200) = 0.1
        # weighted_sum = 100*1.0 + 0*0.1 = 100.0
        # weight_total = 1.1
        # result = 100.0 / 1.1 ~= 90.9
        result = compute_health_score(scores)
        assert result == pytest.approx(90.9, abs=0.1)

    def test_all_zero_checks_returns_100(self):
        """If all dimensions have zero checks, effective weight is 0 -> 100."""
        scores = {
            "Code quality": {
                "score": 50.0,
                "tier": 3,
                "checks": 0,
                "failing": 0,
                "detectors": {},
            },
        }
        assert compute_health_score(scores) == 100.0


class TestComputeHealthBreakdown:
    def test_reports_pool_blend_and_dimension_drag(self):
        scores = {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "failing": 0,
                "detectors": {},
            },
            "High elegance": {
                "score": 80.0,
                "tier": 4,
                "checks": SUBJECTIVE_CHECKS,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        }
        breakdown = compute_health_breakdown(scores)
        assert breakdown["mechanical_fraction"] == pytest.approx(0.25)
        assert breakdown["subjective_fraction"] == pytest.approx(0.75)
        assert breakdown["overall_score"] == pytest.approx(85.0, abs=0.1)

        rows = {entry["name"]: entry for entry in breakdown["entries"]}
        assert rows["High elegance"]["pool"] == "subjective"
        assert rows["High elegance"]["overall_drag"] == pytest.approx(15.0, abs=0.1)
        assert rows["Code quality"]["pool"] == "mechanical"
        assert rows["Code quality"]["overall_contribution"] == pytest.approx(
            25.0, abs=0.1
        )

    def test_mechanical_only_falls_back_to_full_mechanical_fraction(self):
        scores = {
            "Code quality": {
                "score": 90.0,
                "tier": 3,
                "checks": 200,
                "failing": 0,
                "detectors": {},
            }
        }
        breakdown = compute_health_breakdown(scores)
        assert breakdown["mechanical_fraction"] == pytest.approx(1.0)
        assert breakdown["subjective_fraction"] == pytest.approx(0.0)
        assert breakdown["overall_score"] == pytest.approx(90.0, abs=0.1)


# ===================================================================
# get_dimension_for_detector
# ===================================================================


class TestGetDimensionForDetector:
    def test_known_detector_unused(self):
        dim = get_dimension_for_detector("unused")
        assert dim is not None
        assert dim.name == "Code quality"
        assert dim.tier == 3

    def test_known_detector_smells(self):
        dim = get_dimension_for_detector("smells")
        assert dim is not None
        assert dim.name == "Code quality"

    def test_known_detector_cycles(self):
        dim = get_dimension_for_detector("cycles")
        assert dim is not None
        assert dim.name == "Security"
        assert dim.tier == 4

    def test_known_detector_props(self):
        dim = get_dimension_for_detector("props")
        assert dim is not None
        assert dim.name == "Code quality"

    def test_unknown_detector(self):
        assert get_dimension_for_detector("nonexistent_detector") is None

    def test_returns_dimension_dataclass(self):
        dim = get_dimension_for_detector("logs")
        assert isinstance(dim, Dimension)
        assert dim.name == "Code quality"
        assert "logs" in dim.detectors


# ===================================================================
# compute_score_impact
# ===================================================================


class TestComputeScoreImpact:
    def _make_dimension_scores(self):
        """Build dimension_scores with one dimension that has issues."""
        return {
            "Code quality": {
                "score": 80.0,
                "tier": 3,
                "checks": 200,
                "failing": 40,
                "detectors": {
                    "unused": {
                        "potential": 200,
                        "pass_rate": 0.8,
                        "failing": 40,
                        "weighted_failures": 40.0,
                    },
                },
            },
        }

    def test_fixing_issues_improves_score(self):
        scores = self._make_dimension_scores()
        potentials = {"unused": 200}
        impact = compute_score_impact(scores, potentials, "unused", 10)
        assert impact > 0

    def test_unknown_detector_returns_zero(self):
        scores = self._make_dimension_scores()
        potentials = {"unused": 200}
        impact = compute_score_impact(scores, potentials, "nonexistent", 10)
        assert impact == 0.0

    def test_detector_not_in_dimension_scores(self):
        """Detector exists in DIMENSIONS but dimension not in scores."""
        scores = {}  # no dimensions
        potentials = {"unused": 200}
        impact = compute_score_impact(scores, potentials, "unused", 10)
        assert impact == 0.0

    def test_zero_potential_returns_zero(self):
        scores = self._make_dimension_scores()
        potentials = {"unused": 0}
        impact = compute_score_impact(scores, potentials, "unused", 10)
        assert impact == 0.0

    def test_fixing_all_issues(self):
        scores = self._make_dimension_scores()
        potentials = {"unused": 200}
        # Fix all 40 issues -> score should go from 80 to 100
        impact = compute_score_impact(scores, potentials, "unused", 40)
        assert impact == pytest.approx(20.0, abs=0.1)

    def test_fixing_zero_issues(self):
        scores = self._make_dimension_scores()
        potentials = {"unused": 200}
        impact = compute_score_impact(scores, potentials, "unused", 0)
        assert impact == 0.0

    def test_does_not_mutate_input(self):
        scores = self._make_dimension_scores()
        original_score = scores["Code quality"]["score"]
        potentials = {"unused": 200}
        compute_score_impact(scores, potentials, "unused", 10)
        # Original scores dict should be unchanged
        assert scores["Code quality"]["score"] == original_score

    def test_multi_dimension_impact(self):
        """Impact is computed relative to the full set of dimensions."""
        scores = {
            "Code quality": {
                "score": 80.0,
                "tier": 3,
                "checks": 200,
                "failing": 40,
                "detectors": {
                    "unused": {
                        "potential": 200,
                        "pass_rate": 0.8,
                        "failing": 40,
                        "weighted_failures": 40.0,
                    },
                },
            },
            "Security": {
                "score": 100.0,
                "tier": 4,
                "checks": 200,
                "failing": 0,
                "detectors": {
                    "security": {
                        "potential": 200,
                        "pass_rate": 1.0,
                        "failing": 0,
                        "weighted_failures": 0.0,
                    },
                },
            },
        }
        potentials = {"unused": 200, "security": 200}
        impact = compute_score_impact(scores, potentials, "unused", 40)
        # With tier weighting, fixing Code quality from 80->100 is diluted
        # by the Security dimension already being at 100
        assert impact > 0
        assert impact < 20.0  # Less than if it were the only dimension


# ===================================================================
# Module-level constants sanity checks
# ===================================================================


class TestReviewScoringExclusion:
    """Review issues are excluded from detection scoring (assessed via subjective only)."""

    def test_multiplier_constant_still_defined(self):
        """HOLISTIC_MULTIPLIER still exists for display/priority purposes."""
        from desloppify.engine._scoring.policy.core import (
            HOLISTIC_MULTIPLIER,
            HOLISTIC_POTENTIAL,
        )

        assert HOLISTIC_MULTIPLIER == 10.0
        assert HOLISTIC_POTENTIAL == 10

    def test_review_issues_return_perfect_score(self):
        """Review detector always returns (1.0, 0, 0.0) — excluded from scoring."""
        f = _issue("review", confidence="high", file=".")
        f["detail"] = {"holistic": True}
        issues = _issues_dict(f)
        rate, issues, weighted = detector_pass_rate("review", issues, 60)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_multiple_review_issues_excluded(self):
        """Multiple review issues still return perfect score."""
        f1 = _issue("review", confidence="high", file=".")
        f1["detail"] = {"holistic": True}
        f2 = _issue("review", confidence="high", file=".")
        f2["detail"] = {"holistic": True}
        issues = _issues_dict(f1, f2)
        rate, issues, weighted = detector_pass_rate("review", issues, 60)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_file_based_review_also_excluded(self):
        """file="." without holistic detail is also excluded for review detector."""
        f = _issue("review", confidence="high", file=".")
        f["detail"] = {}
        issues = _issues_dict(f)
        rate, issues, weighted = detector_pass_rate("review", issues, 60)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_mixed_review_issues_excluded(self):
        """Both holistic and file-based review issues are excluded."""
        h = _issue("review", confidence="high", file=".")
        h["detail"] = {"holistic": True}
        r1 = _issue("review", confidence="high", file="src/a.py")
        r2 = _issue("review", confidence="high", file="src/a.py")
        issues = _issues_dict(h, r1, r2)
        rate, issues, weighted = detector_pass_rate("review", issues, 60)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0


# ===================================================================
# Subjective dimension scoring
# ===================================================================

