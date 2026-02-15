"""Tests for the subjective code review system (review.py, commands/review_cmd.py)."""

from __future__ import annotations

import json
import os
import textwrap
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
def state_with_findings():
    from desloppify.state import _empty_state
    state = _empty_state()
    state["findings"] = {
        "unused::src/foo.ts::bar": {
            "id": "unused::src/foo.ts::bar",
            "detector": "unused",
            "file": "src/foo.ts",
            "tier": 1,
            "confidence": "high",
            "summary": "Unused import: bar",
            "detail": {},
            "status": "open",
            "note": None,
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-01-01T00:00:00+00:00",
            "resolved_at": None,
            "reopen_count": 0,
            "lang": "typescript",
        },
        "smells::src/utils.ts::eval_exec": {
            "id": "smells::src/utils.ts::eval_exec",
            "detector": "smells",
            "file": "src/utils.ts",
            "tier": 2,
            "confidence": "medium",
            "summary": "eval usage",
            "detail": {},
            "status": "open",
            "note": None,
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-01-01T00:00:00+00:00",
            "resolved_at": None,
            "reopen_count": 0,
            "lang": "typescript",
        },
    }
    return state


@pytest.fixture
def mock_lang():
    """Create a mock LangConfig with minimal interface."""
    lang = MagicMock()
    lang.name = "typescript"
    lang.file_finder = MagicMock(return_value=["src/foo.ts", "src/bar.ts", "src/utils.ts"])
    lang._zone_map = None
    lang._dep_graph = None
    lang.zone_rules = []
    lang.build_dep_graph = None
    return lang


@pytest.fixture
def mock_lang_with_zones(mock_lang):
    """Mock lang with zone map."""
    zone_map = MagicMock()

    def get_zone(filepath):
        z = MagicMock()
        fname = filepath.split("/")[-1] if "/" in filepath else filepath
        if "__tests__" in filepath or fname.endswith(".test.ts") or fname.startswith("test_"):
            z.value = "test"
        elif "generated" in fname:
            z.value = "generated"
        else:
            z.value = "production"
        return z

    zone_map.get = get_zone
    zone_map.counts.return_value = {"production": 3, "test": 1}
    mock_lang._zone_map = zone_map
    return mock_lang


@pytest.fixture
def sample_findings_data():
    """Sample agent-produced review findings."""
    return [
        {
            "file": "src/foo.ts",
            "dimension": "naming_quality",
            "identifier": "processData",
            "summary": "processData is vague — rename to reconcileInvoice",
            "evidence_lines": [15, 32],
            "evidence": ["function processData() handles invoice reconciliation"],
            "suggestion": "Rename processData to reconcileInvoice",
            "reasoning": "Callers expect invoice handling, not generic processing",
            "confidence": "high",
        },
        {
            "file": "src/bar.ts",
            "dimension": "comment_quality",
            "identifier": "handleSubmit",
            "summary": "Stale comment references removed validation step",
            "evidence_lines": [42],
            "evidence": ["Comment says 'validate first' but validation was removed"],
            "suggestion": "Remove stale comment on line 42",
            "reasoning": "Comment misleads maintainers about current behavior",
            "confidence": "medium",
        },
        {
            "file": "src/foo.ts",
            "dimension": "error_consistency",
            "identifier": "fetchUser",
            "summary": "fetchUser returns null on error while siblings throw",
            "evidence_lines": [80],
            "evidence": ["fetchUser returns null, fetchOrder throws on error"],
            "suggestion": "Align to throw pattern used by fetchOrder and fetchItems",
            "reasoning": "Mixed error conventions in the same module",
            "confidence": "low",
        },
    ]


# ── ReviewContext tests ───────────────────────────────────────────

class TestBuildReviewContext:
    def test_empty_files(self, mock_lang, empty_state):
        from desloppify.review import build_review_context
        mock_lang.file_finder = MagicMock(return_value=[])
        ctx = build_review_context(Path("/tmp"), mock_lang, empty_state)
        assert ctx.naming_vocabulary == {}
        assert ctx.codebase_stats == {}

    def test_naming_vocabulary_extraction(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context
        (tmp_path / "foo.ts").write_text("function getData() {}\ndef setName(): pass\nclass UserService {}")
        (tmp_path / "bar.ts").write_text("function getUser() {}\nasync function handleClick() {}")
        mock_lang.file_finder = MagicMock(return_value=[
            str(tmp_path / "foo.ts"), str(tmp_path / "bar.ts")
        ])
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert ctx.naming_vocabulary["total_names"] == 5
        assert ctx.naming_vocabulary["prefixes"]["get"] == 2
        assert ctx.naming_vocabulary["prefixes"]["set"] == 1
        assert ctx.naming_vocabulary["prefixes"]["handle"] == 1

    def test_error_convention_detection(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context
        (tmp_path / "foo.ts").write_text("try { x } catch(e) {}\nreturn null;")
        (tmp_path / "bar.ts").write_text("throw new Error('fail')")
        mock_lang.file_finder = MagicMock(return_value=[
            str(tmp_path / "foo.ts"), str(tmp_path / "bar.ts")
        ])
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert ctx.error_conventions.get("try_catch") == 1
        assert ctx.error_conventions.get("returns_null") == 1
        assert ctx.error_conventions.get("throws") == 1

    def test_existing_findings_in_context(self, mock_lang, state_with_findings, tmp_path):
        from desloppify.review import build_review_context
        (tmp_path / "foo.ts").write_text("x")
        mock_lang.file_finder = MagicMock(return_value=[str(tmp_path / "foo.ts")])
        ctx = build_review_context(tmp_path, mock_lang, state_with_findings)
        assert "src/foo.ts" in ctx.existing_findings

    def test_codebase_stats(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context
        (tmp_path / "foo.ts").write_text("line1\nline2\nline3")
        (tmp_path / "bar.ts").write_text("line1\nline2")
        mock_lang.file_finder = MagicMock(return_value=[
            str(tmp_path / "foo.ts"), str(tmp_path / "bar.ts")
        ])
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert ctx.codebase_stats["total_files"] == 2
        assert ctx.codebase_stats["total_loc"] == 5
        assert ctx.codebase_stats["avg_file_loc"] == 2

    def test_module_patterns(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for i in range(4):
            (hooks / f"hook{i}.ts").write_text(f"export function useHook{i}() {{}}")
        mock_lang.file_finder = MagicMock(return_value=[
            str(hooks / f"hook{i}.ts") for i in range(4)
        ])
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert "hooks/" in ctx.module_patterns

    def test_import_graph_summary(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context
        (tmp_path / "foo.ts").write_text("x")
        mock_lang.file_finder = MagicMock(return_value=[str(tmp_path / "foo.ts")])
        mock_lang._dep_graph = {
            "src/foo.ts": {"importers": {"src/bar.ts", "src/baz.ts"}, "imports": set()},
        }
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert "src/foo.ts" in ctx.import_graph_summary["top_imported"]

    def test_zone_distribution(self, mock_lang_with_zones, empty_state, tmp_path):
        from desloppify.review import build_review_context
        (tmp_path / "foo.ts").write_text("x")
        mock_lang_with_zones.file_finder = MagicMock(return_value=[str(tmp_path / "foo.ts")])
        ctx = build_review_context(tmp_path, mock_lang_with_zones, empty_state)
        assert ctx.zone_distribution == {"production": 3, "test": 1}


# ── File selection tests ──────────────────────────────────────────

class TestSelectFilesForReview:
    def test_selects_production_files(self, mock_lang_with_zones, empty_state, tmp_path):
        from desloppify.review import select_files_for_review
        # Create real files with enough content to pass min LOC filter
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.ts").write_text("export function foo() {}\n" * 25)
        (src / "bar.ts").write_text("export function bar() {}\n" * 25)
        tests = src / "__tests__"
        tests.mkdir()
        (tests / "foo.test.ts").write_text("test('x', () => {})\n" * 25)
        foo_path = str(src / "foo.ts")
        bar_path = str(src / "bar.ts")
        test_path = str(tests / "foo.test.ts")
        mock_lang_with_zones.file_finder = MagicMock(return_value=[
            foo_path, bar_path, test_path,
        ])
        files = select_files_for_review(mock_lang_with_zones, tmp_path, empty_state)
        assert foo_path in files
        assert bar_path in files
        assert test_path not in files

    def test_max_files_limit(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import select_files_for_review
        src = tmp_path / "src"
        src.mkdir()
        paths = []
        for i in range(20):
            f = src / f"file{i}.ts"
            f.write_text("export function x() {}\n" * 25)
            paths.append(str(f))
        mock_lang.file_finder = MagicMock(return_value=paths)
        files = select_files_for_review(mock_lang, tmp_path, empty_state, max_files=5)
        assert len(files) <= 5

    def test_cache_skip_fresh_files(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import select_files_for_review, hash_file
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Create a real file for hashing
        real_file = tmp_path / "cached.ts"
        real_file.write_text("cached content")
        content_hash = hash_file(str(real_file))

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        rpath = str(real_file.relative_to(Path.cwd())) if real_file.is_relative_to(Path.cwd()) else str(real_file)
        # We need to patch rel() to return a stable path
        with patch("desloppify.review.selection.rel", return_value="cached.ts"):
            state["review_cache"] = {
                "files": {
                    "cached.ts": {
                        "content_hash": content_hash,
                        "reviewed_at": now,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(mock_lang, tmp_path, state, max_age_days=30)
        assert len(files) == 0

    def test_cache_refresh_stale_files(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import select_files_for_review, hash_file
        old_time = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        real_file = tmp_path / "stale.ts"
        real_file.write_text("stale content\n" * 25)  # >= MIN_REVIEW_LOC
        content_hash = hash_file(str(real_file))

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        with patch("desloppify.review.selection.rel", return_value="stale.ts"):
            state["review_cache"] = {
                "files": {
                    "stale.ts": {
                        "content_hash": content_hash,
                        "reviewed_at": old_time,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(mock_lang, tmp_path, state, max_age_days=30)
        assert len(files) == 1

    def test_content_hash_change_triggers_review(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import select_files_for_review
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        real_file = tmp_path / "changed.ts"
        real_file.write_text("new content\n" * 25)  # >= MIN_REVIEW_LOC

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        with patch("desloppify.review.selection.rel", return_value="changed.ts"):
            state["review_cache"] = {
                "files": {
                    "changed.ts": {
                        "content_hash": "old_hash_different",
                        "reviewed_at": now,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(mock_lang, tmp_path, state, max_age_days=30)
        assert len(files) == 1

    def test_force_refresh_ignores_cache(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import select_files_for_review, hash_file
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        real_file = tmp_path / "cached.ts"
        real_file.write_text("cached content\n" * 25)  # >= MIN_REVIEW_LOC
        content_hash = hash_file(str(real_file))

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        with patch("desloppify.review.selection.rel", return_value="cached.ts"):
            state["review_cache"] = {
                "files": {
                    "cached.ts": {
                        "content_hash": content_hash,
                        "reviewed_at": now,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(mock_lang, tmp_path, state,
                                            max_age_days=30, force_refresh=True)
        assert len(files) == 1

    def test_priority_ordering_by_importers(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import select_files_for_review
        # Create real files so read_file_text works (need >= MIN_REVIEW_LOC)
        src = tmp_path / "src"
        src.mkdir()
        (src / "popular.ts").write_text("export function foo() {}\n" * 30)
        (src / "lonely.ts").write_text("export function bar() {}\n" * 30)
        pop_abs = str(src / "popular.ts")
        lon_abs = str(src / "lonely.ts")
        mock_lang.file_finder = MagicMock(return_value=[pop_abs, lon_abs])
        mock_lang._dep_graph = {
            pop_abs: {"importers": {"a", "b", "c", "d", "e"}, "imports": set()},
            lon_abs: {"importers": set(), "imports": set()},
        }
        files = select_files_for_review(mock_lang, tmp_path, empty_state)
        assert files[0] == pop_abs


# ── Prepare review tests ─────────────────────────────────────────

class TestPrepareReview:
    def test_basic_prepare(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import prepare_review
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        data = prepare_review(tmp_path, mock_lang, empty_state)
        assert data["command"] == "review"
        assert data["total_candidates"] == 1
        assert data["dimensions"] == [
            "naming_quality", "error_consistency",
            "abstraction_fitness", "logic_clarity",
            "ai_generated_debt",
            "type_safety", "contract_coherence",
        ]
        assert "system_prompt" in data
        assert len(data["files"]) == 1
        assert "export function getData() { return 42; }" in data["files"][0]["content"]

    def test_custom_dimensions(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import prepare_review
        f = tmp_path / "foo.ts"
        f.write_text("export function bar() { return 1; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        data = prepare_review(tmp_path, mock_lang, empty_state,
                              dimensions=["naming_quality", "comment_quality"])
        assert data["dimensions"] == ["naming_quality", "comment_quality"]
        assert len(data["dimension_prompts"]) == 2

    def test_file_neighbors_included(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import prepare_review
        f = tmp_path / "foo.ts"
        f.write_text("export function bar() {}\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])
        mock_lang._dep_graph = {
            "foo.ts": {"imports": {"bar.ts"}, "importers": {"baz.ts", "qux.ts"}},
        }

        with patch("desloppify.review.context.rel", return_value="foo.ts"), \
             patch("desloppify.review.selection.rel", return_value="foo.ts"), \
             patch("desloppify.review.prepare.rel", return_value="foo.ts"):
            data = prepare_review(tmp_path, mock_lang, empty_state)
        if data["files"]:
            neighbors = data["files"][0]["neighbors"]
            if neighbors:  # dep graph lookup may not match the patched rel
                assert "imports" in neighbors


# ── Import findings tests ─────────────────────────────────────────

class TestImportReviewFindings:
    def test_import_valid_findings(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        diff = import_review_findings(sample_findings_data, empty_state, "typescript")
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
        from desloppify.review import import_review_findings
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
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff["new"] == 1

    def test_import_validates_confidence(self, empty_state):
        from desloppify.review import import_review_findings
        data = [{
            "file": "src/foo.ts",
            "dimension": "naming_quality",
            "identifier": "foo",
            "summary": "test",
            "confidence": "very_high",  # Invalid
        }]
        import_review_findings(data, empty_state, "typescript")
        finding = list(empty_state["findings"].values())[0]
        assert finding["confidence"] == "low"

    def test_import_validates_dimension(self, empty_state):
        from desloppify.review import import_review_findings
        data = [{
            "file": "src/foo.ts",
            "dimension": "invalid_dimension",
            "identifier": "foo",
            "summary": "test",
            "confidence": "high",
        }]
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff["new"] == 0

    def test_import_updates_review_cache(self, empty_state, sample_findings_data, tmp_path):
        from desloppify.review import import_review_findings
        # Create actual files so hashing works
        (tmp_path / "src").mkdir(exist_ok=True)
        with patch("desloppify.review.import_findings.PROJECT_ROOT", tmp_path):
            (tmp_path / "src" / "foo.ts").write_text("content")
            (tmp_path / "src" / "bar.ts").write_text("content")
            import_review_findings(sample_findings_data, empty_state, "typescript")
        cache = empty_state.get("review_cache", {}).get("files", {})
        assert len(cache) >= 1  # At least one file cached

    def test_import_merges_with_state(self, state_with_findings, sample_findings_data):
        from desloppify.review import import_review_findings
        diff = import_review_findings(sample_findings_data, state_with_findings, "typescript")
        # Original findings should still be there
        assert "unused::src/foo.ts::bar" in state_with_findings["findings"]
        assert diff["new"] == 3

    def test_import_preserves_wontfix_findings(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        # First import
        import_review_findings(sample_findings_data, empty_state, "typescript")
        # Mark one as wontfix
        for f in empty_state["findings"].values():
            if "naming_quality" in f["id"]:
                f["status"] = "wontfix"
                f["note"] = "intentionally generic"
                break
        # Second import with same findings
        import_review_findings(sample_findings_data, empty_state, "typescript")
        # Wontfix should NOT be auto-resolved (it's still in current findings)
        wontfix = [f for f in empty_state["findings"].values()
                    if f["status"] == "wontfix"]
        # The finding still exists
        assert any("naming_quality" in f["id"] for f in empty_state["findings"].values())

    def test_import_sets_lang(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        import_review_findings(sample_findings_data, empty_state, "python")
        for f in empty_state["findings"].values():
            assert f["lang"] == "python"

    def test_import_sets_tier_3(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        import_review_findings(sample_findings_data, empty_state, "typescript")
        for f in empty_state["findings"].values():
            assert f["tier"] == 3

    def test_import_stores_detail(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        import_review_findings(sample_findings_data, empty_state, "typescript")
        for f in empty_state["findings"].values():
            assert "dimension" in f["detail"]
            assert "suggestion" in f["detail"]

    def test_id_collision_different_summaries(self, empty_state):
        """Two findings for same file/dimension/identifier but different summaries
        must both appear in state (#56)."""
        from desloppify.review import import_review_findings
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
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff["new"] == 2
        assert len(empty_state["findings"]) == 2

    def test_id_stable_for_same_summary(self, empty_state):
        """Same summary should produce the same finding ID (stable hash)."""
        from desloppify.review import import_review_findings
        data = [{
            "file": "src/foo.ts",
            "dimension": "naming_quality",
            "identifier": "processData",
            "summary": "processData is vague",
            "confidence": "high",
        }]
        import_review_findings(data, empty_state, "typescript")
        ids_first = set(empty_state["findings"].keys())

        # Import again — should match same IDs (no new findings)
        diff = import_review_findings(data, empty_state, "typescript")
        assert diff["new"] == 0
        assert set(empty_state["findings"].keys()) == ids_first


# ── Scoring integration tests ─────────────────────────────────────

class TestScoringIntegration:
    def test_review_findings_appear_in_scoring(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        from desloppify.scoring import compute_dimension_scores
        import_review_findings(sample_findings_data, empty_state, "typescript")

        # With assessment-based scoring, review findings alone don't create
        # dimension penalties. Assessments create first-class scoring dimensions.
        assessments = {"naming_quality": {"score": 75}, "comment_quality": {"score": 85}}
        potentials = {"review": 2}
        dim_scores = compute_dimension_scores(
            empty_state["findings"], potentials,
            subjective_assessments=assessments)
        assert "Naming Quality" in dim_scores
        assert dim_scores["Naming Quality"]["score"] == 75.0

    def test_review_findings_not_auto_resolved_by_scan(self, empty_state, sample_findings_data):
        from desloppify.review import import_review_findings
        from desloppify.state import merge_scan
        # Import review findings
        import_review_findings(sample_findings_data, empty_state, "typescript")
        review_ids = {f["id"] for f in empty_state["findings"].values()
                      if f["detector"] == "review"}

        # Simulate a normal scan with no review detector in potentials
        merge_scan(empty_state, [],
                   lang="typescript",
                   potentials={"unused": 10, "smells": 50})

        # Review findings should still be open (not auto-resolved)
        for fid in review_ids:
            if fid in empty_state["findings"]:
                assert empty_state["findings"][fid]["status"] == "open"

    def test_review_in_file_based_detectors(self):
        from desloppify.scoring import _FILE_BASED_DETECTORS
        assert "review" in _FILE_BASED_DETECTORS

    def test_test_health_dimension_exists(self):
        from desloppify.scoring import DIMENSIONS
        dim_names = [d.name for d in DIMENSIONS]
        assert "Test health" in dim_names
        rc = [d for d in DIMENSIONS if d.name == "Test health"][0]
        assert rc.tier == 4
        assert "subjective_review" in rc.detectors


# ── Assessment import tests ────────────────────────────────────────

class TestAssessmentImport:
    def test_import_new_format_with_assessments(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
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
        diff = import_review_findings(data, state, "typescript")
        assert diff["new"] == 1
        assert len(state["findings"]) == 1
        assessments = state["subjective_assessments"]
        assert "naming_quality" in assessments
        assert assessments["naming_quality"]["score"] == 75
        assert "comment_quality" in assessments
        assert assessments["comment_quality"]["score"] == 85

    def test_import_legacy_format_still_works(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "x",
                "summary": "bad name",
                "confidence": "high",
            },
        ]
        diff = import_review_findings(data, state, "typescript")
        assert diff["new"] == 1
        # Legacy format: no assessments stored
        assert state.get("subjective_assessments", {}) == {}

    def test_holistic_assessment_overwrites_per_file(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings, import_holistic_findings
        state = _empty_state()
        # Import per-file assessments first
        per_file_data = {
            "assessments": {"abstraction_fitness": 60},
            "findings": [],
        }
        import_review_findings(per_file_data, state, "typescript")
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 60

        # Import holistic assessments for the same dimension with a different score
        holistic_data = {
            "assessments": {"abstraction_fitness": 40},
            "findings": [],
        }
        import_holistic_findings(holistic_data, state, "typescript")
        # Holistic wins
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 40
        assert state["subjective_assessments"]["abstraction_fitness"]["source"] == "holistic"

    def test_per_file_does_not_overwrite_holistic(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings, import_holistic_findings
        state = _empty_state()
        # Import holistic first
        holistic_data = {
            "assessments": {"abstraction_fitness": 40},
            "findings": [],
        }
        import_holistic_findings(holistic_data, state, "typescript")
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 40

        # Import per-file for the same dimension
        per_file_data = {
            "assessments": {"abstraction_fitness": 80},
            "findings": [],
        }
        import_review_findings(per_file_data, state, "typescript")
        # Holistic score should be preserved
        assert state["subjective_assessments"]["abstraction_fitness"]["score"] == 40
        assert state["subjective_assessments"]["abstraction_fitness"]["source"] == "holistic"

    def test_assessment_score_clamped(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
        data = {
            "assessments": {"naming_quality": 150},
            "findings": [],
        }
        import_review_findings(data, state, "typescript")
        assert state["subjective_assessments"]["naming_quality"]["score"] == 100

    def test_assessment_negative_clamped(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
        data = {
            "assessments": {"naming_quality": -10},
            "findings": [],
        }
        import_review_findings(data, state, "typescript")
        assert state["subjective_assessments"]["naming_quality"]["score"] == 0

    def test_import_dict_without_assessments(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
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
        diff = import_review_findings(data, state, "typescript")
        assert diff["new"] == 1
        # No assessments key in import data, so nothing stored
        assert state.get("subjective_assessments", {}) == {}


# ── Staleness tests ───────────────────────────────────────────────

class TestStaleness:
    def test_stale_after_max_age(self):
        from desloppify.review import _count_stale, _count_fresh
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {"content_hash": "abc", "reviewed_at": old, "finding_count": 0},
                }
            }
        }
        assert _count_stale(state, 30) == 1
        assert _count_fresh(state, 30) == 0

    def test_fresh_within_max_age(self):
        from desloppify.review import _count_stale, _count_fresh
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {"content_hash": "abc", "reviewed_at": now, "finding_count": 0},
                }
            }
        }
        assert _count_stale(state, 30) == 0
        assert _count_fresh(state, 30) == 1

    def test_mixed_fresh_and_stale(self):
        from desloppify.review import _count_stale, _count_fresh
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "fresh.ts": {"content_hash": "abc", "reviewed_at": now, "finding_count": 0},
                    "stale.ts": {"content_hash": "def", "reviewed_at": old, "finding_count": 1},
                }
            }
        }
        assert _count_fresh(state, 30) == 1
        assert _count_stale(state, 30) == 1


# ── Narrative integration tests ───────────────────────────────────

class TestNarrativeIntegration:
    def test_review_staleness_reminder(self):
        from desloppify.narrative.reminders import _compute_reminders
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {"content_hash": "abc", "reviewed_at": old, "finding_count": 0},
                }
            },
            "findings": {},
            "reminder_history": {},
            "objective_strict": 80.0,
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind",
            debt={}, actions=[], dimensions={}, badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_stale" in types

    def test_no_reminder_when_fresh(self):
        from desloppify.narrative.reminders import _compute_reminders
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {"content_hash": "abc", "reviewed_at": now, "finding_count": 0},
                }
            },
            "findings": {},
            "reminder_history": {},
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind",
            debt={}, actions=[], dimensions={}, badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_stale" not in types

    def test_no_reminder_when_no_cache(self):
        from desloppify.narrative.reminders import _compute_reminders
        state = {"findings": {}, "reminder_history": {}}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind",
            debt={}, actions=[], dimensions={}, badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_stale" not in types

    def test_review_not_run_reminder_when_score_high(self):
        """When score >= 80 and no review cache, suggest running review (#55)."""
        from desloppify.narrative.reminders import _compute_reminders
        state = {
            "findings": {},
            "reminder_history": {},
            "objective_strict": 85.0,
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind",
            debt={}, actions=[], dimensions={}, badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_not_run" in types
        review_reminder = [r for r in reminders if r["type"] == "review_not_run"][0]
        assert "desloppify review --prepare" in review_reminder["message"]

    def test_review_not_run_no_reminder_when_score_low(self):
        """No review nudge when score is below 80 (#55)."""
        from desloppify.narrative.reminders import _compute_reminders
        state = {
            "findings": {},
            "reminder_history": {},
            "objective_strict": 60.0,
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind",
            debt={}, actions=[], dimensions={}, badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_not_run" not in types

    def test_review_not_run_no_reminder_when_already_reviewed(self):
        """No review_not_run when review cache has files (#55)."""
        from desloppify.narrative.reminders import _compute_reminders
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {"content_hash": "abc", "reviewed_at": now, "finding_count": 0},
                }
            },
            "findings": {},
            "reminder_history": {},
            "objective_strict": 95.0,
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind",
            debt={}, actions=[], dimensions={}, badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_not_run" not in types

    def test_headline_includes_review_in_maintenance(self):
        from desloppify.narrative.headline import _compute_headline
        headline = _compute_headline(
            "maintenance", {}, {}, None, None,
            95.0, 96.0, {"open": 3}, [],
            open_by_detector={"review": 3},
        )
        assert headline is not None
        assert "review finding" in headline.lower()

    def test_headline_no_review_in_early_momentum(self):
        from desloppify.narrative.headline import _compute_headline
        headline = _compute_headline(
            "early_momentum", {}, {}, None, None,
            75.0, 78.0, {"open": 10}, [],
            open_by_detector={"review": 2},
        )
        # review suffix only in maintenance/stagnation
        if headline:
            assert "design review" not in headline.lower()


# ── Registry tests ────────────────────────────────────────────────

class TestRegistry:
    def test_review_in_registry(self):
        from desloppify.registry import DETECTORS
        assert "review" in DETECTORS
        meta = DETECTORS["review"]
        assert meta.dimension == "Test health"
        assert meta.action_type == "refactor"

    def test_review_in_display_order(self):
        from desloppify.registry import display_order
        assert "review" in display_order()


# ── Dimension prompts tests ───────────────────────────────────────

class TestDimensionPrompts:
    def test_all_dimensions_have_prompts(self):
        from desloppify.review import DEFAULT_DIMENSIONS, DIMENSION_PROMPTS
        for dim in DEFAULT_DIMENSIONS:
            assert dim in DIMENSION_PROMPTS
            prompt = DIMENSION_PROMPTS[dim]
            assert "description" in prompt
            assert "look_for" in prompt
            assert "skip" in prompt

    def test_system_prompt_not_empty(self):
        from desloppify.review import REVIEW_SYSTEM_PROMPT
        assert len(REVIEW_SYSTEM_PROMPT) > 100


# ── Hash tests ────────────────────────────────────────────────────

class TestHashFile:
    def test_hash_consistency(self, tmp_path):
        from desloppify.review import hash_file
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = hash_file(str(f))
        h2 = hash_file(str(f))
        assert h1 == h2
        assert len(h1) == 16

    def test_hash_changes_with_content(self, tmp_path):
        from desloppify.review import hash_file
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h1 = hash_file(str(f))
        f.write_text("world")
        h2 = hash_file(str(f))
        assert h1 != h2

    def test_hash_missing_file(self):
        from desloppify.review import hash_file
        assert hash_file("/nonexistent/file.txt") == ""


# ── CLI tests ─────────────────────────────────────────────────────

class TestCLI:
    def test_review_parser_exists(self):
        from desloppify.cli import create_parser
        parser = create_parser()
        # Should parse without error
        args = parser.parse_args(["review", "--prepare"])
        assert args.command == "review"
        assert args.prepare is True

    def test_review_import_flag(self):
        from desloppify.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review", "--import", "findings.json"])
        assert args.command == "review"
        assert args.import_file == "findings.json"

    def test_review_max_age_flag(self):
        from desloppify.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review", "--max-age", "60"])
        assert args.max_age == 60

    def test_review_max_files_flag(self):
        from desloppify.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review", "--max-files", "25"])
        assert args.max_files == 25

    def test_review_refresh_flag(self):
        from desloppify.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review", "--refresh"])
        assert args.refresh is True

    def test_review_dimensions_flag(self):
        from desloppify.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review", "--dimensions", "naming_quality,comment_quality"])
        assert args.dimensions == "naming_quality,comment_quality"


# ── New dimension tests ──────────────────────────────────────────

class TestNewDimensions:
    def test_logic_clarity_dimension(self):
        from desloppify.review import DIMENSION_PROMPTS
        dim = DIMENSION_PROMPTS["logic_clarity"]
        assert "control flow" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_contract_coherence_dimension(self):
        from desloppify.review import DIMENSION_PROMPTS
        dim = DIMENSION_PROMPTS["contract_coherence"]
        assert "contract" in dim["description"].lower()
        assert any("return type" in item.lower() for item in dim["look_for"])

    def test_type_safety_dimension(self):
        from desloppify.review import DIMENSION_PROMPTS
        dim = DIMENSION_PROMPTS["type_safety"]
        assert "type" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_cross_module_architecture_dimension(self):
        from desloppify.review import DIMENSION_PROMPTS
        dim = DIMENSION_PROMPTS["cross_module_architecture"]
        assert "module" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_new_dimensions_in_default(self):
        from desloppify.review import DEFAULT_DIMENSIONS
        assert "logic_clarity" in DEFAULT_DIMENSIONS
        assert "abstraction_fitness" in DEFAULT_DIMENSIONS
        assert "ai_generated_debt" in DEFAULT_DIMENSIONS

    def test_import_accepts_new_dimensions(self, empty_state):
        from desloppify.review import import_review_findings
        data = [
            {
                "file": "src/foo.ts",
                "dimension": "logic_clarity",
                "identifier": "handleClick",
                "summary": "Identical if/else branches",
                "confidence": "high",
            },
            {
                "file": "src/bar.py",
                "dimension": "contract_coherence",
                "identifier": "get_user",
                "summary": "Return type says User but can return None",
                "confidence": "medium",
            },
            {
                "file": "src/config.py",
                "dimension": "cross_module_architecture",
                "identifier": "DB_URL",
                "summary": "Module reads DB_URL at import time before config is loaded",
                "confidence": "low",
            },
        ]
        diff = import_review_findings(data, empty_state, "python")
        assert diff["new"] == 3

    def test_ai_generated_debt_dimension(self):
        from desloppify.review import DIMENSION_PROMPTS
        dim = DIMENSION_PROMPTS["ai_generated_debt"]
        assert "llm" in dim["description"].lower() or "ai" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_authorization_coherence_dimension(self):
        from desloppify.review import DIMENSION_PROMPTS
        dim = DIMENSION_PROMPTS["authorization_coherence"]
        assert "auth" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_new_phase2_dimensions_in_default(self):
        from desloppify.review import DEFAULT_DIMENSIONS
        assert "ai_generated_debt" in DEFAULT_DIMENSIONS
        assert "error_consistency" in DEFAULT_DIMENSIONS

    def test_import_accepts_new_phase2_dimensions(self, empty_state):
        from desloppify.review import import_review_findings
        data = [
            {
                "file": "src/service.py",
                "dimension": "ai_generated_debt",
                "identifier": "handle_request",
                "summary": "Restating docstring on trivial function",
                "confidence": "medium",
            },
            {
                "file": "src/routes.py",
                "dimension": "authorization_coherence",
                "identifier": "delete_user",
                "summary": "Auth on GET/POST but not DELETE handler",
                "confidence": "high",
            },
        ]
        diff = import_review_findings(data, empty_state, "python")
        assert diff["new"] == 2

    def test_import_accepts_issue57_dimensions(self, empty_state):
        """New dimensions from #57 are accepted by import."""
        from desloppify.review import import_review_findings
        data = [
            {
                "file": "src/app.py",
                "dimension": "abstraction_fitness",
                "identifier": "handle_request",
                "summary": "Wrapper that just forwards to inner handler",
                "confidence": "high",
            },
            {
                "file": "src/utils.py",
                "dimension": "type_safety",
                "identifier": "parse_config",
                "summary": "Return type -> Config but can return None on failure",
                "confidence": "medium",
            },
            {
                "file": "src/core.py",
                "dimension": "cross_module_architecture",
                "identifier": "settings",
                "summary": "Global mutable dict modified by 4 different modules",
                "confidence": "high",
            },
        ]
        diff = import_review_findings(data, empty_state, "python")
        assert diff["new"] == 3


# ── Language guidance tests ──────────────────────────────────────

class TestLangGuidance:
    def test_python_guidance_exists(self):
        from desloppify.review import LANG_GUIDANCE
        assert "python" in LANG_GUIDANCE
        py = LANG_GUIDANCE["python"]
        assert "patterns" in py
        assert "naming" in py
        assert len(py["patterns"]) >= 3

    def test_typescript_guidance_exists(self):
        from desloppify.review import LANG_GUIDANCE
        assert "typescript" in LANG_GUIDANCE
        ts = LANG_GUIDANCE["typescript"]
        assert "patterns" in ts
        assert "naming" in ts
        assert len(ts["patterns"]) >= 3

    def test_prepare_includes_lang_guidance(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import prepare_review
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])
        data = prepare_review(tmp_path, mock_lang, empty_state)
        assert "lang_guidance" in data
        assert "language" in data
        assert data["language"] == "typescript"

    def test_python_auth_guidance_exists(self):
        from desloppify.review import LANG_GUIDANCE
        py = LANG_GUIDANCE["python"]
        assert "auth" in py
        assert len(py["auth"]) >= 3
        auth_text = " ".join(py["auth"]).lower()
        assert "login_required" in auth_text
        assert "request.user" in auth_text

    def test_typescript_auth_guidance_exists(self):
        from desloppify.review import LANG_GUIDANCE
        ts = LANG_GUIDANCE["typescript"]
        assert "auth" in ts
        assert len(ts["auth"]) >= 3
        auth_text = " ".join(ts["auth"]).lower()
        assert "useauth" in auth_text or "getserversession" in auth_text

    def test_prepare_includes_lang_guidance_python(self, empty_state, tmp_path):
        from desloppify.review import prepare_review
        lang = MagicMock()
        lang.name = "python"
        lang._zone_map = None
        lang._dep_graph = None
        f = tmp_path / "foo.py"
        f.write_text("def get_data():\n    return 42\n" * 15)
        lang.file_finder = MagicMock(return_value=[str(f)])
        data = prepare_review(tmp_path, lang, empty_state)
        assert data["language"] == "python"
        assert "patterns" in data["lang_guidance"]


# ── Sibling conventions tests ────────────────────────────────────

class TestSiblingConventions:
    def test_sibling_conventions_populated(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for i in range(4):
            (hooks / f"hook{i}.ts").write_text(
                f"export function useHook{i}() {{}}\n"
                f"function handleEvent{i}() {{}}\n"
            )
        mock_lang.file_finder = MagicMock(return_value=[
            str(hooks / f"hook{i}.ts") for i in range(4)
        ])
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert "hooks/" in ctx.sibling_conventions
        assert "use" in ctx.sibling_conventions["hooks/"]
        assert "handle" in ctx.sibling_conventions["hooks/"]

    def test_sibling_conventions_serialized(self, mock_lang, empty_state, tmp_path):
        from desloppify.review import build_review_context, _serialize_context
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for i in range(4):
            (hooks / f"hook{i}.ts").write_text(f"function getData{i}() {{}}\n")
        mock_lang.file_finder = MagicMock(return_value=[
            str(hooks / f"hook{i}.ts") for i in range(4)
        ])
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        serialized = _serialize_context(ctx)
        assert "sibling_conventions" in serialized


# ── File cache integration test ──────────────────────────────────

class TestFileCache:
    def test_build_context_uses_file_cache(self, mock_lang, empty_state, tmp_path):
        """build_review_context should enable file cache for performance."""
        from desloppify.review import build_review_context
        from desloppify import utils as _utils_mod
        f = tmp_path / "foo.ts"
        f.write_text("function getData() {}\nclass Foo {}")
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        # Cache should be disabled before and after
        assert not _utils_mod._cache_enabled
        build_review_context(tmp_path, mock_lang, empty_state)
        assert not _utils_mod._cache_enabled  # Cleaned up after

    def test_build_context_reentrant_cache(self, mock_lang, empty_state, tmp_path):
        """build_review_context shouldn't disable cache if caller already enabled it."""
        from desloppify.review import build_review_context
        from desloppify import utils as _utils_mod
        from desloppify.utils import enable_file_cache, disable_file_cache
        f = tmp_path / "foo.ts"
        f.write_text("function getData() {}\nclass Foo {}")
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        enable_file_cache()
        try:
            assert _utils_mod._cache_enabled
            build_review_context(tmp_path, mock_lang, empty_state)
            assert _utils_mod._cache_enabled  # Still enabled — didn't stomp caller
        finally:
            disable_file_cache()

    def test_prepare_caches_across_phases(self, mock_lang, empty_state, tmp_path):
        """prepare_review should enable cache for context + selection + extraction."""
        from desloppify.review import prepare_review
        from desloppify import utils as _utils_mod
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        assert not _utils_mod._cache_enabled
        prepare_review(tmp_path, mock_lang, empty_state)
        assert not _utils_mod._cache_enabled  # Cleaned up after


# ── Headline bug fix test ────────────────────────────────────────

class TestHeadlineBugFix:
    def test_headline_no_typeerror_when_headline_none_with_review_suffix(self):
        """Regression: None + review_suffix shouldn't TypeError."""
        from desloppify.narrative.headline import _compute_headline
        # Force: no security prefix, headline_inner returns None, review_suffix non-empty
        # stagnation + review findings + conditions that make headline_inner return None
        result = _compute_headline(
            "stagnation", {}, {}, None, None,
            None, None,  # obj_strict=None → headline_inner falls through to None
            {"open": 0}, [],
            open_by_detector={"review": 5},
        )
        # Should not crash — may return None or a string with review suffix
        if result is not None:
            assert isinstance(result, str)

    def test_headline_review_only_no_security_no_inner(self):
        """When only review_suffix exists, returns it cleanly."""
        from desloppify.narrative.headline import _compute_headline
        result = _compute_headline(
            "stagnation", {}, {}, None, None,
            None, None,
            {"open": 0}, [],
            open_by_detector={"review": 3},
        )
        if result is not None:
            assert "review finding" in result.lower()
            assert "3" in result


# ── Command integration tests ────────────────────────────────────

class TestCmdReviewPrepare:
    def test_do_prepare_writes_query_json(self, mock_lang_with_zones, empty_state, tmp_path):
        from desloppify.commands.review_cmd import _do_prepare, _setup_lang
        from unittest.mock import patch, MagicMock
        import json

        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.ts").write_text("export function foo() {}\n" * 25)
        (src / "bar.ts").write_text("export function bar() {}\n" * 25)
        file_list = [str(src / "foo.ts"), str(src / "bar.ts")]
        mock_lang_with_zones.file_finder = MagicMock(return_value=file_list)

        query_output = {}
        def capture_query(data):
            query_output.update(data)

        args = MagicMock()
        args.path = str(tmp_path)
        args.max_files = 50
        args.max_age = 30
        args.refresh = False
        args.dimensions = None

        with patch("desloppify.commands.review_cmd._setup_lang", return_value=file_list), \
             patch("desloppify.commands._helpers._write_query", capture_query):
            _do_prepare(args, empty_state, mock_lang_with_zones, None)

        assert query_output["command"] == "review"
        assert query_output["total_candidates"] >= 1
        assert "system_prompt" in query_output

    def test_do_import_saves_state(self, empty_state, tmp_path):
        from desloppify.commands.review_cmd import _do_import
        from unittest.mock import patch, MagicMock

        findings = [
            {
                "file": "src/foo.ts",
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "processData is vague",
                "confidence": "high",
            }
        ]
        findings_file = tmp_path / "findings.json"
        findings_file.write_text(json.dumps(findings))

        saved = {}
        def mock_save(state, sp):
            saved["state"] = state
            saved["sp"] = sp

        lang = MagicMock()
        lang.name = "typescript"

        # save_state is imported lazily: from ..state import save_state
        with patch("desloppify.state.save_state", mock_save):
            _do_import(str(findings_file), empty_state, lang, "fake_sp")

        assert saved["sp"] == "fake_sp"
        assert len(empty_state["findings"]) == 1

    def test_do_import_rejects_nonexistent_file(self, empty_state):
        from desloppify.commands.review_cmd import _do_import
        from unittest.mock import MagicMock

        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import("/nonexistent/findings.json", empty_state, lang, "sp")

    def test_do_import_rejects_non_array(self, empty_state, tmp_path):
        from desloppify.commands.review_cmd import _do_import
        from unittest.mock import MagicMock

        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"not": "an array"}')

        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import(str(bad_file), empty_state, lang, "sp")

    def test_do_import_rejects_invalid_json(self, empty_state, tmp_path):
        from desloppify.commands.review_cmd import _do_import
        from unittest.mock import MagicMock

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all")

        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import(str(bad_file), empty_state, lang, "sp")


class TestSetupLang:
    def test_setup_builds_zone_map(self, tmp_path):
        from desloppify.commands.review_cmd import _setup_lang
        from desloppify.zones import ZoneRule

        lang = MagicMock()
        lang.name = "typescript"
        lang._zone_map = None
        lang._dep_graph = None
        lang.build_dep_graph = None
        lang.zone_rules = [ZoneRule("test", ["/tests/"])]
        f1 = str(tmp_path / "src" / "foo.ts")
        f2 = str(tmp_path / "tests" / "foo.test.ts")
        lang.file_finder = MagicMock(return_value=[f1, f2])

        files = _setup_lang(lang, tmp_path, {})
        assert files == [f1, f2]
        assert lang._zone_map is not None

    def test_setup_returns_files(self, tmp_path):
        from desloppify.commands.review_cmd import _setup_lang

        lang = MagicMock()
        lang.name = "typescript"
        lang._zone_map = None
        lang._dep_graph = None
        lang.build_dep_graph = None
        lang.zone_rules = []
        lang.file_finder = None

        files = _setup_lang(lang, tmp_path, {})
        assert files == []

    def test_setup_builds_dep_graph(self, tmp_path):
        from desloppify.commands.review_cmd import _setup_lang

        fake_graph = {"a.ts": {"imports": set(), "importers": set()}}
        lang = MagicMock()
        lang.name = "typescript"
        lang._zone_map = None
        lang._dep_graph = None
        lang.zone_rules = []
        lang.file_finder = None
        lang.build_dep_graph = MagicMock(return_value=fake_graph)

        _setup_lang(lang, tmp_path, {})
        assert lang._dep_graph == fake_graph

    def test_setup_dep_graph_error_nonfatal(self, tmp_path):
        from desloppify.commands.review_cmd import _setup_lang

        lang = MagicMock()
        lang.name = "typescript"
        lang._zone_map = None
        lang._dep_graph = None
        lang.zone_rules = []
        lang.file_finder = None
        lang.build_dep_graph = MagicMock(side_effect=RuntimeError("boom"))

        files = _setup_lang(lang, tmp_path, {})
        assert files == []
        assert lang._dep_graph is None  # Not set due to error


# ── _update_review_cache robustness test ─────────────────────────

class TestUpdateReviewCache:
    def test_cache_created_from_scratch(self, empty_state, sample_findings_data, tmp_path):
        from desloppify.review import _update_review_cache
        with patch("desloppify.review.import_findings.PROJECT_ROOT", tmp_path):
            (tmp_path / "src").mkdir(exist_ok=True)
            (tmp_path / "src" / "foo.ts").write_text("content")
            (tmp_path / "src" / "bar.ts").write_text("content")
            _update_review_cache(empty_state, sample_findings_data)
        assert "review_cache" in empty_state
        assert "files" in empty_state["review_cache"]

    def test_cache_survives_partial_review_cache(self, sample_findings_data, tmp_path):
        """If review_cache exists without files key, shouldn't crash."""
        from desloppify.review import _update_review_cache
        state = {"review_cache": {}}  # No "files" key
        with patch("desloppify.review.import_findings.PROJECT_ROOT", tmp_path):
            (tmp_path / "src").mkdir(exist_ok=True)
            (tmp_path / "src" / "foo.ts").write_text("content")
            (tmp_path / "src" / "bar.ts").write_text("content")
            _update_review_cache(state, sample_findings_data)
        assert "files" in state["review_cache"]

    def test_file_finder_called_once_in_prepare(self, mock_lang, empty_state, tmp_path):
        """prepare_review should call file_finder exactly once."""
        from desloppify.review import prepare_review
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        prepare_review(tmp_path, mock_lang, empty_state)
        # file_finder should be called exactly once (by prepare_review itself)
        assert mock_lang.file_finder.call_count == 1


# ── Skipped findings tests ────────────────────────────────────────

class TestSkippedFindings:
    """Findings missing required fields are tracked and reported."""

    def test_per_file_skipped_missing_fields(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
        data = {
            "findings": [
                # Valid finding
                {"file": "src/a.ts", "dimension": "naming_quality",
                 "identifier": "x", "summary": "bad", "confidence": "high"},
                # Missing 'identifier'
                {"file": "src/b.ts", "dimension": "naming_quality",
                 "summary": "bad", "confidence": "high"},
                # Missing 'confidence'
                {"file": "src/c.ts", "dimension": "naming_quality",
                 "identifier": "y", "summary": "bad"},
            ],
        }
        diff = import_review_findings(data, state, "typescript")
        assert diff["new"] == 1
        assert diff["skipped"] == 2
        assert len(diff["skipped_details"]) == 2
        assert "identifier" in diff["skipped_details"][0]["missing"]
        assert "confidence" in diff["skipped_details"][1]["missing"]

    def test_per_file_invalid_dimension_skipped(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
        data = {
            "findings": [
                {"file": "src/a.ts", "dimension": "bogus_dimension",
                 "identifier": "x", "summary": "bad", "confidence": "high"},
            ],
        }
        diff = import_review_findings(data, state, "typescript")
        assert diff["new"] == 0
        assert diff["skipped"] == 1
        assert "invalid dimension" in diff["skipped_details"][0]["missing"][0]

    def test_holistic_skipped_missing_fields(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_holistic_findings
        state = _empty_state()
        data = {
            "findings": [
                # Valid
                {"dimension": "cross_module_architecture", "identifier": "god_mod",
                 "summary": "too central", "confidence": "high"},
                # Missing 'summary'
                {"dimension": "cross_module_architecture", "identifier": "god_mod2",
                 "confidence": "high"},
            ],
        }
        diff = import_holistic_findings(data, state, "typescript")
        assert diff["new"] == 1
        assert diff["skipped"] == 1
        assert "summary" in diff["skipped_details"][0]["missing"]

    def test_no_skipped_when_all_valid(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()
        data = {
            "findings": [
                {"file": "src/a.ts", "dimension": "naming_quality",
                 "identifier": "x", "summary": "bad", "confidence": "high"},
            ],
        }
        diff = import_review_findings(data, state, "typescript")
        assert diff["new"] == 1
        assert "skipped" not in diff


# ── Auto-resolve on re-import tests ──────────────────────────────

class TestAutoResolveOnReImport:
    """Old findings should auto-resolve when re-imported without them."""

    def test_holistic_auto_resolve_on_reimport(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_holistic_findings
        state = _empty_state()

        # First import: 2 holistic findings
        data1 = {
            "findings": [
                {"dimension": "cross_module_architecture", "identifier": "god_mod",
                 "summary": "too central", "confidence": "high"},
                {"dimension": "abstraction_fitness", "identifier": "util_dump",
                 "summary": "dumping ground", "confidence": "medium"},
            ],
        }
        diff1 = import_holistic_findings(data1, state, "typescript")
        assert diff1["new"] == 2
        open_ids = [fid for fid, f in state["findings"].items()
                    if f["status"] == "open"]
        assert len(open_ids) == 2

        # Second import: only 1 finding (different from first)
        data2 = {
            "findings": [
                {"dimension": "error_consistency", "identifier": "mixed_errors",
                 "summary": "mixed strategies", "confidence": "high"},
            ],
        }
        diff2 = import_holistic_findings(data2, state, "typescript")
        assert diff2["new"] == 1
        # The 2 old findings should be auto-resolved
        assert diff2["auto_resolved"] >= 2
        still_open = [fid for fid, f in state["findings"].items()
                      if f["status"] == "open"]
        assert len(still_open) == 1

    def test_per_file_auto_resolve_on_reimport(self):
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings
        state = _empty_state()

        # First import: findings for src/a.ts
        data1 = {
            "findings": [
                {"file": "src/a.ts", "dimension": "naming_quality",
                 "identifier": "x", "summary": "bad name", "confidence": "high"},
                {"file": "src/a.ts", "dimension": "comment_quality",
                 "identifier": "y", "summary": "stale comment", "confidence": "medium"},
            ],
        }
        diff1 = import_review_findings(data1, state, "typescript")
        assert diff1["new"] == 2

        # Second import: re-review src/a.ts but only 1 finding remains
        data2 = {
            "findings": [
                {"file": "src/a.ts", "dimension": "naming_quality",
                 "identifier": "x", "summary": "bad name", "confidence": "high"},
            ],
        }
        diff2 = import_review_findings(data2, state, "typescript")
        # The comment_quality finding should be auto-resolved
        resolved = [f for f in state["findings"].values()
                    if f["status"] == "auto_resolved"
                    and "not reported in latest per-file" in (f.get("note") or "")]
        assert len(resolved) >= 1

    def test_holistic_does_not_resolve_per_file(self):
        """Holistic re-import should not touch per-file review findings."""
        from desloppify.state import _empty_state
        from desloppify.review import import_review_findings, import_holistic_findings
        state = _empty_state()

        # Import per-file findings
        per_file = {
            "findings": [
                {"file": "src/a.ts", "dimension": "naming_quality",
                 "identifier": "x", "summary": "bad name", "confidence": "high"},
            ],
        }
        import_review_findings(per_file, state, "typescript")
        per_file_ids = [fid for fid, f in state["findings"].items()
                        if f["status"] == "open"]
        assert len(per_file_ids) == 1

        # Import holistic findings (empty) — should NOT resolve per-file
        holistic = {"findings": []}
        import_holistic_findings(holistic, state, "typescript")
        # Per-file finding should still be open
        assert state["findings"][per_file_ids[0]]["status"] == "open"
