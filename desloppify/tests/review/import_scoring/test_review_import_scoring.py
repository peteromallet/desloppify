"""Tests for the subjective code review system (review.py, commands/review/cmd.py)."""

from __future__ import annotations

from unittest.mock import patch

from desloppify.intelligence.review import (
    import_holistic_findings,
    import_review_findings,
)
from desloppify.scoring import (
    DIMENSIONS,
    FILE_BASED_DETECTORS,
    compute_dimension_scores,
)
from desloppify.state import MergeScanOptions, merge_scan
from desloppify.state import empty_state as build_empty_state
from desloppify.tests.review.shared_review_fixtures import _as_review_payload


class TestImportReviewFindings:
    def test_import_valid_findings(self, empty_state, sample_findings_data):
        diff = import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        assert diff["new"] == 3
        # Check findings were added to state
        findings = empty_state["findings"]
        assert len(findings) == 3
        # Check finding IDs follow the pattern
        ids = list(findings.keys())
        assert any("naming_quality" in fid for fid in ids)
        assert any("comment_quality" in fid for fid in ids)
        assert any("error_consistency" in fid for fid in ids)

    def test_import_skips_malformed_findings(self, empty_state):
        data = [
            {"file": "foo.ts"},  # Missing required fields
            {"dimension": "naming_quality"},  # Missing file
            {  # Valid
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "foo",
                "summary": "test",
                "confidence": "low",
            },
        ]
        diff = import_review_findings(_as_review_payload(data), empty_state, "typescript")
        assert diff["new"] == 1

    def test_import_validates_confidence(self, empty_state):
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "foo",
                "summary": "test",
                "confidence": "very_high",  # Invalid
            }
        ]
        import_review_findings(_as_review_payload(data), empty_state, "typescript")
        finding = list(empty_state["findings"].values())[0]
        assert finding["confidence"] == "low"

    def test_import_validates_dimension(self, empty_state):
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "invalid_dimension",
                "identifier": "foo",
                "summary": "test",
                "confidence": "high",
            }
        ]
        diff = import_review_findings(_as_review_payload(data), empty_state, "typescript")
        assert diff["new"] == 0

    def test_import_updates_review_cache(
        self, empty_state, sample_findings_data, tmp_path
    ):
        # Create actual files so hashing works
        (tmp_path / "src").mkdir(exist_ok=True)
        with patch("desloppify.intelligence.review.importing.per_file.PROJECT_ROOT", tmp_path):
            (tmp_path / "src" / "foo.ts").write_text("content")
            (tmp_path / "src" / "bar.ts").write_text("content")
            import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        cache = empty_state.get("review_cache", {}).get("files", {})
        assert len(cache) >= 1  # At least one file cached

    def test_import_merges_with_state(self, state_with_findings, sample_findings_data):
        diff = import_review_findings(_as_review_payload(sample_findings_data), state_with_findings, "typescript"
        )
        # Original findings should still be there
        assert "unused::src/foo.ts::bar" in state_with_findings["findings"]
        assert diff["new"] == 3

    def test_import_preserves_existing_mechanical_potentials(
        self, empty_state, sample_findings_data
    ):
        empty_state["potentials"] = {"typescript": {"unused": 10, "smells": 25}}
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")

        pots = empty_state["potentials"]["typescript"]
        assert pots["unused"] == 10
        assert pots["smells"] == 25
        assert pots.get("review", 0) > 0

    def test_import_preserves_wontfix_findings(self, empty_state, sample_findings_data):
        # First import
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        # Mark one as wontfix
        for f in empty_state["findings"].values():
            if "naming_quality" in f["id"]:
                f["status"] = "wontfix"
                f["note"] = "intentionally generic"
                break
        # Second import with same findings
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        # Wontfix should NOT be auto-resolved (it's still in current findings)
        assert any(f["status"] == "wontfix" for f in empty_state["findings"].values())
        # The finding still exists
        assert any(
            "naming_quality" in f["id"] for f in empty_state["findings"].values()
        )

    def test_import_sets_lang(self, empty_state, sample_findings_data):
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "python")
        for f in empty_state["findings"].values():
            assert f["lang"] == "python"

    def test_import_sets_tier_3(self, empty_state, sample_findings_data):
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        for f in empty_state["findings"].values():
            assert f["tier"] == 3

    def test_import_stores_detail(self, empty_state, sample_findings_data):
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        for f in empty_state["findings"].values():
            assert "dimension" in f["detail"]
            assert "suggestion" in f["detail"]

    def test_id_collision_different_summaries(self, empty_state):
        """Two findings for same file/dimension/identifier but different summaries
        must both appear in state (#56)."""
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "processData is vague — rename to reconcileInvoice",
                "evidence_lines": [15],
                "confidence": "high",
            },
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "processData doesn't indicate the return type",
                "evidence_lines": [15],
                "confidence": "medium",
            },
        ]
        diff = import_review_findings(_as_review_payload(data), empty_state, "typescript")
        assert diff["new"] == 2
        assert len(empty_state["findings"]) == 2

    def test_id_stable_for_same_summary(self, empty_state):
        """Same summary should produce the same finding ID (stable hash)."""
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "processData is vague",
                "confidence": "high",
            }
        ]
        import_review_findings(_as_review_payload(data), empty_state, "typescript")
        ids_first = set(empty_state["findings"].keys())

        # Import again — should match same IDs (no new findings)
        diff = import_review_findings(_as_review_payload(data), empty_state, "typescript")
        assert diff["new"] == 0
        assert set(empty_state["findings"].keys()) == ids_first


# ── Scoring integration tests ─────────────────────────────────────


class TestScoringIntegration:
    def test_review_findings_appear_in_scoring(self, empty_state, sample_findings_data):
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")

        # Assessment scores drive dimension scores directly.
        # Review findings are tracked but don't affect the score.
        assessments = {
            "naming_quality": {"score": 75},
            "comment_quality": {"score": 85},
        }
        potentials = {"review": 2}
        dim_scores = compute_dimension_scores(
            empty_state["findings"], potentials, subjective_assessments=assessments
        )
        assert "Naming quality" in dim_scores
        assert dim_scores["Naming quality"]["score"] == 75.0
        det = dim_scores["Naming quality"]["detectors"]["subjective_assessment"]
        assert det["assessment_score"] == 75.0

    def test_review_findings_not_auto_resolved_by_scan(
        self, empty_state, sample_findings_data
    ):
        # Import review findings
        import_review_findings(_as_review_payload(sample_findings_data), empty_state, "typescript")
        review_ids = {
            f["id"]
            for f in empty_state["findings"].values()
            if f["detector"] == "review"
        }

        # Simulate a normal scan with no review detector in potentials
        merge_scan(
            empty_state,
            [],
            options=MergeScanOptions(
                lang="typescript",
                potentials={"unused": 10, "smells": 50},
            ),
        )

        # Review findings should still be open (not auto-resolved)
        for fid in review_ids:
            if fid in empty_state["findings"]:
                assert empty_state["findings"][fid]["status"] == "open"

    def test_review_in_file_based_detectors(self):
        assert "review" in FILE_BASED_DETECTORS

    def test_test_health_dimension_exists(self):
        dim_names = [d.name for d in DIMENSIONS]
        assert "Test health" in dim_names
        rc = [d for d in DIMENSIONS if d.name == "Test health"][0]
        assert rc.tier == 4
        assert "subjective_review" in rc.detectors


# ── Assessment import tests ────────────────────────────────────────


class TestAssessmentImport:
    def test_import_new_format_with_assessments(self):
        state = build_empty_state()
        data = {
            "assessments": {"naming_quality": 75, "comment_quality": 85},
            "findings": [
                {
                    "file": "src/foo.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad name",
                    "confidence": "high",
                },
            ],
        }
        diff = import_review_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 1
        assert len(state["findings"]) == 1
        assessments = state["subjective_assessments"]
        assert "naming_quality" in assessments
        assert assessments["naming_quality"]["score"] == 75
        assert "comment_quality" in assessments
        assert assessments["comment_quality"]["score"] == 85

    def test_import_legacy_format_still_works(self):
        state = build_empty_state()
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "x",
                "summary": "bad name",
                "confidence": "high",
            },
        ]
        diff = import_review_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 1
        # Legacy format: no assessments stored
        assert state.get("subjective_assessments", {}) == {}

    def test_holistic_assessment_overwrites_per_file(self):
        state = build_empty_state()
        # Import per-file assessments first
        per_file_data = {
            "assessments": {"abstraction_fitness": 60},
            "findings": [],
        }
        import_review_findings(_as_review_payload(per_file_data), state, "typescript")
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 60

        # Import holistic assessments for the same dimension with a different score
        holistic_data = {
            "assessments": {"abstraction_fitness": 40},
            "findings": [],
        }
        import_holistic_findings(_as_review_payload(holistic_data), state, "typescript")
        # Holistic wins
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 40
        assert (
            state["subjective_assessments"]["abstraction_fitness"]["source"]
            == "holistic"
        )

    def test_per_file_does_not_overwrite_holistic(self):
        state = build_empty_state()
        # Import holistic first
        holistic_data = {
            "assessments": {"abstraction_fitness": 40},
            "findings": [],
        }
        import_holistic_findings(_as_review_payload(holistic_data), state, "typescript")
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 40

        # Import per-file for the same dimension
        per_file_data = {
            "assessments": {"abstraction_fitness": 80},
            "findings": [],
        }
        import_review_findings(_as_review_payload(per_file_data), state, "typescript")
        # Holistic score should be preserved
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 40
        assert (
            state["subjective_assessments"]["abstraction_fitness"]["source"]
            == "holistic"
        )

    def test_assessment_score_clamped(self):
        state = build_empty_state()
        data = {
            "assessments": {"naming_quality": 150},
            "findings": [],
        }
        import_review_findings(_as_review_payload(data), state, "typescript")
        assert state["subjective_assessments"]["naming_quality"]["score"] == 100

    def test_assessment_negative_clamped(self):
        state = build_empty_state()
        data = {
            "assessments": {"naming_quality": -10},
            "findings": [],
        }
        import_review_findings(_as_review_payload(data), state, "typescript")
        assert state["subjective_assessments"]["naming_quality"]["score"] == 0

    def test_import_dict_without_assessments(self):
        state = build_empty_state()
        data = {
            "findings": [
                {
                    "file": "src/foo.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad name",
                    "confidence": "high",
                },
            ],
        }
        diff = import_review_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 1
        # No assessments key in import data, so nothing stored
        assert state.get("subjective_assessments", {}) == {}
