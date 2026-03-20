"""Tests for CLI helper utilities and smoke baseline parsing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from desloppify.app.commands.helpers.query import (
    load_query_result,
    write_query,
)
from desloppify.base.config import (
    coerce_target_score,
    target_strict_score_from_config,
)
from desloppify.cli import _apply_persisted_exclusions, create_parser


class TestTargetScoreHelpers:
    def test_coerce_target_score_handles_invalid_inputs(self):
        assert coerce_target_score(None) == 85.0
        assert coerce_target_score("  ") == 85.0
        assert coerce_target_score("bad", fallback=97.0) == 97.0
        assert coerce_target_score(True, fallback=96.0) == 96.0

    def test_coerce_target_score_clamps_range(self):
        assert coerce_target_score(-1) == 0.0
        assert coerce_target_score(120) == 100.0
        assert coerce_target_score("99.5") == 99.5

    def test_target_strict_score_from_config_uses_fallbacks(self):
        assert target_strict_score_from_config(None) == 85.0
        assert target_strict_score_from_config({"target_strict_score": None}) == 85.0
        assert target_strict_score_from_config({"target_strict_score": "97"}) == 97.0
        assert target_strict_score_from_config({"target_strict_score": 120}) == 100.0


# ===========================================================================
# write_query
# ===========================================================================


class TestWriteQuery:
    def test_writes_valid_json(self, tmp_path, monkeypatch):
        query_file = tmp_path / ".desloppify" / "query.json"
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.query.query_file_path",
            lambda: query_file,
        )

        data = {"results": [1, 2, 3], "count": 3}
        write_query(data)

        assert query_file.exists()
        loaded = json.loads(query_file.read_text())
        assert loaded["results"] == [1, 2, 3]
        assert loaded["count"] == 3

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        query_file = tmp_path / "deep" / "nested" / "query.json"
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.query.query_file_path",
            lambda: query_file,
        )

        write_query({"ok": True})
        assert query_file.exists()

    def test_handles_write_error_gracefully(self, tmp_path, monkeypatch):
        """If the file cannot be written, no exception should escape."""
        query_file = Path("/nonexistent/readonly/path/query.json")
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.query.query_file_path",
            lambda: query_file,
        )

        # Should not raise
        write_query({"data": 1})

    def test_load_query_result_returns_parse_error_contract(self, tmp_path, monkeypatch):
        query_file = tmp_path / ".desloppify" / "query.json"
        query_file.parent.mkdir(parents=True, exist_ok=True)
        query_file.write_text("{bad json", encoding="utf-8")
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.query.query_file_path",
            lambda: query_file,
        )

        result = load_query_result()
        assert result.ok is False
        assert result.payload is None
        assert result.error_kind == "query_parse_error"
        assert result.message

    def test_load_query_result_success_payload(self, tmp_path, monkeypatch):
        query_file = tmp_path / ".desloppify" / "query.json"
        query_file.parent.mkdir(parents=True, exist_ok=True)
        query_file.write_text(json.dumps({"command": "review"}), encoding="utf-8")
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.query.query_file_path",
            lambda: query_file,
        )

        result = load_query_result()
        assert result.ok is True
        assert result.error_kind is None
        assert result.payload == {"command": "review"}


# ===========================================================================
# _apply_persisted_exclusions
# ===========================================================================


class TestApplyPersistedExclusions:
    def test_cli_exclusions_applied(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "desloppify.cli.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["node_modules", "dist"])
        config = {"exclude": []}
        _apply_persisted_exclusions(args, config)
        assert "node_modules" in captured
        assert "dist" in captured

    def test_persisted_exclusions_merged(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "desloppify.cli.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["cli_only"])
        config = {"exclude": ["persisted_one"]}
        _apply_persisted_exclusions(args, config)
        assert "cli_only" in captured
        assert "persisted_one" in captured

    def test_no_duplicates_in_combined(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "desloppify.cli.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["shared"])
        config = {"exclude": ["shared"]}
        _apply_persisted_exclusions(args, config)
        assert captured.count("shared") == 1

    def test_no_exclusions_does_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            "desloppify.cli.set_exclusions", lambda pats: called.append(pats)
        )
        args = SimpleNamespace(exclude=None)
        config = {"exclude": []}
        _apply_persisted_exclusions(args, config)
        # set_exclusions should not be called if combined is empty
        assert len(called) == 0

    def test_missing_config_key_handled(self, monkeypatch):
        """Config with no 'exclude' key should not crash."""
        captured = []
        monkeypatch.setattr(
            "desloppify.cli.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["foo"])
        config = {}
        _apply_persisted_exclusions(args, config)
        assert "foo" in captured


class TestCliSmokeBaseline:
    def test_smoke_fixture_commands_parse(self):
        parser = create_parser()

        scan_args = parser.parse_args(
            [
                "--lang",
                "python",
                "scan",
                "--path",
                "desloppify/tests/fixtures/cli_smoke_project/src",
                "--state",
                "desloppify/tests/snapshots/cli_smoke/state-python.json",
                "--no-badge",
            ]
        )
        assert scan_args.command == "scan"
        assert scan_args.no_badge is True

        status_args = parser.parse_args(
            [
                "--lang",
                "python",
                "status",
                "--state",
                "desloppify/tests/snapshots/cli_smoke/state-python.json",
            ]
        )
        assert status_args.command == "status"

        review_args = parser.parse_args(
            [
                "--lang",
                "python",
                "review",
                "--prepare",
                "--path",
                "tests/fixtures/cli_smoke_project/src",
                "--state",
                "tests/snapshots/cli_smoke/state-python.json",
            ]
        )
        assert review_args.command == "review"
        assert review_args.prepare is True
