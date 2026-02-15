"""Tests for desloppify.cli — argument parsing, state path resolution, helpers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from desloppify.commands._helpers import _write_query
from desloppify.cli import (
    DETECTOR_NAMES,
    _apply_persisted_exclusions,
    state_path,
    create_parser,
)


# ===========================================================================
# Module import
# ===========================================================================

class TestModuleImport:
    def test_module_importable(self):
        """Verify the cli module can be imported without side effects."""
        import desloppify.cli
        assert hasattr(desloppify.cli, "main")
        assert hasattr(desloppify.cli, "create_parser")


# ===========================================================================
# create_parser — argument parsing
# ===========================================================================

class TestCreateParser:
    @pytest.fixture()
    def parser(self):
        return create_parser()

    def test_scan_command_parses(self, parser):
        args = parser.parse_args(["scan"])
        assert args.command == "scan"
        assert args.path is None
        assert args.skip_slow is False

    def test_scan_with_path_and_skip_slow(self, parser):
        args = parser.parse_args(["scan", "--path", "/tmp/mycode", "--skip-slow"])
        assert args.path == "/tmp/mycode"
        assert args.skip_slow is True

    def test_scan_with_lang(self, parser):
        args = parser.parse_args(["--lang", "python", "scan"])
        assert args.lang == "python"

    def test_scan_with_exclude(self, parser):
        args = parser.parse_args(["--exclude", "node_modules", "--exclude", "dist", "scan"])
        assert args.exclude == ["node_modules", "dist"]

    def test_status_command(self, parser):
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_status_with_json_flag(self, parser):
        args = parser.parse_args(["status", "--json"])
        assert args.json is True

    def test_show_command_with_pattern(self, parser):
        args = parser.parse_args(["show", "src/foo.py"])
        assert args.command == "show"
        assert args.pattern == "src/foo.py"

    def test_show_command_default_status(self, parser):
        args = parser.parse_args(["show"])
        assert args.status == "open"

    def test_show_command_with_status_filter(self, parser):
        args = parser.parse_args(["show", "--status", "all"])
        assert args.status == "all"

    def test_show_chronic_flag(self, parser):
        args = parser.parse_args(["show", "--chronic"])
        assert args.chronic is True

    def test_next_command(self, parser):
        args = parser.parse_args(["next"])
        assert args.command == "next"
        assert args.tier is None
        assert args.count == 1

    def test_next_with_tier_and_count(self, parser):
        args = parser.parse_args(["next", "--tier", "2", "--count", "5"])
        assert args.tier == 2
        assert args.count == 5

    def test_resolve_command(self, parser):
        args = parser.parse_args(["resolve", "fixed", "id1", "id2"])
        assert args.command == "resolve"
        assert args.status == "fixed"
        assert args.patterns == ["id1", "id2"]

    def test_resolve_with_note(self, parser):
        args = parser.parse_args(["resolve", "wontfix", "id1", "--note", "intentional"])
        assert args.note == "intentional"

    def test_ignore_command(self, parser):
        args = parser.parse_args(["ignore", "smells::*::async_no_await"])
        assert args.command == "ignore"
        assert args.pattern == "smells::*::async_no_await"

    def test_fix_command(self, parser):
        args = parser.parse_args(["fix", "unused_imports", "--dry-run"])
        assert args.command == "fix"
        assert args.fixer == "unused_imports"
        assert args.dry_run is True

    def test_plan_command(self, parser):
        args = parser.parse_args(["plan"])
        assert args.command == "plan"

    def test_plan_with_output(self, parser):
        args = parser.parse_args(["plan", "--output", "plan.md"])
        assert args.output == "plan.md"

    def test_tree_command_defaults(self, parser):
        args = parser.parse_args(["tree"])
        assert args.command == "tree"
        assert args.depth == 2
        assert args.focus is None
        assert args.min_loc == 0
        assert args.sort == "loc"
        assert args.detail is False

    def test_tree_with_all_options(self, parser):
        args = parser.parse_args([
            "tree", "--depth", "4", "--focus", "shared/components",
            "--min-loc", "100", "--sort", "findings", "--detail",
        ])
        assert args.depth == 4
        assert args.focus == "shared/components"
        assert args.min_loc == 100
        assert args.sort == "findings"
        assert args.detail is True

    def test_detect_command(self, parser):
        args = parser.parse_args(["detect", "smells", "--top", "5"])
        assert args.command == "detect"
        assert args.detector == "smells"
        assert args.top == 5

    def test_detect_with_threshold(self, parser):
        args = parser.parse_args(["detect", "dupes", "--threshold", "0.85"])
        assert args.threshold == pytest.approx(0.85)

    def test_move_command(self, parser):
        args = parser.parse_args(["move", "src/foo.py", "src/bar/foo.py", "--dry-run"])
        assert args.command == "move"
        assert args.source == "src/foo.py"
        assert args.dest == "src/bar/foo.py"
        assert args.dry_run is True

    def test_viz_command(self, parser):
        args = parser.parse_args(["viz"])
        assert args.command == "viz"

    def test_zone_show(self, parser):
        args = parser.parse_args(["zone", "show"])
        assert args.command == "zone"
        assert args.zone_action == "show"

    def test_zone_set(self, parser):
        args = parser.parse_args(["zone", "set", "src/foo.py", "test"])
        assert args.zone_action == "set"
        assert args.zone_path == "src/foo.py"
        assert args.zone_value == "test"

    def test_zone_clear(self, parser):
        args = parser.parse_args(["zone", "clear", "src/foo.py"])
        assert args.zone_action == "clear"
        assert args.zone_path == "src/foo.py"

    def test_scan_badge_options(self, parser):
        args = parser.parse_args(["scan", "--no-badge", "--badge-path", "custom.png"])
        assert args.no_badge is True
        assert args.badge_path == "custom.png"

    def test_missing_command_raises(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_invalid_resolve_status_raises(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["resolve", "invalid_status", "id1"])


# ===========================================================================
# DETECTOR_NAMES
# ===========================================================================

class TestDetectorNames:
    def test_is_non_empty_list(self):
        assert isinstance(DETECTOR_NAMES, list)
        assert len(DETECTOR_NAMES) > 0

    def test_contains_known_detectors(self):
        for name in ["logs", "unused", "smells", "cycles", "dupes"]:
            assert name in DETECTOR_NAMES


# ===========================================================================
# state_path
# ===========================================================================

class TestStatePath:
    def test_auto_detects_lang_when_no_state_or_lang(self):
        """state_path auto-detects language and returns lang-specific path."""
        from unittest.mock import patch
        args = SimpleNamespace()
        # When auto_detect_lang finds a language, state_path returns lang-specific path
        with patch("desloppify.lang.auto_detect_lang", return_value="python"):
            result = state_path(args)
            assert result is not None
            assert "state-python.json" in str(result)
        # When auto_detect_lang finds nothing, state_path returns None
        with patch("desloppify.lang.auto_detect_lang", return_value=None):
            result = state_path(args)
            assert result is None

    def test_returns_explicit_state_path(self):
        args = SimpleNamespace(state="/tmp/custom.json")
        result = state_path(args)
        assert result == Path("/tmp/custom.json")

    def test_returns_lang_based_path_when_lang_set(self):
        args = SimpleNamespace(lang="python")
        result = state_path(args)
        assert result is not None
        assert "state-python.json" in str(result)
        assert ".desloppify" in str(result)

    def test_explicit_state_takes_precedence_over_lang(self):
        args = SimpleNamespace(state="/tmp/override.json", lang="python")
        result = state_path(args)
        assert result == Path("/tmp/override.json")


# ===========================================================================
# _write_query
# ===========================================================================

class TestWriteQuery:
    def test_writes_valid_json(self, tmp_path, monkeypatch):
        query_file = tmp_path / ".desloppify" / "query.json"
        monkeypatch.setattr("desloppify.commands._helpers.QUERY_FILE", query_file)

        data = {"results": [1, 2, 3], "count": 3}
        _write_query(data)

        assert query_file.exists()
        loaded = json.loads(query_file.read_text())
        assert loaded["results"] == [1, 2, 3]
        assert loaded["count"] == 3

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        query_file = tmp_path / "deep" / "nested" / "query.json"
        monkeypatch.setattr("desloppify.commands._helpers.QUERY_FILE", query_file)

        _write_query({"ok": True})
        assert query_file.exists()

    def test_handles_write_error_gracefully(self, tmp_path, monkeypatch):
        """If the file cannot be written, no exception should escape."""
        query_file = Path("/nonexistent/readonly/path/query.json")
        monkeypatch.setattr("desloppify.commands._helpers.QUERY_FILE", query_file)

        # Should not raise
        _write_query({"data": 1})


# ===========================================================================
# _apply_persisted_exclusions
# ===========================================================================

class TestApplyPersistedExclusions:
    def test_cli_exclusions_applied(self, monkeypatch):
        captured = []
        monkeypatch.setattr("desloppify.utils.set_exclusions",
                            lambda pats: captured.extend(pats))
        args = SimpleNamespace(exclude=["node_modules", "dist"])
        config = {"exclude": []}
        _apply_persisted_exclusions(args, config)
        assert "node_modules" in captured
        assert "dist" in captured

    def test_persisted_exclusions_merged(self, monkeypatch):
        captured = []
        monkeypatch.setattr("desloppify.utils.set_exclusions",
                            lambda pats: captured.extend(pats))
        args = SimpleNamespace(exclude=["cli_only"])
        config = {"exclude": ["persisted_one"]}
        _apply_persisted_exclusions(args, config)
        assert "cli_only" in captured
        assert "persisted_one" in captured

    def test_no_duplicates_in_combined(self, monkeypatch):
        captured = []
        monkeypatch.setattr("desloppify.utils.set_exclusions",
                            lambda pats: captured.extend(pats))
        args = SimpleNamespace(exclude=["shared"])
        config = {"exclude": ["shared"]}
        _apply_persisted_exclusions(args, config)
        assert captured.count("shared") == 1

    def test_no_exclusions_does_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr("desloppify.utils.set_exclusions",
                            lambda pats: called.append(pats))
        args = SimpleNamespace(exclude=None)
        config = {"exclude": []}
        _apply_persisted_exclusions(args, config)
        # set_exclusions should not be called if combined is empty
        assert len(called) == 0

    def test_missing_config_key_handled(self, monkeypatch):
        """Config with no 'exclude' key should not crash."""
        captured = []
        monkeypatch.setattr("desloppify.utils.set_exclusions",
                            lambda pats: captured.extend(pats))
        args = SimpleNamespace(exclude=["foo"])
        config = {}
        _apply_persisted_exclusions(args, config)
        assert "foo" in captured
