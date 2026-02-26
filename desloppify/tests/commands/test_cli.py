"""Tests for desloppify.cli — argument parsing, state path resolution, helpers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import desloppify.app.commands.helpers.lang as lang_helpers_mod
import desloppify.cli as cli_mod
from desloppify.app.commands.helpers.lang import resolve_lang, resolve_lang_settings
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime_options import resolve_lang_runtime_options
from desloppify.app.commands.helpers.score import (
    coerce_target_score,
    target_strict_score_from_config,
)
from desloppify.cli import (
    _apply_persisted_exclusions,
    _get_detector_names,
    _resolve_default_path,
    create_parser,
    state_path,
)
from desloppify.languages.csharp import CSharpConfig

# ===========================================================================
# Module import
# ===========================================================================


class TestModuleImport:
    def test_module_importable(self):
        """Verify the cli module can be imported without side effects."""
        assert hasattr(cli_mod, "main")
        assert hasattr(cli_mod, "create_parser")


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
        assert args.reset_subjective is False
        assert args.skip_slow is False
        assert args.profile is None

    def test_scan_with_path_and_skip_slow(self, parser):
        args = parser.parse_args(["scan", "--path", "/tmp/mycode", "--skip-slow"])
        assert args.path == "/tmp/mycode"
        assert args.skip_slow is True

    def test_scan_with_reset_subjective_flag(self, parser):
        args = parser.parse_args(["scan", "--reset-subjective"])
        assert args.reset_subjective is True

    def test_scan_rejects_legacy_deep_flag(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["scan", "--deep"])

    def test_scan_with_profile(self, parser):
        args = parser.parse_args(["scan", "--profile", "ci"])
        assert args.profile == "ci"

    def test_scan_with_lang_opt(self, parser):
        args = parser.parse_args(["scan", "--lang-opt", "foo=bar", "--lang-opt", "x=1"])
        assert args.lang_opt == ["foo=bar", "x=1"]

    def test_scan_rejects_language_specific_legacy_flag(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["scan", "--roslyn-cmd", "legacy"])

    def test_scan_with_lang(self, parser):
        args = parser.parse_args(["--lang", "python", "scan"])
        assert args.lang == "python"

    def test_scan_rejects_subcommand_lang_position(self, parser, capsys):
        with pytest.raises(SystemExit):
            parser.parse_args(["scan", "--lang", "python"])
        err = capsys.readouterr().err
        assert "unrecognized arguments" in err
        assert "--lang" in err

    def test_scan_with_exclude(self, parser):
        args = parser.parse_args(
            ["--exclude", "node_modules", "--exclude", "dist", "scan"]
        )
        assert args.exclude == ["node_modules", "dist"]

    def test_top_level_version_flag(self, parser, capsys):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--version"])
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith("desloppify")

    def test_top_level_short_version_flag(self, parser, capsys):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["-V"])
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith("desloppify")

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

    def test_next_with_scope_status_group_and_format(self, parser):
        args = parser.parse_args(
            [
                "next",
                "--scope",
                "src/core",
                "--status",
                "all",
                "--group",
                "file",
                "--format",
                "md",
            ]
        )
        assert args.scope == "src/core"
        assert args.status == "all"
        assert args.group == "file"
        assert args.format == "md"

    def test_next_with_explain_and_no_tier_fallback(self, parser):
        args = parser.parse_args(
            ["next", "--tier", "4", "--explain", "--no-tier-fallback"]
        )
        assert args.tier == 4
        assert args.explain is True
        assert args.no_tier_fallback is True

    def test_resolve_command(self, parser):
        args = parser.parse_args(["resolve", "fixed", "id1", "id2"])
        assert args.command == "resolve"
        assert args.status == "fixed"
        assert args.patterns == ["id1", "id2"]

    def test_resolve_open_command(self, parser):
        args = parser.parse_args(["resolve", "open", "id1"])
        assert args.command == "resolve"
        assert args.status == "open"
        assert args.patterns == ["id1"]

    def test_resolve_with_note(self, parser):
        args = parser.parse_args(["resolve", "wontfix", "id1", "--note", "intentional"])
        assert args.note == "intentional"

    def test_resolve_with_attest(self, parser):
        args = parser.parse_args(
            [
                "resolve",
                "fixed",
                "id1",
                "--attest",
                "I have actually fixed this and I am not gaming",
            ]
        )
        assert args.attest is not None

    def test_ignore_command(self, parser):
        args = parser.parse_args(["ignore", "smells::*::async_no_await"])
        assert args.command == "ignore"
        assert args.pattern == "smells::*::async_no_await"

    def test_ignore_with_attest(self, parser):
        args = parser.parse_args(
            [
                "ignore",
                "smells::*::async_no_await",
                "--attest",
                "I have actually reviewed this and I am not gaming",
            ]
        )
        assert args.attest is not None

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
        args = parser.parse_args(
            [
                "tree",
                "--depth",
                "4",
                "--focus",
                "shared/components",
                "--min-loc",
                "100",
                "--sort",
                "findings",
                "--detail",
            ]
        )
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

    def test_detect_with_lang_opt(self, parser):
        args = parser.parse_args(["detect", "deps", "--lang-opt", "foo=bar"])
        assert args.lang_opt == ["foo=bar"]

    def test_detect_rejects_language_specific_legacy_flag(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["detect", "deps", "--roslyn-cmd", "legacy"])

    def test_lang_opt_parsed_for_csharp(self):
        args = SimpleNamespace(lang_opt=["roslyn_cmd=fake-roslyn --json"])
        options = resolve_lang_runtime_options(args, CSharpConfig())
        assert options["roslyn_cmd"] == "fake-roslyn --json"

    def test_lang_opt_rejects_invalid_key_value_pair(self, capsys):
        args = SimpleNamespace(lang_opt=["not_a_pair"])
        with pytest.raises(SystemExit) as exc:
            resolve_lang_runtime_options(args, CSharpConfig())
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "Invalid --lang-opt" in err
        assert "Expected KEY=VALUE" in err

    def test_language_settings_loaded_from_config_namespace(self):
        lang = CSharpConfig()
        config = {
            "languages": {
                "csharp": {
                    "corroboration_min_signals": 3,
                    "high_fanout_threshold": 8,
                }
            }
        }
        settings = resolve_lang_settings(config, lang)
        assert settings["corroboration_min_signals"] == 3
        assert settings["high_fanout_threshold"] == 8

    def test_move_command(self, parser):
        args = parser.parse_args(["move", "src/foo.py", "src/bar/foo.py", "--dry-run"])
        assert args.command == "move"
        assert args.source == "src/foo.py"
        assert args.dest == "src/bar/foo.py"
        assert args.dry_run is True

    def test_viz_command(self, parser):
        args = parser.parse_args(["viz"])
        assert args.command == "viz"

    def test_review_command_defaults(self, parser):
        args = parser.parse_args(["review"])
        assert args.command == "review"
        assert args.prepare is False
        assert args.import_file is None
        assert args.validate_import_file is None
        assert args.external_start is False
        assert args.external_submit is False
        assert args.session_id is None
        assert args.external_runner == "claude"
        assert args.session_ttl_hours == 24
        assert args.allow_partial is False
        assert args.manual_override is False
        assert args.attested_external is False
        assert args.attest is None
        assert args.retrospective is False
        assert args.retrospective_max_issues == 30
        assert args.retrospective_max_batch_items == 20

    def test_review_prepare_flag(self, parser):
        args = parser.parse_args(["review", "--prepare"])
        assert args.prepare is True

    def test_review_allow_partial_flag(self, parser):
        args = parser.parse_args(["review", "--import", "findings.json", "--allow-partial"])
        assert args.import_file == "findings.json"
        assert args.allow_partial is True

    def test_review_validate_import_flag(self, parser):
        args = parser.parse_args(["review", "--validate-import", "findings.json"])
        assert args.validate_import_file == "findings.json"

    def test_review_external_start_flag(self, parser):
        args = parser.parse_args(
            [
                "review",
                "--external-start",
                "--external-runner",
                "claude",
                "--session-ttl-hours",
                "12",
            ]
        )
        assert args.external_start is True
        assert args.external_runner == "claude"
        assert args.session_ttl_hours == 12

    def test_review_external_submit_flag(self, parser):
        args = parser.parse_args(
            [
                "review",
                "--external-submit",
                "--session-id",
                "ext_20260223_000000_deadbeef",
                "--import",
                "findings.json",
            ]
        )
        assert args.external_submit is True
        assert args.session_id == "ext_20260223_000000_deadbeef"
        assert args.import_file == "findings.json"

    def test_review_manual_override_flag(self, parser):
        args = parser.parse_args(
            [
                "review",
                "--import",
                "findings.json",
                "--manual-override",
                "--attest",
                "manual calibration justified by independent reviewer output",
            ]
        )
        assert args.manual_override is True
        assert isinstance(args.attest, str)

    def test_review_attested_external_flag(self, parser):
        args = parser.parse_args(
            [
                "review",
                "--import",
                "findings.json",
                "--attested-external",
                "--attest",
                "I validated this review was completed without awareness of overall score and is unbiased.",
            ]
        )
        assert args.attested_external is True
        assert isinstance(args.attest, str)

    def test_issues_command_defaults(self, parser):
        args = parser.parse_args(["issues"])
        assert args.command == "issues"
        assert args.issues_action is None

    def test_issues_accepts_state_file_flag(self, parser):
        args = parser.parse_args(["issues", "--state-file", ".desloppify/state.json"])
        assert args.command == "issues"
        assert args.state == ".desloppify/state.json"

    def test_issues_deprecated_state_flag_still_works(self, parser, capsys):
        args = parser.parse_args(["issues", "--state", ".desloppify/state.json"])
        assert args.command == "issues"
        assert args.state == ".desloppify/state.json"
        err = capsys.readouterr().err
        assert "deprecated" in err
        assert "--state" in err

    def test_issues_rejects_status_like_state_path(self, parser, capsys):
        with pytest.raises(SystemExit):
            parser.parse_args(["issues", "--state-file", "resolved"])
        err = capsys.readouterr().err
        assert "looks like a status value" in err
        assert "--state-file" in err

    def test_issues_show_subcommand(self, parser):
        args = parser.parse_args(["issues", "show", "3"])
        assert args.command == "issues"
        assert args.issues_action == "show"
        assert args.number == 3

    def test_issues_list_subcommand(self, parser):
        args = parser.parse_args(["issues", "list"])
        assert args.command == "issues"
        assert args.issues_action == "list"

    def test_issues_update_subcommand(self, parser):
        args = parser.parse_args(["issues", "update", "2", "--file", "analysis.md"])
        assert args.command == "issues"
        assert args.issues_action == "update"
        assert args.number == 2
        assert args.file == "analysis.md"

    def test_issues_merge_subcommand(self, parser):
        args = parser.parse_args(["issues", "merge", "--dry-run", "--similarity", "0.9"])
        assert args.command == "issues"
        assert args.issues_action == "merge"
        assert args.dry_run is True
        assert args.similarity == 0.9

    def test_config_command_defaults(self, parser):
        args = parser.parse_args(["config"])
        assert args.command == "config"
        assert args.config_action is None

    def test_config_set_subcommand(self, parser):
        args = parser.parse_args(["config", "set", "review_max_age_days", "14"])
        assert args.command == "config"
        assert args.config_action == "set"
        assert args.config_key == "review_max_age_days"
        assert args.config_value == "14"

    def test_config_unset_subcommand(self, parser):
        args = parser.parse_args(["config", "unset", "review_max_age_days"])
        assert args.command == "config"
        assert args.config_action == "unset"
        assert args.config_key == "review_max_age_days"

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

    def test_dev_scaffold_lang(self, parser):
        args = parser.parse_args(
            [
                "dev",
                "scaffold-lang",
                "ruby",
                "--extension",
                ".rb",
                "--extension",
                ".rake",
                "--marker",
                "Gemfile",
                "--default-src",
                "lib",
                "--force",
            ]
        )
        assert args.command == "dev"
        assert args.dev_action == "scaffold-lang"
        assert args.name == "ruby"
        assert args.extension == [".rb", ".rake"]
        assert args.marker == ["Gemfile"]
        assert args.default_src == "lib"
        assert args.force is True
        assert args.wire_pyproject is True

    def test_dev_scaffold_lang_no_wire_pyproject(self, parser):
        args = parser.parse_args(
            ["dev", "scaffold-lang", "go", "--extension", ".go", "--no-wire-pyproject"]
        )
        assert args.wire_pyproject is False

    def test_dev_requires_action(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["dev"])

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
# _get_detector_names (lazy)
# ===========================================================================


class TestDetectorNames:
    def test_is_non_empty_list(self):
        names = _get_detector_names()
        assert isinstance(names, list)
        assert len(names) > 0

    def test_contains_known_detectors(self):
        names = _get_detector_names()
        for name in ["logs", "unused", "smells", "cycles", "dupes"]:
            assert name in names


# ===========================================================================
# state_path
# ===========================================================================


class TestStatePath:
    def test_auto_detects_lang_when_no_state_or_lang(self):
        """state_path auto-detects language and returns lang-specific path."""
        args = SimpleNamespace()
        # When auto_detect_lang finds a language, state_path returns lang-specific path
        with patch("desloppify.languages.auto_detect_lang", return_value="python"):
            result = state_path(args)
            assert result is not None
            assert "state-python.json" in str(result)
        # When auto_detect_lang finds nothing, state_path returns None
        with patch("desloppify.languages.auto_detect_lang", return_value=None):
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

    def test_non_scan_falls_back_to_sole_existing_lang_state(
        self, monkeypatch, tmp_path
    ):
        state_dir = tmp_path / ".desloppify"
        state_dir.mkdir()
        existing = state_dir / "state-typescript.json"
        existing.write_text("{}")
        monkeypatch.setattr("desloppify.app.commands.helpers.state.PROJECT_ROOT", tmp_path)

        args = SimpleNamespace(state=None, lang="python", command="status")
        result = state_path(args)
        assert result == existing

    def test_scan_does_not_fallback_to_other_lang_state(self, monkeypatch, tmp_path):
        state_dir = tmp_path / ".desloppify"
        state_dir.mkdir()
        (state_dir / "state-typescript.json").write_text("{}")
        monkeypatch.setattr("desloppify.app.commands.helpers.state.PROJECT_ROOT", tmp_path)

        args = SimpleNamespace(state=None, lang="python", command="scan")
        result = state_path(args)
        assert result == state_dir / "state-python.json"

    def test_non_scan_without_lang_uses_sole_existing_state(
        self, monkeypatch, tmp_path
    ):
        state_dir = tmp_path / ".desloppify"
        state_dir.mkdir()
        existing = state_dir / "state-python.json"
        existing.write_text("{}")
        monkeypatch.setattr("desloppify.app.commands.helpers.state.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.auto_detect_lang_name",
            lambda _args: None,
        )

        args = SimpleNamespace(state=None, lang=None, command="status")
        result = state_path(args)
        assert result == existing

    def test_non_scan_with_ambiguous_existing_states_keeps_resolved_lang_path(
        self, monkeypatch, tmp_path
    ):
        state_dir = tmp_path / ".desloppify"
        state_dir.mkdir()
        (state_dir / "state-python.json").write_text("{}")
        (state_dir / "state-typescript.json").write_text("{}")
        monkeypatch.setattr("desloppify.app.commands.helpers.state.PROJECT_ROOT", tmp_path)

        args = SimpleNamespace(state=None, lang="csharp", command="status")
        result = state_path(args)
        assert result == state_dir / "state-csharp.json"


class TestResolveDefaultPath:
    """Tests for _resolve_default_path — especially the review-command scan_path fix."""

    def test_does_nothing_when_path_already_set(self):
        args = SimpleNamespace(command="review", path="/explicit/path")
        _resolve_default_path(args)
        assert args.path == "/explicit/path"

    def test_review_uses_scan_path_from_state(self, monkeypatch, tmp_path):
        """Regression test for issue #127: review --prepare should use last scan path."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        # Simulate a project with files at the root (no src/ subdir)
        (project_root / "server.ts").write_text("export {}")
        saved_state = {"scan_path": "."}  # scan was run with --path .

        monkeypatch.setattr(cli_mod, "PROJECT_ROOT", project_root)
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.PROJECT_ROOT", project_root
        )

        with (
            patch("desloppify.cli.state_path", return_value=tmp_path / "state.json"),
            patch("desloppify.cli.load_state", return_value=saved_state),
        ):
            args = SimpleNamespace(command="review", path=None)
            _resolve_default_path(args)

        assert args.path == str(project_root.resolve())

    def test_review_falls_back_to_lang_default_when_no_scan_path(self, monkeypatch):
        """When state has no scan_path, review falls back to lang.default_src."""
        with (
            patch("desloppify.cli.state_path", return_value=None),
            patch("desloppify.cli.load_state", return_value={}),
            patch("desloppify.cli.resolve_lang") as mock_lang,
        ):
            mock_lang.return_value = SimpleNamespace(default_src="src")
            args = SimpleNamespace(command="review", path=None)
            _resolve_default_path(args)

        assert args.path.endswith("src")

    def test_review_falls_back_when_state_load_raises(self, monkeypatch):
        """If state cannot be loaded, path resolution continues without crashing."""
        with (
            patch("desloppify.cli.state_path", return_value=None),
            patch("desloppify.cli.load_state", side_effect=OSError("no file")),
            patch("desloppify.cli.resolve_lang") as mock_lang,
        ):
            mock_lang.return_value = SimpleNamespace(default_src="src")
            args = SimpleNamespace(command="review", path=None)
            _resolve_default_path(args)  # must not raise

        assert args.path.endswith("src")

    def test_non_review_command_uses_lang_default(self):
        with patch("desloppify.cli.resolve_lang") as mock_lang:
            mock_lang.return_value = SimpleNamespace(default_src="src")
            args = SimpleNamespace(command="scan", path=None)
            _resolve_default_path(args)

        assert args.path.endswith("src")


class TestResolveLang:
    def test_prefers_explicit_lang(self):
        args = SimpleNamespace(lang="python", path="/tmp/somewhere")
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "python"

    def test_auto_detect_uses_path_when_it_looks_like_project_root(
        self, tmp_path, monkeypatch
    ):
        # CWD-style project root is python.
        cwd_root = tmp_path / "cwd_project"
        cwd_root.mkdir()
        (cwd_root / "pyproject.toml").write_text("[tool.pytest]\n")
        py_src = cwd_root / "src"
        py_src.mkdir()
        (py_src / "main.py").write_text("print('x')\n")

        # Target --path root is typescript.
        target_root = tmp_path / "target_project"
        target_root.mkdir()
        (target_root / "package.json").write_text('{"name": "target"}\n')
        ts_src = target_root / "src"
        ts_src.mkdir()
        (ts_src / "index.ts").write_text("export const x = 1\n")

        monkeypatch.setattr(lang_helpers_mod, "PROJECT_ROOT", cwd_root)
        monkeypatch.setattr("desloppify.utils.PROJECT_ROOT", cwd_root)
        args = SimpleNamespace(lang=None, path=str(target_root))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "typescript"

    def test_auto_detect_falls_back_to_project_root_for_subdir_path(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "project"
        root.mkdir()
        (root / "pyproject.toml").write_text("[tool.pytest]\n")
        src = root / "src"
        src.mkdir()
        (src / "main.py").write_text("print('x')\n")

        monkeypatch.setattr(lang_helpers_mod, "PROJECT_ROOT", root)
        monkeypatch.setattr("desloppify.utils.PROJECT_ROOT", root)
        args = SimpleNamespace(lang=None, path=str(src))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "python"

    def test_auto_detect_walks_up_from_external_subdir_path(
        self, tmp_path, monkeypatch
    ):
        # CWD-style project root is python.
        cwd_root = tmp_path / "cwd_project"
        cwd_root.mkdir()
        (cwd_root / "pyproject.toml").write_text("[tool.pytest]\n")
        (cwd_root / "local.py").write_text("print('local')\n")

        # External target is typescript, and --path points to target/src.
        target_root = tmp_path / "target_project"
        target_root.mkdir()
        (target_root / "package.json").write_text('{"name":"target"}\n')
        target_src = target_root / "src"
        target_src.mkdir()
        (target_src / "index.ts").write_text("export const x = 1\n")

        monkeypatch.setattr(lang_helpers_mod, "PROJECT_ROOT", cwd_root)
        monkeypatch.setattr("desloppify.utils.PROJECT_ROOT", cwd_root)
        args = SimpleNamespace(lang=None, path=str(target_src))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "typescript"

    def test_auto_detect_prefers_path_subtree_when_no_markers(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "project"
        root.mkdir()

        # No marker files anywhere in this repo-style tree.
        ts_dir = root / "web"
        ts_dir.mkdir()
        for i in range(3):
            (ts_dir / f"view_{i}.ts").write_text("export const x = 1\n")

        py_dir = root / "scripts"
        py_dir.mkdir()
        for i in range(2):
            (py_dir / f"job_{i}.py").write_text("print('x')\n")

        monkeypatch.setattr(lang_helpers_mod, "PROJECT_ROOT", root)
        monkeypatch.setattr("desloppify.utils.PROJECT_ROOT", root)

        # Path points to python subtree; detection should use this subtree first,
        # not the entire repo where TypeScript files are more numerous.
        args = SimpleNamespace(lang=None, path=str(py_dir))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "python"

    def test_lang_config_markers_include_plugin_markers(self, monkeypatch):
        class DummyCfg:
            detect_markers = ["deno.json", "custom.lock"]

        lang_helpers_mod._lang_config_markers.cache_clear()
        monkeypatch.setattr("desloppify.languages.available_langs", lambda: ["dummy"])
        monkeypatch.setattr("desloppify.languages.get_lang", lambda _name: DummyCfg())

        markers = lang_helpers_mod._lang_config_markers()
        assert "deno.json" in markers
        assert "custom.lock" in markers

        lang_helpers_mod._lang_config_markers.cache_clear()

    def test_resolve_detection_root_uses_plugin_marker(self, tmp_path, monkeypatch):
        cwd_root = tmp_path / "cwd_project"
        cwd_root.mkdir()
        (cwd_root / "pyproject.toml").write_text("[tool.pytest]\n")

        target_root = tmp_path / "target_project"
        target_root.mkdir()
        (target_root / "deno.json").write_text("{}\n")
        target_src = target_root / "src"
        target_src.mkdir()

        monkeypatch.setattr(lang_helpers_mod, "PROJECT_ROOT", cwd_root)
        monkeypatch.setattr(
            lang_helpers_mod, "_lang_config_markers", lambda: ("deno.json",)
        )

        args = SimpleNamespace(path=str(target_src))
        resolved = lang_helpers_mod.resolve_detection_root(args)
        assert resolved == target_root


class TestTargetScoreHelpers:
    def test_coerce_target_score_handles_invalid_inputs(self):
        assert coerce_target_score(None) == 95.0
        assert coerce_target_score("  ") == 95.0
        assert coerce_target_score("bad", fallback=97.0) == 97.0
        assert coerce_target_score(True, fallback=96.0) == 96.0

    def test_coerce_target_score_clamps_range(self):
        assert coerce_target_score(-1) == 0.0
        assert coerce_target_score(120) == 100.0
        assert coerce_target_score("99.5") == 99.5

    def test_target_strict_score_from_config_uses_fallbacks(self):
        assert target_strict_score_from_config(None) == 95.0
        assert target_strict_score_from_config({"target_strict_score": None}) == 95.0
        assert target_strict_score_from_config({"target_strict_score": "97"}) == 97.0
        assert target_strict_score_from_config({"target_strict_score": 120}) == 100.0


# ===========================================================================
# write_query
# ===========================================================================


class TestWriteQuery:
    def test_writes_valid_json(self, tmp_path, monkeypatch):
        query_file = tmp_path / ".desloppify" / "query.json"
        monkeypatch.setattr("desloppify.app.commands.helpers.query.QUERY_FILE", query_file)

        data = {"results": [1, 2, 3], "count": 3}
        write_query(data)

        assert query_file.exists()
        loaded = json.loads(query_file.read_text())
        assert loaded["results"] == [1, 2, 3]
        assert loaded["count"] == 3

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        query_file = tmp_path / "deep" / "nested" / "query.json"
        monkeypatch.setattr("desloppify.app.commands.helpers.query.QUERY_FILE", query_file)

        write_query({"ok": True})
        assert query_file.exists()

    def test_handles_write_error_gracefully(self, tmp_path, monkeypatch):
        """If the file cannot be written, no exception should escape."""
        query_file = Path("/nonexistent/readonly/path/query.json")
        monkeypatch.setattr("desloppify.app.commands.helpers.query.QUERY_FILE", query_file)

        # Should not raise
        write_query({"data": 1})


# ===========================================================================
# _apply_persisted_exclusions
# ===========================================================================


class TestApplyPersistedExclusions:
    def test_cli_exclusions_applied(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "desloppify.file_discovery.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["node_modules", "dist"])
        config = {"exclude": []}
        _apply_persisted_exclusions(args, config)
        assert "node_modules" in captured
        assert "dist" in captured

    def test_persisted_exclusions_merged(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "desloppify.file_discovery.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["cli_only"])
        config = {"exclude": ["persisted_one"]}
        _apply_persisted_exclusions(args, config)
        assert "cli_only" in captured
        assert "persisted_one" in captured

    def test_no_duplicates_in_combined(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "desloppify.file_discovery.set_exclusions", lambda pats: captured.extend(pats)
        )
        args = SimpleNamespace(exclude=["shared"])
        config = {"exclude": ["shared"]}
        _apply_persisted_exclusions(args, config)
        assert captured.count("shared") == 1

    def test_no_exclusions_does_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            "desloppify.file_discovery.set_exclusions", lambda pats: called.append(pats)
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
            "desloppify.file_discovery.set_exclusions", lambda pats: captured.extend(pats)
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
