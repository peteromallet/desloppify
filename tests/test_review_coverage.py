"""Tests for review coverage detector, ID collision fix, and new subjective dimensions."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.detectors.review_coverage import detect_review_coverage
from desloppify.review import (
    DEFAULT_DIMENSIONS, DIMENSION_PROMPTS,
    import_review_findings, MIN_REVIEW_LOC,
)
from desloppify.state import _find_suspect_detectors, make_finding, _empty_state, merge_scan
from desloppify.scoring import DIMENSIONS, _FILE_BASED_DETECTORS
from desloppify.registry import DETECTORS, _DISPLAY_ORDER


# ── Helpers ──────────────────────────────────────────────────────


class FakeZone:
    def __init__(self, val):
        self.value = val


class FakeZoneMap:
    """Minimal zone map for testing."""
    def __init__(self, mapping=None):
        self._map = mapping or {}

    def get(self, filepath):
        return self._map.get(filepath, FakeZone("production"))

    def counts(self):
        return {}


def _make_file(tmpdir, name, lines=30):
    """Create a file with enough lines to pass MIN_REVIEW_LOC."""
    p = os.path.join(tmpdir, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        for i in range(lines):
            f.write(f"line {i}\n")
    return p


def _hash_content(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


# ── Part A: review_coverage detector (renamed to subjective_review) ──


class TestReviewCoverageNoCache:
    """No cache → all production files flagged as unreviewed."""

    def test_all_flagged(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module_a.py")
        f2 = _make_file(str(tmp_path), "module_b.py")
        entries, potential = detect_review_coverage(
            [f1, f2], zone_map=None, review_cache={}, lang_name="python"
        )
        assert potential == 2
        assert len(entries) == 2
        assert all(e["name"] == "unreviewed" for e in entries)
        assert all(e["confidence"] == "low" for e in entries)

    def test_small_files_skipped(self, tmp_path):
        small = _make_file(str(tmp_path), "tiny.py", lines=5)
        entries, potential = detect_review_coverage(
            [small], zone_map=None, review_cache={}, lang_name="python"
        )
        assert potential == 0
        assert len(entries) == 0

    def test_low_value_skipped(self, tmp_path):
        types_file = _make_file(str(tmp_path), "types.ts", lines=50)
        constants_file = _make_file(str(tmp_path), "constants.ts", lines=50)
        index_file = _make_file(str(tmp_path), "index.ts", lines=50)
        dts_file = _make_file(str(tmp_path), "api.d.ts", lines=50)
        entries, potential = detect_review_coverage(
            [types_file, constants_file, index_file, dts_file],
            zone_map=None, review_cache={}, lang_name="typescript"
        )
        assert potential == 0
        assert len(entries) == 0


class TestReviewCoverageZoneFiltering:
    """Zone filtering: only production files are flagged."""

    def test_test_zone_skipped(self, tmp_path):
        f = _make_file(str(tmp_path), "test_foo.py")
        zm = FakeZoneMap({f: FakeZone("test")})
        entries, potential = detect_review_coverage(
            [f], zone_map=zm, review_cache={}, lang_name="python"
        )
        assert potential == 0
        assert len(entries) == 0

    def test_generated_zone_skipped(self, tmp_path):
        f = _make_file(str(tmp_path), "gen.py")
        zm = FakeZoneMap({f: FakeZone("generated")})
        entries, potential = detect_review_coverage(
            [f], zone_map=zm, review_cache={}, lang_name="python"
        )
        assert potential == 0

    def test_vendor_zone_skipped(self, tmp_path):
        f = _make_file(str(tmp_path), "vendor.py")
        zm = FakeZoneMap({f: FakeZone("vendor")})
        entries, potential = detect_review_coverage(
            [f], zone_map=zm, review_cache={}, lang_name="python"
        )
        assert potential == 0

    def test_config_zone_skipped(self, tmp_path):
        f = _make_file(str(tmp_path), "config.py")
        zm = FakeZoneMap({f: FakeZone("config")})
        entries, potential = detect_review_coverage(
            [f], zone_map=zm, review_cache={}, lang_name="python"
        )
        assert potential == 0

    def test_production_zone_included(self, tmp_path):
        f = _make_file(str(tmp_path), "app.py")
        zm = FakeZoneMap({f: FakeZone("production")})
        entries, potential = detect_review_coverage(
            [f], zone_map=zm, review_cache={}, lang_name="python"
        )
        assert potential == 1
        assert len(entries) == 1


class TestReviewCoverageFreshCache:
    """Fresh cache → zero findings."""

    def test_fresh_no_findings(self, tmp_path):
        f = _make_file(str(tmp_path), "module.py")
        rpath = os.path.basename(f)  # relative path key
        content_hash = _hash_content(f)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {
            rpath: {
                "content_hash": content_hash,
                "reviewed_at": now,
                "finding_count": 0,
            }
        }
        with patch("desloppify.detectors.review_coverage.rel", return_value=rpath):
            entries, potential = detect_review_coverage(
                [f], zone_map=None, review_cache=cache, lang_name="python"
            )
        assert potential == 1
        assert len(entries) == 0


class TestReviewCoverageStaleCache:
    """Stale/changed/expired cache → correct findings."""

    def test_changed_file(self, tmp_path):
        f = _make_file(str(tmp_path), "module.py")
        rpath = os.path.basename(f)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {
            rpath: {
                "content_hash": "old_hash_doesnt_match",
                "reviewed_at": now,
                "finding_count": 0,
            }
        }
        with patch("desloppify.detectors.review_coverage.rel", return_value=rpath):
            entries, potential = detect_review_coverage(
                [f], zone_map=None, review_cache=cache, lang_name="python"
            )
        assert potential == 1
        assert len(entries) == 1
        assert entries[0]["name"] == "changed"
        assert entries[0]["confidence"] == "medium"

    def test_expired_review(self, tmp_path):
        f = _make_file(str(tmp_path), "module.py")
        rpath = os.path.basename(f)
        content_hash = _hash_content(f)
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(timespec="seconds")
        cache = {
            rpath: {
                "content_hash": content_hash,
                "reviewed_at": old_date,
                "finding_count": 0,
            }
        }
        with patch("desloppify.detectors.review_coverage.rel", return_value=rpath):
            entries, potential = detect_review_coverage(
                [f], zone_map=None, review_cache=cache, lang_name="python"
            )
        assert potential == 1
        assert len(entries) == 1
        assert entries[0]["name"] == "stale"
        assert entries[0]["confidence"] == "low"

    def test_no_reviewed_at(self, tmp_path):
        f = _make_file(str(tmp_path), "module.py")
        rpath = os.path.basename(f)
        content_hash = _hash_content(f)
        cache = {
            rpath: {
                "content_hash": content_hash,
                "reviewed_at": "",
                "finding_count": 0,
            }
        }
        with patch("desloppify.detectors.review_coverage.rel", return_value=rpath):
            entries, potential = detect_review_coverage(
                [f], zone_map=None, review_cache=cache, lang_name="python"
            )
        assert potential == 1
        assert len(entries) == 1
        assert entries[0]["name"] == "unreviewed"


# ── Part A: review findings protected from auto-resolve ──────────


class TestReviewProtectedFromAutoResolve:
    """The 'review' detector is import-only — never auto-resolved by scan."""

    def test_review_always_suspect(self):
        existing = {
            "review::file.py::naming_quality::foo": {
                "id": "review::file.py::naming_quality::foo",
                "detector": "review",
                "status": "open",
            }
        }
        # Even with 0 current findings, review should be suspect
        suspect = _find_suspect_detectors(existing, {}, force_resolve=False)
        assert "review" in suspect

    def test_review_suspect_even_with_ran_detectors(self):
        existing = {
            "review::file.py::naming_quality::foo": {
                "id": "review::file.py::naming_quality::foo",
                "detector": "review",
                "status": "open",
            }
        }
        # Even when ran_detectors is provided, review should be protected
        suspect = _find_suspect_detectors(
            existing, {}, force_resolve=False, ran_detectors={"smells", "unused"}
        )
        assert "review" in suspect

    def test_review_not_suspect_when_force_resolve(self):
        existing = {
            "review::file.py::naming_quality::foo": {
                "id": "review::file.py::naming_quality::foo",
                "detector": "review",
                "status": "open",
            }
        }
        suspect = _find_suspect_detectors(existing, {}, force_resolve=True)
        assert len(suspect) == 0


# ── Part B: ID collision fix ─────────────────────────────────────


class TestIDCollision:
    """Two findings same file+dimension+identifier get distinct IDs."""

    def test_distinct_ids_with_evidence_lines(self):
        findings_data = [
            {
                "file": "module.py",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name — rename to reconcileInvoice",
                "confidence": "high",
                "evidence_lines": [15, 32],
                "evidence": ["processData is vague"],
                "suggestion": "rename to reconcileInvoice",
            },
            {
                "file": "module.py",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Name/behavior mismatch — getX mutates state",
                "confidence": "medium",
                "evidence_lines": [45, 60],
                "evidence": ["processData mutates state"],
                "suggestion": "rename to updateInvoice",
            },
        ]
        state = _empty_state()
        diff = import_review_findings(findings_data, state, "python")

        # Both should be present with distinct IDs (content-hash disambiguated)
        ids = list(state["findings"].keys())
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_distinct_ids_without_evidence_lines(self):
        findings_data = [
            {
                "file": "module.py",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name",
                "confidence": "high",
                "evidence_lines": [],
                "evidence": [],
                "suggestion": "rename",
            },
            {
                "file": "module.py",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Different issue with processData",
                "confidence": "medium",
                "evidence_lines": [],
                "evidence": [],
                "suggestion": "refactor",
            },
        ]
        state = _empty_state()
        diff = import_review_findings(findings_data, state, "python")

        ids = list(state["findings"].keys())
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_same_finding_same_id(self):
        """Same evidence lines → same ID (stable across re-imports)."""
        findings_data = [
            {
                "file": "module.py",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name",
                "confidence": "high",
                "evidence_lines": [15],
                "evidence": [],
                "suggestion": "rename",
            },
        ]
        state = _empty_state()
        import_review_findings(findings_data, state, "python")
        id1 = list(state["findings"].keys())[0]

        # Re-import same finding
        state2 = _empty_state()
        import_review_findings(findings_data, state2, "python")
        id2 = list(state2["findings"].keys())[0]

        assert id1 == id2


# ── Part C: New subjective dimensions ────────────────────────────


class TestNewDimensions:
    """3 new dimensions present in DEFAULT_DIMENSIONS and DIMENSION_PROMPTS."""

    def test_abstraction_fitness_in_defaults(self):
        assert "abstraction_fitness" in DEFAULT_DIMENSIONS

    def test_error_consistency_in_defaults(self):
        assert "error_consistency" in DEFAULT_DIMENSIONS

    def test_type_safety_prompt(self):
        assert "type_safety" in DIMENSION_PROMPTS
        prompt = DIMENSION_PROMPTS["type_safety"]
        assert len(prompt["look_for"]) >= 3

    def test_cross_module_architecture_prompt(self):
        assert "cross_module_architecture" in DIMENSION_PROMPTS
        prompt = DIMENSION_PROMPTS["cross_module_architecture"]
        assert len(prompt["look_for"]) >= 3

    def test_new_dimensions_accepted_by_import(self):
        """New dimensions should not be rejected by import_review_findings validation."""
        for dim in ("type_safety", "cross_module_architecture", "abstraction_fitness"):
            findings_data = [{
                "file": "module.py",
                "dimension": dim,
                "identifier": "test_symbol",
                "summary": f"Test finding for {dim}",
                "confidence": "medium",
                "evidence_lines": [10],
                "evidence": ["test"],
                "suggestion": "fix it",
            }]
            state = _empty_state()
            diff = import_review_findings(findings_data, state, "python")
            assert len(state["findings"]) == 1, f"Finding for {dim} was rejected"


# ── Registry and scoring integration ─────────────────────────────


class TestRegistryIntegration:
    def test_subjective_review_in_registry(self):
        assert "subjective_review" in DETECTORS
        meta = DETECTORS["subjective_review"]
        assert meta.dimension == "Test health"
        assert meta.action_type == "manual_fix"

    def test_subjective_review_in_display_order(self):
        assert "subjective_review" in _DISPLAY_ORDER

    def test_subjective_review_in_scoring_dimensions(self):
        review_dim = next(d for d in DIMENSIONS if d.name == "Test health")
        assert "subjective_review" in review_dim.detectors

    def test_subjective_review_is_file_based(self):
        assert "subjective_review" in _FILE_BASED_DETECTORS


# ── Phase integration ────────────────────────────────────────────


class TestPhaseIntegration:
    def test_phase_registered_in_python(self):
        from desloppify.lang.python import PythonConfig
        cfg = PythonConfig()
        labels = [p.label for p in cfg.phases]
        assert "Subjective review" in labels

    def test_phase_registered_in_typescript(self):
        from desloppify.lang.typescript import TypeScriptConfig
        cfg = TypeScriptConfig()
        labels = [p.label for p in cfg.phases]
        assert "Subjective review" in labels

    def test_review_cache_field_exists(self):
        from desloppify.lang.base import LangConfig
        # _review_cache should be a dict by default
        from desloppify.lang.python import PythonConfig
        cfg = PythonConfig()
        assert hasattr(cfg, "_review_cache")
        assert isinstance(cfg._review_cache, dict)


# ── Part E: Holistic review staleness ─────────────────────────────


class TestHolisticStalenessInCoverage:
    """Holistic staleness entries emitted by detect_holistic_review_staleness."""

    def test_zero_files_emits_nothing(self):
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        entries = detect_holistic_review_staleness({}, total_files=0)
        assert entries == []

    def test_no_holistic_cache_emits_unreviewed(self):
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        entries = detect_holistic_review_staleness({}, total_files=50)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_unreviewed"
        assert entries[0]["file"] == ""
        assert entries[0]["tier"] == 4

    def test_fresh_holistic_emits_nothing(self):
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {"holistic": {"reviewed_at": now, "file_count_at_review": 50, "finding_count": 1}}
        entries = detect_holistic_review_staleness(cache, total_files=50)
        assert len(entries) == 0

    def test_stale_holistic_emits_stale(self):
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        cache = {"holistic": {"reviewed_at": old, "file_count_at_review": 50, "finding_count": 1}}
        entries = detect_holistic_review_staleness(cache, total_files=50)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"

    def test_drifted_file_count_emits_stale(self):
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {"holistic": {"reviewed_at": now, "file_count_at_review": 50, "finding_count": 1}}
        entries = detect_holistic_review_staleness(cache, total_files=100)  # 100% drift
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"
        assert entries[0]["detail"]["reason"] == "drift"


# ===========================================================================
# max_age_days=0 ("never") behavior
# ===========================================================================

class TestReviewNeverExpires:
    """When max_age_days=0, reviews should never be considered stale."""

    def test_per_file_stale_skipped_with_zero(self):
        """Old review with unchanged content should NOT be flagged when max_age_days=0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = _make_file(tmpdir, "src/widget.ts", lines=40)
            content = open(fp).read()
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # rel_path key must match what rel() returns for this filepath
            rpath = os.path.relpath(fp, os.getcwd())
            old_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
            cache = {rpath: {"content_hash": content_hash, "reviewed_at": old_date}}

            entries, _pot = detect_review_coverage(
                [fp], FakeZoneMap(), cache, "typescript", max_age_days=0)

            # Should have no stale entry
            stale = [e for e in entries if e["name"] == "stale"]
            assert len(stale) == 0

    def test_holistic_never_expires_with_zero(self):
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(timespec="seconds")
        cache = {"holistic": {"reviewed_at": old, "file_count_at_review": 50, "finding_count": 1}}
        entries = detect_holistic_review_staleness(cache, total_files=50, max_age_days=0)
        assert len(entries) == 0

    def test_holistic_unreviewed_still_flagged_with_zero(self):
        """Even with max_age_days=0, missing holistic review should still be flagged."""
        from desloppify.detectors.review_coverage import detect_holistic_review_staleness
        entries = detect_holistic_review_staleness({}, total_files=50, max_age_days=0)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_unreviewed"
