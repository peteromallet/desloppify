"""Tests for the subjective code review system (review.py, commands/review/cmd.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from desloppify.cli import create_parser
from desloppify.core.registry import DETECTORS, display_order
from desloppify.file_discovery import (
    disable_file_cache,
    enable_file_cache,
    is_file_cache_enabled,
)
from desloppify.intelligence.narrative.headline import _compute_headline
from desloppify.intelligence.narrative.reminders import _compute_reminders
from desloppify.intelligence.review import (
    DIMENSION_PROMPTS,
    LANG_GUIDANCE,
    REVIEW_SYSTEM_PROMPT,
    build_review_context,
    hash_file,
    import_review_findings,
)
from desloppify.intelligence.review import (
    DIMENSIONS as REVIEW_DIMENSIONS,
)
from desloppify.intelligence.review.context import serialize_context
from desloppify.intelligence.review.selection import (
    count_fresh,
    count_stale,
)
from desloppify.tests.review.shared_review_fixtures import (
    _as_review_payload,
    prepare_review,
)


class TestStaleness:
    def test_stale_after_max_age(self):
        old = (datetime.now(UTC) - timedelta(days=60)).isoformat(
            timespec="seconds"
        )
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {
                        "content_hash": "abc",
                        "reviewed_at": old,
                        "finding_count": 0,
                    },
                }
            }
        }
        assert count_stale(state, 30) == 1
        assert count_fresh(state, 30) == 0

    def test_fresh_within_max_age(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {
                        "content_hash": "abc",
                        "reviewed_at": now,
                        "finding_count": 0,
                    },
                }
            }
        }
        assert count_stale(state, 30) == 0
        assert count_fresh(state, 30) == 1

    def test_mixed_fresh_and_stale(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        old = (datetime.now(UTC) - timedelta(days=60)).isoformat(
            timespec="seconds"
        )
        state = {
            "review_cache": {
                "files": {
                    "fresh.ts": {
                        "content_hash": "abc",
                        "reviewed_at": now,
                        "finding_count": 0,
                    },
                    "stale.ts": {
                        "content_hash": "def",
                        "reviewed_at": old,
                        "finding_count": 1,
                    },
                }
            }
        }
        assert count_fresh(state, 30) == 1
        assert count_stale(state, 30) == 1


# ── Narrative integration tests ───────────────────────────────────


class TestNarrativeIntegration:
    def test_review_staleness_reminder(self):
        old = (datetime.now(UTC) - timedelta(days=60)).isoformat(
            timespec="seconds"
        )
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {
                        "content_hash": "abc",
                        "reviewed_at": old,
                        "finding_count": 0,
                    },
                }
            },
            "findings": {},
            "reminder_history": {},
            "strict_score": 80.0,
        }
        reminders, _ = _compute_reminders(
            state,
            "typescript",
            "middle_grind",
            debt={},
            actions=[],
            dimensions={},
            badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_stale" in types

    def test_no_reminder_when_fresh(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {
                        "content_hash": "abc",
                        "reviewed_at": now,
                        "finding_count": 0,
                    },
                }
            },
            "findings": {},
            "reminder_history": {},
        }
        reminders, _ = _compute_reminders(
            state,
            "typescript",
            "middle_grind",
            debt={},
            actions=[],
            dimensions={},
            badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_stale" not in types

    def test_no_reminder_when_no_cache(self):
        state = {"findings": {}, "reminder_history": {}}
        reminders, _ = _compute_reminders(
            state,
            "typescript",
            "middle_grind",
            debt={},
            actions=[],
            dimensions={},
            badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_stale" not in types

    def test_review_not_run_reminder_when_score_high(self):
        """When score >= 80 and no review cache, suggest running review (#55)."""
        state = {
            "findings": {},
            "reminder_history": {},
            "strict_score": 85.0,
        }
        reminders, _ = _compute_reminders(
            state,
            "typescript",
            "middle_grind",
            debt={},
            actions=[],
            dimensions={},
            badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_not_run" in types
        review_reminder = [r for r in reminders if r["type"] == "review_not_run"][0]
        assert "desloppify review --prepare" in review_reminder["message"]

    def test_review_not_run_no_reminder_when_score_low(self):
        """No review nudge when score is below 80 (#55)."""
        state = {
            "findings": {},
            "reminder_history": {},
            "strict_score": 60.0,
        }
        reminders, _ = _compute_reminders(
            state,
            "typescript",
            "middle_grind",
            debt={},
            actions=[],
            dimensions={},
            badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_not_run" not in types

    def test_review_not_run_no_reminder_when_already_reviewed(self):
        """No review_not_run when review cache has files (#55)."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        state = {
            "review_cache": {
                "files": {
                    "foo.ts": {
                        "content_hash": "abc",
                        "reviewed_at": now,
                        "finding_count": 0,
                    },
                }
            },
            "findings": {},
            "reminder_history": {},
            "strict_score": 95.0,
        }
        reminders, _ = _compute_reminders(
            state,
            "typescript",
            "middle_grind",
            debt={},
            actions=[],
            dimensions={},
            badge={},
            command="scan",
        )
        types = [r["type"] for r in reminders]
        assert "review_not_run" not in types

    def test_headline_includes_review_in_maintenance(self):
        headline = _compute_headline(
            "maintenance",
            {},
            {},
            None,
            None,
            95.0,
            96.0,
            {"open": 3},
            [],
            open_by_detector={"review": 3},
        )
        assert headline is not None
        assert "review finding" in headline.lower()

    def test_headline_no_review_in_early_momentum(self):
        headline = _compute_headline(
            "early_momentum",
            {},
            {},
            None,
            None,
            75.0,
            78.0,
            {"open": 10},
            [],
            open_by_detector={"review": 2},
        )
        # review suffix only in maintenance/stagnation
        if headline:
            assert "design review" not in headline.lower()


# ── Registry tests ────────────────────────────────────────────────


class TestRegistry:
    def test_review_in_registry(self):
        assert "review" in DETECTORS
        meta = DETECTORS["review"]
        assert meta.dimension == "Test health"
        assert meta.action_type == "refactor"

    def test_review_in_display_order(self):
        assert "review" in display_order()


# ── Dimension prompts tests ───────────────────────────────────────


class TestDimensionPrompts:
    def test_all_dimensions_have_prompts(self):
        for dim in REVIEW_DIMENSIONS:
            assert dim in DIMENSION_PROMPTS
            prompt = DIMENSION_PROMPTS[dim]
            assert "description" in prompt
            assert "look_for" in prompt
            assert "skip" in prompt

    def test_system_prompt_not_empty(self):
        assert len(REVIEW_SYSTEM_PROMPT) > 100


# ── Hash tests ────────────────────────────────────────────────────


class TestHashFile:
    def test_hash_consistency(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = hash_file(str(f))
        h2 = hash_file(str(f))
        assert h1 == h2
        assert len(h1) == 16

    def test_hash_changes_with_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h1 = hash_file(str(f))
        f.write_text("world")
        h2 = hash_file(str(f))
        assert h1 != h2

    def test_hash_missing_file(self):
        assert hash_file("/nonexistent/file.txt") == ""


# ── CLI tests ─────────────────────────────────────────────────────


class TestCLI:
    def test_review_parser_exists(self):
        parser = create_parser()
        # Should parse without error
        args = parser.parse_args(["review", "--prepare"])
        assert args.command == "review"
        assert args.prepare is True

    def test_review_import_flag(self):
        parser = create_parser()
        args = parser.parse_args(["review", "--import", "findings.json"])
        assert args.command == "review"
        assert args.import_file == "findings.json"

    def test_review_allow_partial_flag(self):
        parser = create_parser()
        args = parser.parse_args(["review", "--import", "findings.json", "--allow-partial"])
        assert args.allow_partial is True

    def test_review_max_age_flag(self):
        parser = create_parser()
        args = parser.parse_args(["review", "--max-age", "60"])
        assert args.max_age == 60

    def test_review_max_files_flag(self):
        parser = create_parser()
        args = parser.parse_args(["review", "--max-files", "25"])
        assert args.max_files == 25

    def test_review_refresh_flag(self):
        parser = create_parser()
        args = parser.parse_args(["review", "--refresh"])
        assert args.refresh is True

    def test_review_dimensions_flag(self):
        parser = create_parser()
        args = parser.parse_args(
            ["review", "--dimensions", "naming_quality,comment_quality"]
        )
        assert args.dimensions == "naming_quality,comment_quality"

    def test_review_run_batches_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            [
                "review",
                "--run-batches",
                "--runner",
                "codex",
                "--parallel",
                "--max-parallel-batches",
                "3",
                "--batch-timeout-seconds",
                "90",
                "--batch-max-retries",
                "2",
                "--batch-retry-backoff-seconds",
                "1.5",
                "--batch-heartbeat-seconds",
                "2.5",
                "--batch-stall-warning-seconds",
                "45",
                "--save-run-log",
                "--run-log-file",
                ".desloppify/subagents/runs/custom.log",
                "--dry-run",
                "--only-batches",
                "1,3",
            ]
        )
        assert args.run_batches is True
        assert args.runner == "codex"
        assert args.parallel is True
        assert args.max_parallel_batches == 3
        assert args.batch_timeout_seconds == 90
        assert args.batch_max_retries == 2
        assert args.batch_retry_backoff_seconds == 1.5
        assert args.batch_heartbeat_seconds == 2.5
        assert args.batch_stall_warning_seconds == 45
        assert args.save_run_log is True
        assert args.run_log_file == ".desloppify/subagents/runs/custom.log"
        assert args.dry_run is True
        assert args.only_batches == "1,3"


# ── New dimension tests ──────────────────────────────────────────


class TestNewDimensions:
    def test_logic_clarity_dimension(self):
        dim = DIMENSION_PROMPTS["logic_clarity"]
        assert "control flow" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_contract_coherence_dimension(self):
        dim = DIMENSION_PROMPTS["contract_coherence"]
        assert "contract" in dim["description"].lower()
        assert any("return type" in item.lower() for item in dim["look_for"])

    def test_type_safety_dimension(self):
        dim = DIMENSION_PROMPTS["type_safety"]
        assert "type" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_cross_module_architecture_dimension(self):
        dim = DIMENSION_PROMPTS["cross_module_architecture"]
        assert "module" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_new_dimensions_in_default(self):
        assert "logic_clarity" in REVIEW_DIMENSIONS
        assert "abstraction_fitness" in REVIEW_DIMENSIONS
        assert "ai_generated_debt" in REVIEW_DIMENSIONS

    def test_import_accepts_new_dimensions(self, empty_state):
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
        diff = import_review_findings(_as_review_payload(data), empty_state, "python")
        assert diff["new"] == 3

    def test_ai_generated_debt_dimension(self):
        dim = DIMENSION_PROMPTS["ai_generated_debt"]
        assert "llm" in dim["description"].lower() or "ai" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_authorization_coherence_dimension(self):
        dim = DIMENSION_PROMPTS["authorization_coherence"]
        assert "auth" in dim["description"].lower()
        assert len(dim["look_for"]) >= 3
        assert len(dim["skip"]) >= 1

    def test_new_phase2_dimensions_in_default(self):
        assert "ai_generated_debt" in REVIEW_DIMENSIONS
        assert "error_consistency" in REVIEW_DIMENSIONS

    def test_import_accepts_new_phase2_dimensions(self, empty_state):
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
        diff = import_review_findings(_as_review_payload(data), empty_state, "python")
        assert diff["new"] == 2

    def test_import_accepts_issue57_dimensions(self, empty_state):
        """New dimensions from #57 are accepted by import."""
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
        diff = import_review_findings(_as_review_payload(data), empty_state, "python")
        assert diff["new"] == 3


# ── Language guidance tests ──────────────────────────────────────


class TestLangGuidance:
    def test_python_guidance_exists(self):
        assert "python" in LANG_GUIDANCE
        py = LANG_GUIDANCE["python"]
        assert "patterns" in py
        assert "naming" in py
        assert len(py["patterns"]) >= 3

    def test_typescript_guidance_exists(self):
        assert "typescript" in LANG_GUIDANCE
        ts = LANG_GUIDANCE["typescript"]
        assert "patterns" in ts
        assert "naming" in ts
        assert len(ts["patterns"]) >= 3

    def test_prepare_includes_lang_guidance(self, mock_lang, empty_state, tmp_path):
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])
        data = prepare_review(tmp_path, mock_lang, empty_state)
        assert "lang_guidance" in data
        assert "language" in data
        assert data["language"] == "typescript"

    def test_python_auth_guidance_exists(self):
        py = LANG_GUIDANCE["python"]
        assert "auth" in py
        assert len(py["auth"]) >= 3
        auth_text = " ".join(py["auth"]).lower()
        assert "login_required" in auth_text
        assert "request.user" in auth_text

    def test_typescript_auth_guidance_exists(self):
        ts = LANG_GUIDANCE["typescript"]
        assert "auth" in ts
        assert len(ts["auth"]) >= 3
        auth_text = " ".join(ts["auth"]).lower()
        assert "useauth" in auth_text or "getserversession" in auth_text

    def test_prepare_includes_lang_guidance_python(self, empty_state, tmp_path):
        lang = MagicMock()
        lang.name = "python"
        lang.zone_map = None
        lang.dep_graph = None
        f = tmp_path / "foo.py"
        f.write_text("def get_data():\n    return 42\n" * 15)
        lang.file_finder = MagicMock(return_value=[str(f)])
        data = prepare_review(tmp_path, lang, empty_state)
        assert data["language"] == "python"
        assert "patterns" in data["lang_guidance"]


# ── Sibling conventions tests ────────────────────────────────────


class TestSiblingConventions:
    def test_sibling_conventions_populated(self, mock_lang, empty_state, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for i in range(4):
            (hooks / f"hook{i}.ts").write_text(
                f"export function useHook{i}() {{}}\nfunction handleEvent{i}() {{}}\n"
            )
        mock_lang.file_finder = MagicMock(
            return_value=[str(hooks / f"hook{i}.ts") for i in range(4)]
        )
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        assert "hooks/" in ctx.sibling_conventions
        assert "use" in ctx.sibling_conventions["hooks/"]
        assert "handle" in ctx.sibling_conventions["hooks/"]

    def test_sibling_conventions_serialized(self, mock_lang, empty_state, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        for i in range(4):
            (hooks / f"hook{i}.ts").write_text(f"function getData{i}() {{}}\n")
        mock_lang.file_finder = MagicMock(
            return_value=[str(hooks / f"hook{i}.ts") for i in range(4)]
        )
        ctx = build_review_context(tmp_path, mock_lang, empty_state)
        serialized = serialize_context(ctx)
        assert "sibling_conventions" in serialized


# ── File cache integration test ──────────────────────────────────


class TestFileCache:
    def test_build_context_uses_file_cache(self, mock_lang, empty_state, tmp_path):
        """build_review_context should enable file cache for performance."""
        f = tmp_path / "foo.ts"
        f.write_text("function getData() {}\nclass Foo {}")
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        # Cache should be disabled before and after
        assert not is_file_cache_enabled()
        build_review_context(tmp_path, mock_lang, empty_state)
        assert not is_file_cache_enabled()  # Cleaned up after

    def test_build_context_reentrant_cache(self, mock_lang, empty_state, tmp_path):
        """build_review_context shouldn't disable cache if caller already enabled it."""
        f = tmp_path / "foo.ts"
        f.write_text("function getData() {}\nclass Foo {}")
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        enable_file_cache()
        try:
            assert is_file_cache_enabled()
            build_review_context(tmp_path, mock_lang, empty_state)
            assert is_file_cache_enabled()  # Still enabled — didn't stomp caller
        finally:
            disable_file_cache()

    def test_prepare_caches_across_phases(self, mock_lang, empty_state, tmp_path):
        """prepare_review should enable cache for context + selection + extraction."""
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        assert not is_file_cache_enabled()
        prepare_review(tmp_path, mock_lang, empty_state)
        assert not is_file_cache_enabled()  # Cleaned up after


# ── Headline bug fix test ────────────────────────────────────────


class TestHeadlineBugFix:
    def test_headline_no_typeerror_when_headline_none_with_review_suffix(self):
        """Regression: None + review_suffix shouldn't TypeError."""
        # Force: no security prefix, headline_inner returns None, review_suffix non-empty
        # stagnation + review findings + conditions that make headline_inner return None
        result = _compute_headline(
            "stagnation",
            {},
            {},
            None,
            None,
            None,
            None,  # obj_strict=None → headline_inner falls through to None
            {"open": 0},
            [],
            open_by_detector={"review": 5},
        )
        # Should not crash — may return None or a string with review suffix
        if result is not None:
            assert isinstance(result, str)

    def test_headline_review_only_no_security_no_inner(self):
        """When only review_suffix exists, returns it cleanly."""
        result = _compute_headline(
            "stagnation",
            {},
            {},
            None,
            None,
            None,
            None,
            {"open": 0},
            [],
            open_by_detector={"review": 3},
        )
        if result is not None:
            assert "review finding" in result.lower()
            assert "3" in result
