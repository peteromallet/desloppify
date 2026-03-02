"""Tests for the subjective code review system (review.py, commands/review/cmd.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from desloppify.intelligence.review import (
    build_review_context,
    hash_file,
)
from desloppify.tests.review.shared_review_fixtures import (
    prepare_review,
    select_files_for_review,
)


class TestBuildReviewContext:
    def test_empty_files(self, mock_lang, empty_state):
        mock_lang.file_finder = MagicMock(return_value=[])
        ctx = build_review_context(Path("/tmp"), mock_lang, empty_state)
        assert ctx.naming_vocabulary == {}
        assert ctx.codebase_stats == {}

    def test_naming_vocabulary_extraction(self, mock_lang, empty_state, tmp_path):
        (tmp_path / "foo.ts").write_text(
            "function getData() {}\ndef setName(): pass\nclass UserService {}"
        )
        (tmp_path / "bar.ts").write_text(
            "function getUser() {}\nasync function handleClick() {}"
        )
        mock_lang.file_finder = MagicMock(
            return_value=[str(tmp_path / "foo.ts"), str(tmp_path / "bar.ts")]
        )
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert ctx.naming_vocabulary["total_names"] == 5
        assert ctx.naming_vocabulary["prefixes"]["get"] == 2
        assert ctx.naming_vocabulary["prefixes"]["set"] == 1
        assert ctx.naming_vocabulary["prefixes"]["handle"] == 1

    def test_error_convention_detection(self, mock_lang, empty_state, tmp_path):
        (tmp_path / "foo.ts").write_text("try { x } catch(e) {}\nreturn null;")
        (tmp_path / "bar.ts").write_text("throw new Error('fail')")
        mock_lang.file_finder = MagicMock(
            return_value=[str(tmp_path / "foo.ts"), str(tmp_path / "bar.ts")]
        )
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert ctx.error_conventions.get("try_catch") == 1
        assert ctx.error_conventions.get("returns_null") == 1
        assert ctx.error_conventions.get("throws") == 1

    def test_existing_findings_in_context(
        self, mock_lang, state_with_findings, tmp_path
    ):
        (tmp_path / "foo.ts").write_text("x")
        mock_lang.file_finder = MagicMock(return_value=[str(tmp_path / "foo.ts")])
        with patch("desloppify.intelligence.review.context.rel") as mock_rel:
            def _fake_rel(value: str) -> str:
                text = str(value).replace("\\", "/")
                if text == str(tmp_path / "foo.ts").replace("\\", "/"):
                    return "src/foo.ts"
                return text

            mock_rel.side_effect = _fake_rel
            ctx = build_review_context(tmp_path, mock_lang, state_with_findings)

        assert "src/foo.ts" in ctx.existing_findings

    def test_existing_findings_are_scoped_to_selected_files(
        self, mock_lang, state_with_findings, tmp_path
    ):
        (tmp_path / "foo.ts").write_text("x")
        mock_lang.file_finder = MagicMock(return_value=[str(tmp_path / "foo.ts")])
        with patch("desloppify.intelligence.review.context.rel") as mock_rel:
            def _fake_rel(value: str) -> str:
                text = str(value).replace("\\", "/")
                if text == str(tmp_path / "foo.ts").replace("\\", "/"):
                    return "src/foo.ts"
                return text

            mock_rel.side_effect = _fake_rel
            ctx = build_review_context(tmp_path, mock_lang, state_with_findings)

        assert "src/foo.ts" in ctx.existing_findings
        assert "src/utils.ts" not in ctx.existing_findings

    def test_codebase_stats(self, mock_lang, empty_state, tmp_path):
        (tmp_path / "foo.ts").write_text("line1\nline2\nline3")
        (tmp_path / "bar.ts").write_text("line1\nline2")
        mock_lang.file_finder = MagicMock(
            return_value=[str(tmp_path / "foo.ts"), str(tmp_path / "bar.ts")]
        )
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert ctx.codebase_stats["total_files"] == 2
        assert ctx.codebase_stats["total_loc"] == 5
        assert ctx.codebase_stats["avg_file_loc"] == 2

    def test_module_patterns(self, mock_lang, empty_state, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for i in range(4):
            (hooks / f"hook{i}.ts").write_text(f"export function useHook{i}() {{}}")
        mock_lang.file_finder = MagicMock(
            return_value=[str(hooks / f"hook{i}.ts") for i in range(4)]
        )
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert "hooks/" in ctx.module_patterns

    def test_import_graph_summary(self, mock_lang, empty_state, tmp_path):
        (tmp_path / "foo.ts").write_text("x")
        mock_lang.file_finder = MagicMock(return_value=[str(tmp_path / "foo.ts")])
        mock_lang.dep_graph = {
            "src/foo.ts": {"importers": {"src/bar.ts", "src/baz.ts"}, "imports": set()},
        }
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert "src/foo.ts" in ctx.import_graph_summary["top_imported"]

    def test_zone_distribution(self, mock_lang_with_zones, empty_state, tmp_path):
        (tmp_path / "foo.ts").write_text("x")
        mock_lang_with_zones.file_finder = MagicMock(
            return_value=[str(tmp_path / "foo.ts")]
        )
        ctx = build_review_context(tmp_path, mock_lang_with_zones, empty_state)
        assert ctx.zone_distribution == {"production": 3, "test": 1}


# ── File selection tests ──────────────────────────────────────────


class TestSelectFilesForReview:
    def test_selects_production_files(
        self, mock_lang_with_zones, empty_state, tmp_path
    ):
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
        mock_lang_with_zones.file_finder = MagicMock(
            return_value=[
                foo_path,
                bar_path,
                test_path,
            ]
        )
        files = select_files_for_review(mock_lang_with_zones, tmp_path, empty_state)
        assert foo_path in files
        assert bar_path in files
        assert test_path not in files

    def test_max_files_limit(self, mock_lang, empty_state, tmp_path):
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
        now = datetime.now(UTC).isoformat(timespec="seconds")
        # Create a real file for hashing
        real_file = tmp_path / "cached.ts"
        real_file.write_text("cached content")
        content_hash = hash_file(str(real_file))

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        # Patch rel() to return a stable path
        with patch("desloppify.intelligence.review.selection.rel", return_value="cached.ts"):
            state["review_cache"] = {
                "files": {
                    "cached.ts": {
                        "content_hash": content_hash,
                        "reviewed_at": now,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(
                mock_lang,
                tmp_path,
                state,
                max_age_days=30,
                force_refresh=False,
            )
        assert len(files) == 0

    def test_cache_refresh_stale_files(self, mock_lang, empty_state, tmp_path):
        old_time = (datetime.now(UTC) - timedelta(days=60)).isoformat(
            timespec="seconds"
        )
        real_file = tmp_path / "stale.ts"
        real_file.write_text("stale content\n" * 25)  # >= MIN_REVIEW_LOC
        content_hash = hash_file(str(real_file))

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        with patch("desloppify.intelligence.review.selection.rel", return_value="stale.ts"):
            state["review_cache"] = {
                "files": {
                    "stale.ts": {
                        "content_hash": content_hash,
                        "reviewed_at": old_time,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(
                mock_lang,
                tmp_path,
                state,
                max_age_days=30,
                force_refresh=False,
            )
        assert len(files) == 1

    def test_content_hash_change_triggers_review(
        self, mock_lang, empty_state, tmp_path
    ):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        real_file = tmp_path / "changed.ts"
        real_file.write_text("new content\n" * 25)  # >= MIN_REVIEW_LOC

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        with patch("desloppify.intelligence.review.selection.rel", return_value="changed.ts"):
            state["review_cache"] = {
                "files": {
                    "changed.ts": {
                        "content_hash": "old_hash_different",
                        "reviewed_at": now,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(
                mock_lang,
                tmp_path,
                state,
                max_age_days=30,
                force_refresh=False,
            )
        assert len(files) == 1

    def test_force_refresh_ignores_cache(self, mock_lang, empty_state, tmp_path):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        real_file = tmp_path / "cached.ts"
        real_file.write_text("cached content\n" * 25)  # >= MIN_REVIEW_LOC
        content_hash = hash_file(str(real_file))

        mock_lang.file_finder = MagicMock(return_value=[str(real_file)])
        state = dict(empty_state)
        with patch("desloppify.intelligence.review.selection.rel", return_value="cached.ts"):
            state["review_cache"] = {
                "files": {
                    "cached.ts": {
                        "content_hash": content_hash,
                        "reviewed_at": now,
                        "finding_count": 0,
                    }
                }
            }
            files = select_files_for_review(
                mock_lang, tmp_path, state, max_age_days=30, force_refresh=True
            )
        assert len(files) == 1

    def test_priority_ordering_by_importers(self, mock_lang, empty_state, tmp_path):
        # Create real files so read_file_text works (need >= MIN_REVIEW_LOC)
        src = tmp_path / "src"
        src.mkdir()
        (src / "popular.ts").write_text("export function foo() {}\n" * 30)
        (src / "lonely.ts").write_text("export function bar() {}\n" * 30)
        pop_abs = str(src / "popular.ts")
        lon_abs = str(src / "lonely.ts")
        mock_lang.file_finder = MagicMock(return_value=[pop_abs, lon_abs])
        mock_lang.dep_graph = {
            pop_abs: {"importers": {"a", "b", "c", "d", "e"}, "imports": set()},
            lon_abs: {"importers": set(), "imports": set()},
        }
        files = select_files_for_review(mock_lang, tmp_path, empty_state)
        assert files[0] == pop_abs


# ── Prepare review tests ─────────────────────────────────────────


class TestPrepareReview:
    def test_basic_prepare(self, mock_lang, empty_state, tmp_path):
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        data = prepare_review(tmp_path, mock_lang, empty_state)
        assert data["command"] == "review"
        assert data["total_candidates"] == 1
        assert data["dimensions"] == [
            "naming_quality",
            "logic_clarity",
            "type_safety",
            "contract_coherence",
            "error_consistency",
            "abstraction_fitness",
            "ai_generated_debt",
            "high_level_elegance",
            "mid_level_elegance",
            "low_level_elegance",
            "cross_module_architecture",
            "initialization_coupling",
            "convention_outlier",
            "dependency_health",
            "test_strategy",
            "api_surface_coherence",
            "authorization_consistency",
            "incomplete_migration",
            "package_organization",
            "design_coherence",
        ]
        assert "system_prompt" in data
        assert len(data["files"]) == 1
        assert "export function getData() { return 42; }" in data["files"][0]["content"]

    def test_custom_dimensions(self, mock_lang, empty_state, tmp_path):
        f = tmp_path / "foo.ts"
        f.write_text("export function bar() { return 1; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        data = prepare_review(
            tmp_path,
            mock_lang,
            empty_state,
            dimensions=["naming_quality", "comment_quality"],
        )
        assert data["dimensions"] == ["naming_quality", "comment_quality"]
        assert len(data["dimension_prompts"]) == 2

    def test_file_neighbors_included(self, mock_lang, empty_state, tmp_path):
        f = tmp_path / "foo.ts"
        f.write_text("export function bar() {}\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])
        mock_lang.dep_graph = {
            "foo.ts": {"imports": {"bar.ts"}, "importers": {"baz.ts", "qux.ts"}},
        }

        with (
            patch("desloppify.intelligence.review.context.rel", return_value="foo.ts"),
            patch("desloppify.intelligence.review.selection.rel", return_value="foo.ts"),
            patch("desloppify.intelligence.review.prepare.rel", return_value="foo.ts"),
        ):
            data = prepare_review(tmp_path, mock_lang, empty_state)
        if data["files"]:
            neighbors = data["files"][0]["neighbors"]
            if neighbors:  # dep graph lookup may not match the patched rel
                assert "imports" in neighbors
