"""Direct tests for review/ submodules — selection, prepare, import_findings, remediation.

These tests import directly from the submodule files (not the __init__.py facade)
so the test_coverage detector recognizes them as directly tested.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def empty_state():
    from desloppify.state import _empty_state
    return _empty_state()


@pytest.fixture
def mock_lang():
    lang = MagicMock()
    lang.name = "typescript"
    lang._zone_map = None
    lang._dep_graph = None
    lang.file_finder = MagicMock(return_value=[])
    return lang


# ── selection.py tests ───────────────────────────────────────────

class TestHashFile:
    def test_hash_existing_file(self, tmp_path):
        from desloppify.review.selection import hash_file
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = hash_file(str(f))
        assert len(h) == 16
        expected = hashlib.sha256(b"hello").hexdigest()[:16]
        assert h == expected

    def test_hash_missing_file(self):
        from desloppify.review.selection import hash_file
        assert hash_file("/nonexistent/file.txt") == ""


class TestCountFreshStale:
    def test_count_fresh_empty(self, empty_state):
        from desloppify.review.selection import _count_fresh
        assert _count_fresh(empty_state, 30) == 0

    def test_count_fresh_with_recent(self, empty_state):
        from desloppify.review.selection import _count_fresh
        now = datetime.now(timezone.utc).isoformat()
        empty_state["review_cache"] = {
            "files": {"src/a.ts": {"reviewed_at": now}}
        }
        assert _count_fresh(empty_state, 30) == 1

    def test_count_fresh_with_old(self, empty_state):
        from desloppify.review.selection import _count_fresh
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        empty_state["review_cache"] = {
            "files": {"src/a.ts": {"reviewed_at": old}}
        }
        assert _count_fresh(empty_state, 30) == 0

    def test_count_stale(self, empty_state):
        from desloppify.review.selection import _count_stale
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        empty_state["review_cache"] = {
            "files": {
                "src/a.ts": {"reviewed_at": old},
                "src/b.ts": {"reviewed_at": now},
            }
        }
        assert _count_stale(empty_state, 30) == 1


class TestGetFileFindings:
    def test_empty_state(self, empty_state):
        from desloppify.review.selection import _get_file_findings
        assert _get_file_findings(empty_state, "src/foo.ts") == []

    def test_finds_matching(self, empty_state):
        from desloppify.review.selection import _get_file_findings
        empty_state["findings"] = {
            "f1": {"detector": "smells", "file": "src/foo.ts",
                   "summary": "bad smell", "status": "open", "id": "f1"},
            "f2": {"detector": "smells", "file": "src/bar.ts",
                   "summary": "other", "status": "open", "id": "f2"},
        }
        with patch("desloppify.review.selection.rel", side_effect=lambda x: x):
            results = _get_file_findings(empty_state, "src/foo.ts")
        assert len(results) == 1
        assert results[0]["summary"] == "bad smell"


class TestComputeReviewPriority:
    def test_tiny_file_filtered(self, mock_lang, empty_state):
        from desloppify.review.selection import _compute_review_priority
        with patch("desloppify.review.selection.rel", return_value="tiny.ts"), \
             patch("desloppify.review.selection.read_file_text", return_value="x\n" * 5):
            assert _compute_review_priority("tiny.ts", mock_lang, empty_state) == -1

    def test_normal_file_gets_score(self, mock_lang, empty_state):
        from desloppify.review.selection import _compute_review_priority
        content = "line\n" * 100
        with patch("desloppify.review.selection.rel", return_value="src/app.ts"), \
             patch("desloppify.review.selection.read_file_text", return_value=content):
            score = _compute_review_priority("src/app.ts", mock_lang, empty_state)
            assert score >= 0

    def test_low_value_penalty(self, mock_lang, empty_state):
        from desloppify.review.selection import _compute_review_priority
        content = "line\n" * 100
        with patch("desloppify.review.selection.rel") as mock_rel, \
             patch("desloppify.review.selection.read_file_text", return_value=content):
            mock_rel.return_value = "src/types.ts"
            low_score = _compute_review_priority("src/types.ts", mock_lang, empty_state)
            mock_rel.return_value = "src/app.ts"
            normal_score = _compute_review_priority("src/app.ts", mock_lang, empty_state)
            assert low_score < normal_score


class TestSelectFilesForReview:
    def test_empty_files(self, mock_lang, empty_state):
        from desloppify.review.selection import select_files_for_review
        result = select_files_for_review(mock_lang, Path("."), empty_state, files=[])
        assert result == []

    def test_skips_cached_fresh(self, mock_lang, empty_state):
        from desloppify.review.selection import select_files_for_review
        now = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.sha256(b"hello").hexdigest()[:16]
        empty_state["review_cache"] = {
            "files": {
                "src/a.ts": {
                    "content_hash": content_hash,
                    "reviewed_at": now,
                }
            }
        }
        with patch("desloppify.review.selection.rel", return_value="src/a.ts"), \
             patch("desloppify.review.selection.hash_file", return_value=content_hash), \
             patch("desloppify.review.selection._compute_review_priority", return_value=10):
            result = select_files_for_review(mock_lang, Path("."), empty_state,
                                              files=["src/a.ts"])
        assert result == []


class TestLowValueNames:
    def test_types_file(self):
        from desloppify.review.selection import LOW_VALUE_NAMES
        assert LOW_VALUE_NAMES.search("src/types.ts")

    def test_dts_file(self):
        from desloppify.review.selection import LOW_VALUE_NAMES
        assert LOW_VALUE_NAMES.search("src/foo.d.ts")

    def test_normal_file(self):
        from desloppify.review.selection import LOW_VALUE_NAMES
        assert not LOW_VALUE_NAMES.search("src/app.ts")


# ── prepare.py tests ────────────────────────────────────────────

class TestRelList:
    def test_set_input(self):
        from desloppify.review.prepare import _rel_list
        with patch("desloppify.review.prepare.rel", side_effect=lambda x: x):
            result = _rel_list({"b", "a", "c"})
            assert result == sorted(result)
            assert len(result) == 3

    def test_list_truncation(self):
        from desloppify.review.prepare import _rel_list
        with patch("desloppify.review.prepare.rel", side_effect=lambda x: x):
            result = _rel_list(list(range(20)))
            assert len(result) == 10


class TestBuildFileRequests:
    def test_basic(self, mock_lang, empty_state):
        from desloppify.review.prepare import _build_file_requests
        with patch("desloppify.review.prepare.read_file_text", return_value="line1\nline2"), \
             patch("desloppify.review.prepare.rel", return_value="src/a.ts"), \
             patch("desloppify.review.prepare._abs", side_effect=lambda x: x):
            result = _build_file_requests(["src/a.ts"], mock_lang, empty_state)
        assert len(result) == 1
        assert result[0]["file"] == "src/a.ts"
        assert result[0]["loc"] == 2

    def test_skips_unreadable(self, mock_lang, empty_state):
        from desloppify.review.prepare import _build_file_requests
        with patch("desloppify.review.prepare.read_file_text", return_value=None), \
             patch("desloppify.review.prepare._abs", side_effect=lambda x: x):
            result = _build_file_requests(["missing.ts"], mock_lang, empty_state)
        assert result == []


class TestBuildInvestigationBatches:
    def test_empty_context(self, mock_lang):
        from desloppify.review.prepare import _build_investigation_batches
        result = _build_investigation_batches({}, mock_lang)
        assert result == []  # No files -> no batches

    def test_batches_with_data(self, mock_lang):
        from desloppify.review.prepare import _build_investigation_batches
        ctx = {
            "architecture": {"god_modules": [{"file": "src/big.ts"}]},
            "coupling": {"module_level_io": []},
            "conventions": {},
            "abstractions": {},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
        }
        result = _build_investigation_batches(ctx, mock_lang)
        assert len(result) >= 1
        assert result[0]["name"] == "Architecture & Coupling"
        assert "src/big.ts" in result[0]["files_to_read"]


class TestPrepareReview:
    def test_returns_expected_keys(self, mock_lang, empty_state):
        from desloppify.review.prepare import prepare_review
        with patch("desloppify.review.prepare.build_review_context") as mock_ctx, \
             patch("desloppify.review.prepare.select_files_for_review", return_value=[]), \
             patch("desloppify.review.prepare._build_file_requests", return_value=[]), \
             patch("desloppify.review.prepare._serialize_context", return_value={}), \
             patch("desloppify.review.prepare._count_fresh", return_value=0), \
             patch("desloppify.review.prepare._count_stale", return_value=0):
            mock_ctx.return_value = MagicMock()
            result = prepare_review(Path("."), mock_lang, empty_state, files=[])
        assert "command" in result
        assert result["command"] == "review"
        assert "dimensions" in result
        assert "files" in result
        assert "cache_status" in result


class TestPrepareHolisticReview:
    def test_returns_expected_keys(self, mock_lang, empty_state):
        from desloppify.review.prepare import prepare_holistic_review
        with patch("desloppify.review.prepare.build_review_context") as mock_review_ctx, \
             patch("desloppify.review.prepare.build_holistic_context", return_value={}), \
             patch("desloppify.review.prepare._serialize_context", return_value={}), \
             patch("desloppify.review.prepare._build_investigation_batches", return_value=[]):
            mock_review_ctx.return_value = MagicMock()
            result = prepare_holistic_review(Path("."), mock_lang, empty_state, files=[])
        assert result["command"] == "review"
        assert result["mode"] == "holistic"
        assert "investigation_batches" in result
        assert "workflow" in result


# ── import_findings.py tests ──────────────────────────────────────

class TestExtractFindingsAndAssessments:
    def test_list_format(self):
        from desloppify.review.import_findings import _extract_findings_and_assessments
        data = [{"file": "a.ts", "summary": "x"}]
        findings, assessments = _extract_findings_and_assessments(data)
        assert findings == data
        assert assessments is None

    def test_dict_format(self):
        from desloppify.review.import_findings import _extract_findings_and_assessments
        data = {
            "findings": [{"file": "a.ts"}],
            "assessments": {"naming": 80},
        }
        findings, assessments = _extract_findings_and_assessments(data)
        assert len(findings) == 1
        assert assessments == {"naming": 80}

    def test_invalid_type(self):
        from desloppify.review.import_findings import _extract_findings_and_assessments
        findings, assessments = _extract_findings_and_assessments("bad")
        assert findings == []
        assert assessments is None


class TestStoreAssessments:
    def test_stores_basic(self, empty_state):
        from desloppify.review.import_findings import _store_assessments
        _store_assessments(empty_state, {"naming": 80}, "per_file")
        assert empty_state["subjective_assessments"]["naming"]["score"] == 80
        assert empty_state["subjective_assessments"]["naming"]["source"] == "per_file"

    def test_holistic_overwrites_per_file(self, empty_state):
        from desloppify.review.import_findings import _store_assessments
        _store_assessments(empty_state, {"naming": 60}, "per_file")
        _store_assessments(empty_state, {"naming": 90}, "holistic")
        assert empty_state["subjective_assessments"]["naming"]["score"] == 90

    def test_per_file_no_overwrite_holistic(self, empty_state):
        from desloppify.review.import_findings import _store_assessments
        _store_assessments(empty_state, {"naming": 90}, "holistic")
        _store_assessments(empty_state, {"naming": 60}, "per_file")
        assert empty_state["subjective_assessments"]["naming"]["score"] == 90

    def test_clamps_score(self, empty_state):
        from desloppify.review.import_findings import _store_assessments
        _store_assessments(empty_state, {"naming": 200}, "per_file")
        assert empty_state["subjective_assessments"]["naming"]["score"] == 100
        _store_assessments(empty_state, {"naming": -50}, "holistic")
        assert empty_state["subjective_assessments"]["naming"]["score"] == 0

    def test_dict_value_format(self, empty_state):
        from desloppify.review.import_findings import _store_assessments
        _store_assessments(empty_state, {"naming": {"score": 75, "extra": "data"}}, "per_file")
        assert empty_state["subjective_assessments"]["naming"]["score"] == 75


class TestImportReviewFindings:
    def test_valid_finding(self, empty_state):
        from desloppify.review.import_findings import import_review_findings
        data = [{
            "file": "src/foo.ts",
            "dimension": "naming_quality",
            "identifier": "bad_names",
            "summary": "Poor variable names",
            "confidence": "medium",
        }]
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff.get("skipped", 0) == 0
        # Finding should be in state
        assert any(f.get("detector") == "review"
                   for f in empty_state.get("findings", {}).values())

    def test_skips_missing_fields(self, empty_state):
        from desloppify.review.import_findings import import_review_findings
        data = [{"file": "src/foo.ts"}]  # Missing dimension, identifier, etc.
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff.get("skipped", 0) == 1

    def test_skips_invalid_dimension(self, empty_state):
        from desloppify.review.import_findings import import_review_findings
        data = [{
            "file": "src/foo.ts",
            "dimension": "nonexistent_dimension",
            "identifier": "x",
            "summary": "x",
            "confidence": "high",
        }]
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff.get("skipped", 0) == 1

    def test_normalizes_invalid_confidence(self, empty_state):
        from desloppify.review.import_findings import import_review_findings
        data = [{
            "file": "src/foo.ts",
            "dimension": "naming_quality",
            "identifier": "x",
            "summary": "test",
            "confidence": "INVALID",
        }]
        diff = import_review_findings(data, empty_state, "typescript")
        findings = list(empty_state.get("findings", {}).values())
        review_findings = [f for f in findings if f.get("detector") == "review"]
        assert len(review_findings) == 1
        assert review_findings[0]["confidence"] == "low"

    def test_auto_resolves_missing_findings(self, empty_state):
        from desloppify.review.import_findings import import_review_findings
        from desloppify.state import make_finding
        # Pre-existing review finding for src/foo.ts
        old = make_finding(
            detector="review", file="src/foo.ts",
            name="naming_quality::old::abc12345",
            tier=3, confidence="medium", summary="old finding",
            detail={"dimension": "naming_quality"},
        )
        old["lang"] = "typescript"
        empty_state["findings"][old["id"]] = old
        # Import new findings for same file, but different finding
        data = [{
            "file": "src/foo.ts",
            "dimension": "naming_quality",
            "identifier": "new_issue",
            "summary": "New finding",
            "confidence": "high",
        }]
        diff = import_review_findings(data, empty_state, "typescript")
        # Old finding should be auto-resolved
        assert empty_state["findings"][old["id"]]["status"] == "auto_resolved"


class TestImportHolisticFindings:
    def test_valid_holistic(self, empty_state):
        from desloppify.review.import_findings import import_holistic_findings
        data = [{
            "dimension": "cross_module_architecture",
            "identifier": "god_module",
            "summary": "Too many responsibilities",
            "confidence": "high",
            "related_files": ["src/big.ts"],
        }]
        diff = import_holistic_findings(data, empty_state, "typescript")
        findings = list(empty_state.get("findings", {}).values())
        holistic = [f for f in findings
                    if f.get("detail", {}).get("holistic")]
        assert len(holistic) == 1

    def test_skips_invalid(self, empty_state):
        from desloppify.review.import_findings import import_holistic_findings
        data = [{"summary": "missing dimension"}]
        diff = import_holistic_findings(data, empty_state, "typescript")
        assert diff.get("skipped", 0) == 1


class TestUpdateReviewCache:
    def test_updates_cache(self, empty_state):
        from desloppify.review.import_findings import _update_review_cache
        with patch("desloppify.review.import_findings.PROJECT_ROOT", Path("/fake")), \
             patch("desloppify.review.import_findings.utc_now", return_value="2026-01-01T00:00:00+00:00"):
            with patch.object(Path, "exists", return_value=False):
                _update_review_cache(empty_state, [{"file": "src/a.ts"}])
        cache = empty_state.get("review_cache", {}).get("files", {})
        assert "src/a.ts" in cache
        assert cache["src/a.ts"]["reviewed_at"] == "2026-01-01T00:00:00+00:00"


class TestUpdateHolisticReviewCache:
    def test_updates_holistic_cache(self, empty_state):
        from desloppify.review.import_findings import _update_holistic_review_cache
        with patch("desloppify.review.import_findings.utc_now", return_value="2026-02-01"):
            _update_holistic_review_cache(empty_state, [])
        rc = empty_state.get("review_cache", {})
        assert "holistic" in rc
        assert rc["holistic"]["reviewed_at"] == "2026-02-01"


# ── remediation.py tests ─────────────────────────────────────────

class TestEmptyPlan:
    def test_contains_score(self, empty_state):
        from desloppify.review.remediation import _empty_plan
        empty_state["objective_score"] = 88.5
        result = _empty_plan(empty_state, "typescript")
        assert "88.5" in result
        assert "No open holistic findings" in result


class TestGenerateRemediationPlan:
    def test_empty_findings(self, empty_state):
        from desloppify.review.remediation import generate_remediation_plan
        result = generate_remediation_plan(empty_state, "typescript")
        assert "No open holistic findings" in result

    def test_with_findings(self, empty_state):
        from desloppify.review.remediation import generate_remediation_plan
        from desloppify.state import make_finding
        f = make_finding(
            detector="review", file="",
            name="holistic::cross_module_architecture::god::abc12345",
            tier=3, confidence="high",
            summary="God module detected",
            detail={
                "holistic": True,
                "dimension": "cross_module_architecture",
                "related_files": ["src/big.ts"],
                "evidence": ["Too many exports"],
                "suggestion": "Split the module",
                "reasoning": "Reduces coupling",
            },
        )
        empty_state["findings"][f["id"]] = f
        empty_state["objective_score"] = 85.0
        empty_state["objective_strict"] = 84.0
        empty_state["potentials"] = {"typescript": {"review": 50}}
        result = generate_remediation_plan(empty_state, "typescript")
        assert "God module detected" in result
        assert "Priority 1" in result
        assert "Evidence" in result
        assert "Suggested fix" in result

    def test_writes_to_file(self, empty_state, tmp_path):
        from desloppify.review.remediation import generate_remediation_plan
        out = tmp_path / "plan.md"
        with patch("desloppify.utils.safe_write_text") as mock_write:
            generate_remediation_plan(empty_state, "python", output_path=out)
            mock_write.assert_called_once()
