"""Tests for desloppify.scoring — objective dimension-based scoring system."""

from __future__ import annotations

import pytest

from desloppify.scoring import (
    ASSESSMENT_CHECKS,
    CONFIDENCE_WEIGHTS,
    DIMENSIONS,
    MIN_SAMPLE,
    TIER_WEIGHTS,
    Dimension,
    _detector_pass_rate,
    compute_dimension_scores,
    compute_objective_score,
    compute_score_impact,
    get_dimension_for_detector,
    merge_potentials,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    detector: str,
    *,
    status: str = "open",
    confidence: str = "high",
    file: str = "a.py",
    zone: str = "production",
) -> dict:
    """Build a minimal finding dict."""
    return {
        "detector": detector,
        "status": status,
        "confidence": confidence,
        "file": file,
        "zone": zone,
    }


def _findings_dict(*findings: dict) -> dict:
    """Wrap a list of finding dicts into an id-keyed dict."""
    return {str(i): f for i, f in enumerate(findings)}


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
# _detector_pass_rate
# ===================================================================

class TestDetectorPassRate:
    def test_zero_potential_returns_perfect(self):
        findings = _findings_dict(_finding("unused"))
        rate, issues, weighted = _detector_pass_rate("unused", findings, 0)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_negative_potential_returns_perfect(self):
        rate, issues, weighted = _detector_pass_rate("unused", {}, -5)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_all_passing_no_findings(self):
        rate, issues, weighted = _detector_pass_rate("unused", {}, 100)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_all_passing_only_resolved_findings(self):
        findings = _findings_dict(
            _finding("unused", status="resolved"),
            _finding("unused", status="resolved"),
        )
        rate, issues, weighted = _detector_pass_rate("unused", findings, 50)
        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_some_failures_high_confidence(self):
        findings = _findings_dict(
            _finding("unused", status="open", confidence="high"),
            _finding("unused", status="open", confidence="high"),
        )
        # potential=10, 2 open high-confidence -> weighted_failures=2.0
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 2
        assert weighted == 2.0
        assert rate == pytest.approx(8.0 / 10.0)

    def test_some_failures_medium_confidence(self):
        findings = _findings_dict(
            _finding("unused", status="open", confidence="medium"),
        )
        # potential=10, 1 open medium -> weighted_failures=0.7
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 1
        assert weighted == pytest.approx(0.7)
        assert rate == pytest.approx(9.3 / 10.0)

    def test_some_failures_low_confidence(self):
        findings = _findings_dict(
            _finding("unused", status="open", confidence="low"),
        )
        # potential=10, 1 open low -> weighted_failures=0.3
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 1
        assert weighted == pytest.approx(0.3)
        assert rate == pytest.approx(9.7 / 10.0)

    def test_mixed_confidence(self):
        findings = _findings_dict(
            _finding("unused", status="open", confidence="high"),
            _finding("unused", status="open", confidence="medium"),
            _finding("unused", status="open", confidence="low"),
        )
        # weighted = 1.0 + 0.7 + 0.3 = 2.0
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 3
        assert weighted == pytest.approx(2.0)
        assert rate == pytest.approx(8.0 / 10.0)

    def test_filters_by_detector(self):
        findings = _findings_dict(
            _finding("unused", status="open", confidence="high"),
            _finding("logs", status="open", confidence="high"),
        )
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 1
        assert weighted == 1.0

    def test_excludes_non_production_zones(self):
        findings = _findings_dict(
            _finding("unused", status="open", zone="production"),
            _finding("unused", status="open", zone="test"),
            _finding("unused", status="open", zone="config"),
            _finding("unused", status="open", zone="generated"),
            _finding("unused", status="open", zone="vendor"),
        )
        # Only the production one counts
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 1
        assert weighted == 1.0

    def test_script_zone_not_excluded(self):
        """Script zone is NOT in EXCLUDED_ZONES, so it should count."""
        findings = _findings_dict(
            _finding("unused", status="open", zone="script"),
        )
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 1
        assert weighted == 1.0

    # -- strict mode --

    def test_lenient_mode_ignores_wontfix(self):
        findings = _findings_dict(
            _finding("unused", status="open"),
            _finding("unused", status="wontfix"),
        )
        rate, issues, weighted = _detector_pass_rate(
            "unused", findings, 10, strict=False)
        # Only "open" counts in lenient mode
        assert issues == 1
        assert weighted == 1.0

    def test_strict_mode_counts_wontfix(self):
        findings = _findings_dict(
            _finding("unused", status="open"),
            _finding("unused", status="wontfix"),
        )
        rate, issues, weighted = _detector_pass_rate(
            "unused", findings, 10, strict=True)
        # Both "open" and "wontfix" count in strict mode
        assert issues == 2
        assert weighted == 2.0
        assert rate == pytest.approx(8.0 / 10.0)

    # -- file-based detectors --

    def test_file_based_detector_caps_per_file_weight(self):
        """For 'smells', multiple findings in the same file are capped at 1.0 weight."""
        findings = _findings_dict(
            _finding("smells", status="open", confidence="high", file="a.py"),
            _finding("smells", status="open", confidence="high", file="a.py"),
            _finding("smells", status="open", confidence="high", file="a.py"),
        )
        # 3 high-confidence findings in same file -> raw weight 3.0, capped at 1.0
        rate, issues, weighted = _detector_pass_rate("smells", findings, 10)
        assert issues == 3
        assert weighted == 1.0  # capped at 1.0 per file
        assert rate == pytest.approx(9.0 / 10.0)

    def test_file_based_detector_multiple_files(self):
        """Smells across two files: each file capped independently."""
        findings = _findings_dict(
            _finding("smells", status="open", confidence="high", file="a.py"),
            _finding("smells", status="open", confidence="high", file="a.py"),
            _finding("smells", status="open", confidence="high", file="b.py"),
        )
        # file a.py: raw=2.0, capped=1.0; file b.py: raw=1.0, capped=1.0
        rate, issues, weighted = _detector_pass_rate("smells", findings, 10)
        assert issues == 3
        assert weighted == 2.0
        assert rate == pytest.approx(8.0 / 10.0)

    def test_file_based_low_confidence_no_cap_needed(self):
        """Low confidence per file doesn't exceed 1.0, no capping needed."""
        findings = _findings_dict(
            _finding("smells", status="open", confidence="low", file="a.py"),
            _finding("smells", status="open", confidence="low", file="a.py"),
        )
        # raw per-file weight = 0.3 + 0.3 = 0.6, below cap
        rate, issues, weighted = _detector_pass_rate("smells", findings, 10)
        assert issues == 2
        assert weighted == pytest.approx(0.6)

    def test_dict_keys_is_file_based(self):
        """dict_keys detector should also use file-based capping."""
        findings = _findings_dict(
            _finding("dict_keys", status="open", confidence="high", file="a.py"),
            _finding("dict_keys", status="open", confidence="high", file="a.py"),
        )
        rate, issues, weighted = _detector_pass_rate("dict_keys", findings, 10)
        assert issues == 2
        assert weighted == 1.0  # capped

    def test_test_coverage_is_file_based(self):
        """test_coverage detector uses loc_weight from detail, not confidence."""
        f1 = _finding("test_coverage", status="open", confidence="high", file="a.py")
        f1["detail"] = {"loc_weight": 5.0}
        findings = _findings_dict(f1)
        rate, issues, weighted = _detector_pass_rate("test_coverage", findings, 100)
        assert issues == 1
        assert weighted == pytest.approx(5.0)

    def test_test_coverage_per_file_cap(self):
        """Multiple findings for the same file are capped at one file's loc_weight."""
        f1 = _finding("test_coverage", status="open", confidence="high", file="a.py")
        f1["detail"] = {"loc_weight": 5.0}
        f2 = _finding("test_coverage", status="open", confidence="high", file="a.py")
        f2["detail"] = {"loc_weight": 5.0}
        f3 = _finding("test_coverage", status="open", confidence="high", file="a.py")
        f3["detail"] = {"loc_weight": 5.0}
        findings = _findings_dict(f1, f2, f3)
        rate, issues, weighted = _detector_pass_rate("test_coverage", findings, 100)
        assert issues == 3
        # 3 findings but capped at one file's loc_weight (5.0)
        assert weighted == pytest.approx(5.0)

    def test_test_coverage_loc_weight_default(self):
        """test_coverage findings without loc_weight default to 1.0."""
        findings = _findings_dict(
            _finding("test_coverage", status="open", confidence="high", file="a.py"),
        )
        rate, issues, weighted = _detector_pass_rate("test_coverage", findings, 10)
        assert issues == 1
        assert weighted == pytest.approx(1.0)

    def test_test_coverage_large_vs_small_files(self):
        """Large untested files contribute more to score than small ones."""
        import math
        # 500-LOC file: loc_weight = min(sqrt(500), 50) ≈ 22.4
        f_large = _finding("test_coverage", status="open", file="big.py")
        f_large["detail"] = {"loc_weight": min(math.sqrt(500), 50)}
        # 15-LOC file: loc_weight = min(sqrt(15), 50) ≈ 3.87
        f_small = _finding("test_coverage", status="open", file="small.py")
        f_small["detail"] = {"loc_weight": min(math.sqrt(15), 50)}

        # Only the large file
        large_only = _findings_dict(f_large)
        _, _, w_large = _detector_pass_rate("test_coverage", large_only, 100)
        # Only the small file
        small_only = _findings_dict(f_small)
        _, _, w_small = _detector_pass_rate("test_coverage", small_only, 100)
        # Large file contributes ~5.8x more
        assert w_large / w_small > 5

    def test_pass_rate_floor_at_zero(self):
        """Pass rate can't go below 0.0 even with huge weighted failures."""
        findings = _findings_dict(
            *[_finding("unused", status="open", confidence="high") for _ in range(20)]
        )
        rate, issues, weighted = _detector_pass_rate("unused", findings, 5)
        assert rate == 0.0
        assert issues == 20
        assert weighted == 20.0

    def test_missing_confidence_defaults_to_medium(self):
        """If confidence key is missing, weight defaults to 0.7."""
        finding_no_conf = {
            "detector": "unused",
            "status": "open",
            "file": "a.py",
            "zone": "production",
        }
        findings = {"0": finding_no_conf}
        rate, issues, weighted = _detector_pass_rate("unused", findings, 10)
        assert issues == 1
        assert weighted == pytest.approx(0.7)


# ===================================================================
# compute_dimension_scores
# ===================================================================

class TestComputeDimensionScores:
    def test_no_findings_all_potentials(self):
        potentials = {"unused": 100, "logs": 50}
        result = compute_dimension_scores({}, potentials)
        # Both unused and logs are in "Code quality" dimension
        assert "Code quality" in result
        assert result["Code quality"]["score"] == 100.0
        assert result["Code quality"]["tier"] == 3
        assert result["Code quality"]["checks"] == 150
        assert result["Code quality"]["issues"] == 0

    def test_skips_dimensions_with_zero_potential(self):
        potentials = {"structural": 100}
        result = compute_dimension_scores({}, potentials)
        assert "File health" in result
        # Duplication requires "dupes" which has no potential
        assert "Duplication" not in result

    def test_no_potentials_unassessed_dims_at_zero(self):
        """Unassessed dimensions with no findings appear at 0%."""
        result = compute_dimension_scores({}, {})
        # No mechanical dimensions
        assert "Code quality" not in result
        # Unassessed subjective dimensions always appear at 0%
        assert "Naming Quality" in result
        assert result["Naming Quality"]["score"] == 0.0

    def test_unassessed_dim_with_review_findings_included(self):
        """Unassessed dimension with open review findings is still included."""
        f = _finding("review", status="open", file="a.py")
        f["detail"] = {"dimension": "naming_quality"}
        findings = _findings_dict(f)
        result = compute_dimension_scores(findings, {})
        # Has an open review finding → included even without assessment
        assert "Naming Quality" in result
        assert result["Naming Quality"]["score"] == 0.0
        assert result["Naming Quality"]["issues"] == 1

    def test_with_some_findings(self):
        findings = _findings_dict(
            _finding("unused", status="open", confidence="high"),
            _finding("unused", status="open", confidence="high"),
        )
        potentials = {"unused": 10}
        result = compute_dimension_scores(findings, potentials)
        assert "Code quality" in result
        dim = result["Code quality"]
        assert dim["score"] == 80.0  # (10 - 2) / 10 * 100
        assert dim["issues"] == 2
        assert dim["checks"] == 10
        assert "unused" in dim["detectors"]

    def test_multi_detector_dimension(self):
        """Dimension with multiple detectors pools potentials."""
        findings = _findings_dict(
            _finding("smells", status="open", confidence="high", file="a.py"),
            _finding("react", status="open", confidence="high", file="b.tsx"),
        )
        potentials = {"smells": 50, "react": 50}
        result = compute_dimension_scores(findings, potentials)
        dim = result["Code quality"]
        # smells: 1 file-based finding -> 1.0 weighted failure
        # react: 1 non-file-based finding -> 1.0 weighted failure
        # total: (100 - 2.0) / 100 * 100 = 98.0
        assert dim["score"] == 98.0
        assert dim["checks"] == 100
        assert dim["issues"] == 2
        assert "smells" in dim["detectors"]
        assert "react" in dim["detectors"]

    def test_strict_mode_propagates(self):
        findings = _findings_dict(
            _finding("unused", status="wontfix"),
        )
        potentials = {"unused": 10}

        lenient = compute_dimension_scores(findings, potentials, strict=False)
        strict = compute_dimension_scores(findings, potentials, strict=True)

        assert lenient["Code quality"]["score"] == 100.0  # wontfix ignored
        assert strict["Code quality"]["score"] == 90.0  # wontfix counted

    def test_dimension_with_partial_detectors(self):
        """Only detectors with nonzero potential contribute."""
        # Code quality has many detectors; only naming has potential here
        potentials = {"naming": 20}  # only naming has potential
        findings = _findings_dict(
            _finding("naming", status="open", confidence="high"),
        )
        result = compute_dimension_scores(findings, potentials)
        dim = result["Code quality"]
        assert dim["checks"] == 20
        assert dim["issues"] == 1
        assert "naming" in dim["detectors"]
        assert "orphaned" not in dim["detectors"]


# ===================================================================
# compute_objective_score
# ===================================================================

class TestComputeObjectiveScore:
    def test_empty_returns_100(self):
        assert compute_objective_score({}) == 100.0

    def test_single_dimension_perfect(self):
        scores = {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "issues": 0,
                "detectors": {},
            }
        }
        assert compute_objective_score(scores) == 100.0

    def test_single_dimension_partial(self):
        scores = {
            "Code quality": {
                "score": 80.0,
                "tier": 3,
                "checks": 200,
                "issues": 5,
                "detectors": {},
            }
        }
        assert compute_objective_score(scores) == 80.0

    def test_weighted_average(self):
        """Tier-weighted average: tier3 (w=3) at 100, tier4 (w=4) at 50."""
        scores = {
            "Code quality": {
                "score": 100.0, "tier": 3,
                "checks": 200, "issues": 0, "detectors": {},
            },
            "Security": {
                "score": 50.0, "tier": 4,
                "checks": 200, "issues": 10, "detectors": {},
            },
        }
        # Both have checks >= MIN_SAMPLE (200), so full weight
        # weighted_sum = 100*3 + 50*4 = 500
        # weight_total = 3 + 4 = 7
        # result = 500 / 7 ~= 71.4
        assert compute_objective_score(scores) == pytest.approx(71.4, abs=0.1)

    def test_sample_dampening(self):
        """Dimensions with fewer than MIN_SAMPLE checks get dampened weight."""
        scores = {
            "Code quality": {
                "score": 100.0, "tier": 3,
                "checks": 200, "issues": 0, "detectors": {},
            },
            "Security": {
                "score": 0.0, "tier": 4,
                "checks": 20, "issues": 10, "detectors": {},
            },
        }
        # Code quality: weight = 3 * 1.0 = 3.0 (200 >= 200)
        # Security: weight = 4 * (20/200) = 4 * 0.1 = 0.4
        # weighted_sum = 100*3.0 + 0*0.4 = 300.0
        # weight_total = 3.0 + 0.4 = 3.4
        # result = 300.0 / 3.4 ~= 88.2
        result = compute_objective_score(scores)
        assert result == pytest.approx(88.2, abs=0.1)

    def test_all_zero_checks_returns_100(self):
        """If all dimensions have zero checks, effective weight is 0 -> 100."""
        scores = {
            "Code quality": {
                "score": 50.0, "tier": 3,
                "checks": 0, "issues": 0, "detectors": {},
            },
        }
        assert compute_objective_score(scores) == 100.0


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
                "issues": 40,
                "detectors": {
                    "unused": {
                        "potential": 200,
                        "pass_rate": 0.8,
                        "issues": 40,
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
                "issues": 40,
                "detectors": {
                    "unused": {
                        "potential": 200,
                        "pass_rate": 0.8,
                        "issues": 40,
                        "weighted_failures": 40.0,
                    },
                },
            },
            "Security": {
                "score": 100.0,
                "tier": 4,
                "checks": 200,
                "issues": 0,
                "detectors": {
                    "security": {
                        "potential": 200,
                        "pass_rate": 1.0,
                        "issues": 0,
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

class TestHolisticMultiplier:
    """Holistic findings get HOLISTIC_MULTIPLIER weight and bypass per-file cap."""

    def test_multiplier_constant_defined(self):
        from desloppify.scoring import HOLISTIC_MULTIPLIER, HOLISTIC_POTENTIAL
        assert HOLISTIC_MULTIPLIER == 10.0
        assert HOLISTIC_POTENTIAL == 10

    def test_holistic_finding_weighted(self):
        """Single holistic finding contributes confidence * HOLISTIC_MULTIPLIER."""
        from desloppify.scoring import HOLISTIC_MULTIPLIER
        f = _finding("review", confidence="high", file=".")
        f["detail"] = {"holistic": True}
        findings = _findings_dict(f)
        rate, issues, weighted = _detector_pass_rate("review", findings, 60)
        assert issues == 1
        assert weighted == pytest.approx(1.0 * HOLISTIC_MULTIPLIER)

    def test_holistic_medium_confidence(self):
        from desloppify.scoring import HOLISTIC_MULTIPLIER
        f = _finding("review", confidence="medium", file=".")
        f["detail"] = {"holistic": True}
        findings = _findings_dict(f)
        _, _, weighted = _detector_pass_rate("review", findings, 60)
        assert weighted == pytest.approx(0.7 * HOLISTIC_MULTIPLIER)

    def test_holistic_no_cap(self):
        """Multiple holistic findings are NOT capped per file."""
        from desloppify.scoring import HOLISTIC_MULTIPLIER
        f1 = _finding("review", confidence="high", file=".")
        f1["detail"] = {"holistic": True}
        f2 = _finding("review", confidence="high", file=".")
        f2["detail"] = {"holistic": True}
        findings = _findings_dict(f1, f2)
        _, issues, weighted = _detector_pass_rate("review", findings, 60)
        assert issues == 2
        assert weighted == pytest.approx(2.0 * HOLISTIC_MULTIPLIER)

    def test_file_dot_without_holistic_detail_is_file_based(self):
        """file="." WITHOUT detail.holistic should be treated as regular file-based."""
        f = _finding("review", confidence="high", file=".")
        f["detail"] = {}  # no holistic flag
        findings = _findings_dict(f)
        _, issues, weighted = _detector_pass_rate("review", findings, 60)
        assert issues == 1
        # Regular per-file: capped at 1.0
        assert weighted == pytest.approx(1.0)

    def test_mixed_holistic_and_regular(self):
        """Holistic + regular file findings combine correctly."""
        from desloppify.scoring import HOLISTIC_MULTIPLIER
        h = _finding("review", confidence="high", file=".")
        h["detail"] = {"holistic": True}
        r1 = _finding("review", confidence="high", file="src/a.py")
        r2 = _finding("review", confidence="high", file="src/a.py")
        findings = _findings_dict(h, r1, r2)
        _, issues, weighted = _detector_pass_rate("review", findings, 60)
        assert issues == 3
        # Holistic: 1.0*10=10.0, file: 2 findings same file capped at 1.0
        assert weighted == pytest.approx(10.0 + 1.0)


# ===================================================================
# Subjective dimension scoring
# ===================================================================

class TestSubjectiveScoring:
    """Tests for the subjective_assessments kwarg on compute_dimension_scores."""

    def test_no_assessments_no_change(self):
        """Calling with subjective_assessments=None produces the same result as before."""
        potentials = {"unused": 100}
        findings = _findings_dict(
            _finding("unused", status="open", confidence="high"),
        )
        without = compute_dimension_scores(findings, potentials)
        with_none = compute_dimension_scores(findings, potentials, subjective_assessments=None)
        assert without == with_none

    def test_single_assessment_dimension(self):
        """One assessment adds a dimension with the right shape."""
        assessments = {"naming_quality": {"score": 75}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        assert "Naming Quality" in result
        dim = result["Naming Quality"]
        assert dim["score"] == 75.0
        assert dim["tier"] == 4
        assert dim["checks"] == ASSESSMENT_CHECKS
        assert dim["issues"] == 0
        assert "subjective_assessment" in dim["detectors"]
        det = dim["detectors"]["subjective_assessment"]
        assert det["potential"] == ASSESSMENT_CHECKS
        assert det["pass_rate"] == 0.75
        assert det["weighted_failures"] == pytest.approx(ASSESSMENT_CHECKS * 0.25)

    def test_multiple_assessment_dimensions(self):
        """Two assessments show up independently."""
        assessments = {
            "naming_quality": {"score": 80},
            "error_handling": {"score": 60},
        }
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        assert "Naming Quality" in result
        assert "Error Handling" in result
        assert result["Naming Quality"]["score"] == 80.0
        assert result["Error Handling"]["score"] == 60.0

    def test_assessment_perfect_score(self):
        """score=100 yields pass_rate=1.0 and weighted_failures=0."""
        assessments = {"perfection": {"score": 100}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        det = result["Perfection"]["detectors"]["subjective_assessment"]
        assert det["pass_rate"] == 1.0
        assert det["weighted_failures"] == 0.0

    def test_assessment_zero_score(self):
        """score=0 yields pass_rate=0.0 and weighted_failures=ASSESSMENT_CHECKS."""
        assessments = {"disaster": {"score": 0}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        dim = result["Disaster"]
        assert dim["score"] == 0.0
        det = dim["detectors"]["subjective_assessment"]
        assert det["pass_rate"] == 0.0
        assert det["weighted_failures"] == pytest.approx(float(ASSESSMENT_CHECKS))

    def test_assessment_score_clamped(self):
        """Scores outside 0-100 are clamped."""
        assessments = {
            "too_high": {"score": 150},
            "too_low": {"score": -10},
        }
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        assert result["Too High"]["score"] == 100.0
        assert result["Too Low"]["score"] == 0.0
        # Verify pass_rate is also clamped
        assert result["Too High"]["detectors"]["subjective_assessment"]["pass_rate"] == 1.0
        assert result["Too Low"]["detectors"]["subjective_assessment"]["pass_rate"] == 0.0

    def test_assessment_in_objective_score(self):
        """Subjective dimensions feed into compute_objective_score correctly."""
        # All 7 subjective dimensions appear; naming_quality assessed at 50%, rest at 0%
        # No mechanical dims → pure subjective avg: (50*4 + 0*4*6) / (4*7)
        assessments = {"naming_quality": {"score": 50}}
        result = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        score = compute_objective_score(result)
        # Pure subjective (no mechanical): tier-weighted avg = (50*4)/(7*4)
        # But budget blend sees mech_weight=0 → returns pure subj_avg
        n_dims = 7  # DEFAULT_DIMENSIONS count
        subj_avg = (50 * 4 + 0 * 4 * (n_dims - 1)) / (n_dims * 4)
        assert score == pytest.approx(subj_avg, abs=0.2)

    def test_assessment_budget_blend(self):
        """Subjective dimensions use budget blend, not sample dampening.

        The overall score blends mechanical and subjective pool averages
        at the configured SUBJECTIVE_WEIGHT_FRACTION ratio,
        regardless of how many subjective dimensions there are.
        """
        from desloppify.scoring import SUBJECTIVE_WEIGHT_FRACTION
        # Build a full-weight mechanical dimension alongside subjective assessments
        potentials = {"unused": MIN_SAMPLE}  # full weight: tier 3, sample_factor 1.0
        # Set ALL default dimensions to 0 so we can predict the outcome
        from desloppify.review import DEFAULT_DIMENSIONS
        assessments = {d: {"score": 0} for d in DEFAULT_DIMENSIONS}
        result = compute_dimension_scores({}, potentials, subjective_assessments=assessments)

        # Mechanical pool: Code quality at 100% (only mechanical dim)
        # Subjective pool: all dims at 0% → subj_avg = 0.0
        # Budget blend: 100.0 * (1 - frac) + 0.0 * frac
        score = compute_objective_score(result)
        expected = 100.0 * (1 - SUBJECTIVE_WEIGHT_FRACTION) + 0.0 * SUBJECTIVE_WEIGHT_FRACTION
        assert score == pytest.approx(round(expected, 1), abs=0.2)

    def test_assessment_counts_open_review_findings(self):
        """Open review findings with matching dimension are counted as issues."""
        f1 = _finding("review", status="open", file="a.py")
        f1["detail"] = {"dimension": "naming_quality"}
        f2 = _finding("review", status="open", file="b.py")
        f2["detail"] = {"dimension": "naming_quality"}
        f3 = _finding("review", status="resolved", file="c.py")
        f3["detail"] = {"dimension": "naming_quality"}
        findings = _findings_dict(f1, f2, f3)
        assessments = {"naming_quality": {"score": 70}}
        result = compute_dimension_scores(findings, {}, subjective_assessments=assessments)
        dim = result["Naming Quality"]
        assert dim["issues"] == 2  # only the 2 open ones
        assert dim["detectors"]["subjective_assessment"]["issues"] == 2

    def test_assessment_ignores_non_review_findings(self):
        """Smells findings with a dimension field do not count as assessment issues."""
        f = _finding("smells", status="open", file="a.py")
        f["detail"] = {"dimension": "naming_quality"}
        findings = _findings_dict(f)
        assessments = {"naming_quality": {"score": 80}}
        result = compute_dimension_scores(findings, {}, subjective_assessments=assessments)
        dim = result["Naming Quality"]
        assert dim["issues"] == 0  # smells detector, not "review"

    def test_compute_score_impact_returns_zero_for_subjective(self):
        """compute_score_impact returns 0.0 for subjective dimensions."""
        assessments = {"naming_quality": {"score": 50}}
        dim_scores = compute_dimension_scores({}, {}, subjective_assessments=assessments)
        potentials = {}
        # "subjective_assessment" is not a detector in static DIMENSIONS
        impact = compute_score_impact(dim_scores, potentials, "subjective_assessment", 5)
        assert impact == 0.0

    def test_test_health_dimension_has_subjective_review(self):
        """Verify 'Test health' dimension contains subjective_review detector."""
        test_dim = None
        for dim in DIMENSIONS:
            if dim.name == "Test health":
                test_dim = dim
                break
        assert test_dim is not None, "Test health dimension not found"
        assert "subjective_review" in test_dim.detectors
        assert test_dim.tier == 4


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
        findings = _findings_dict(
            _finding("security", status="open", confidence="high"),
        )
        potentials = {"security": 10}
        assessments = {"security": {"score": 60}}
        result = compute_dimension_scores(findings, potentials,
                                          subjective_assessments=assessments)
        # Mechanical dimension should exist
        assert "Security" in result
        # Assessment should get the (subjective) suffix
        assert "Security (subjective)" in result
        # Both should have different data
        assert result["Security"]["detectors"].get("security")
        assert result["Security (subjective)"]["detectors"].get("subjective_assessment")

    def test_no_collision_no_suffix(self):
        """When there's no collision, no suffix should be added."""
        findings = {}
        potentials = {}
        assessments = {"naming_quality": {"score": 80}}
        result = compute_dimension_scores(findings, potentials,
                                          subjective_assessments=assessments)
        assert "Naming Quality" in result
        assert "Naming Quality (subjective)" not in result

    def test_multiple_collisions(self):
        """Multiple assessment dims that collide get suffixed independently."""
        findings = _findings_dict(
            _finding("security", status="open"),
            _finding("test_coverage", status="open"),
        )
        potentials = {"security": 10, "test_coverage": 10}
        assessments = {
            "security": {"score": 50},
            "test_health": {"score": 70},
        }
        result = compute_dimension_scores(findings, potentials,
                                          subjective_assessments=assessments)
        assert "Security" in result
        assert "Security (subjective)" in result
        assert "Test health" in result
        assert "Test Health (subjective)" in result
