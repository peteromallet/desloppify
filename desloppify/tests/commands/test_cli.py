"""Tests for desloppify.cli — argument parsing, state path resolution, helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import desloppify.app.commands.helpers.lang as lang_helpers_mod
import desloppify.cli as cli_mod
from desloppify.app.commands.helpers.lang import resolve_lang, resolve_lang_settings
from desloppify.app.commands.helpers.runtime_options import (
    LangRuntimeOptionsError,
    resolve_lang_runtime_options,
)
from desloppify.cli import (
    _get_detector_names,
    _running_installed_package_from_checkout,
    _resolve_default_path,
    _warn_if_running_installed_package_from_checkout,
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


class TestInstalledPackageCheckoutWarning:
    def test_detects_installed_package_running_from_checkout(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "desloppify").mkdir()
        (tmp_path / "desloppify" / "__init__.py").write_text("__all__ = []\n")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "desloppify"\nversion = "0.0.0"\n'
        )

        assert _running_installed_package_from_checkout(
            cwd_root=tmp_path,
            module_file="/tmp/site-packages/desloppify/cli.py",
        )

    def test_does_not_flag_local_checkout_execution(self, tmp_path: Path) -> None:
        (tmp_path / "desloppify").mkdir()
        (tmp_path / "desloppify" / "__init__.py").write_text("__all__ = []\n")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "desloppify"\nversion = "0.0.0"\n'
        )

        assert not _running_installed_package_from_checkout(
            cwd_root=tmp_path,
            module_file=tmp_path / "desloppify" / "cli.py",
        )

    def test_does_not_flag_non_checkout_project(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "other-project"\nversion = "0.0.0"\n'
        )

        assert not _running_installed_package_from_checkout(
            cwd_root=tmp_path,
            module_file="/tmp/site-packages/desloppify/cli.py",
        )

    def test_warns_when_running_installed_package_from_checkout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        (tmp_path / "desloppify").mkdir()
        (tmp_path / "desloppify" / "__init__.py").write_text("__all__ = []\n")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "desloppify"\nversion = "0.0.0"\n'
        )

        monkeypatch.setattr(cli_mod, "get_project_root", lambda: tmp_path)
        monkeypatch.setattr(cli_mod, "__file__", "/tmp/site-packages/desloppify/cli.py")

        _warn_if_running_installed_package_from_checkout()

        err = capsys.readouterr().err
        assert "running installed desloppify package" in err
        assert "python -m desloppify" in err


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
        assert "\nPython " in out
        assert " at " in out

    def test_top_level_short_version_flag(self, parser, capsys):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["-V"])
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith("desloppify")
        assert "\nPython " in out
        assert " at " in out

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
        assert args.count == 1

    def test_backlog_command(self, parser):
        args = parser.parse_args(["backlog"])
        assert args.command == "backlog"
        assert args.count == 1

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

    def test_plan_resolve_command(self, parser):
        args = parser.parse_args(["plan", "resolve", "id1", "id2"])
        assert args.command == "plan"
        assert args.plan_action == "resolve"
        assert args.patterns == ["id1", "id2"]

    def test_plan_resolve_with_note(self, parser):
        args = parser.parse_args(["plan", "resolve", "id1", "--note", "removed import"])
        assert args.note == "removed import"

    def test_plan_resolve_with_attest(self, parser):
        args = parser.parse_args(
            [
                "plan",
                "resolve",
                "id1",
                "--attest",
                "I have actually fixed this and I am not gaming",
            ]
        )
        assert args.attest is not None

    def test_resolve_not_top_level(self, parser):
        """resolve is no longer a top-level command."""
        import pytest

        with pytest.raises(SystemExit):
            parser.parse_args(["resolve", "fixed", "id1"])

    def test_suppress_command(self, parser):
        args = parser.parse_args(["suppress", "smells::*::async_no_await"])
        assert args.command == "suppress"
        assert args.pattern == "smells::*::async_no_await"

    def test_suppress_with_attest(self, parser):
        args = parser.parse_args(
            [
                "suppress",
                "smells::*::async_no_await",
                "--attest",
                "I have actually reviewed this and I am not gaming",
            ]
        )
        assert args.attest is not None

    def test_autofix_command(self, parser):
        args = parser.parse_args(["autofix", "unused_imports", "--dry-run"])
        assert args.command == "autofix"
        assert args.fixer == "unused_imports"
        assert args.dry_run is True

    def test_plan_command(self, parser):
        args = parser.parse_args(["plan"])
        assert args.command == "plan"

    def test_plan_triage_parses_flags(self, parser):
        args = parser.parse_args(
            ["plan", "triage", "--stage", "observe", "--report", "analysis"]
        )
        assert args.command == "plan"
        assert args.plan_action == "triage"
        assert args.stage == "observe"
        assert args.report == "analysis"

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
                "issues",
                "--detail",
            ]
        )
        assert args.depth == 4
        assert args.focus == "shared/components"
        assert args.min_loc == 100
        assert args.sort == "issues"
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

    def test_lang_opt_rejects_invalid_key_value_pair(self):
        args = SimpleNamespace(lang_opt=["not_a_pair"])
        with pytest.raises(LangRuntimeOptionsError) as exc:
            resolve_lang_runtime_options(args, CSharpConfig())
        assert "Invalid --lang-opt" in str(exc.value)
        assert "Expected KEY=VALUE" in str(exc.value)

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
        assert args.retrospective is True
        assert args.retrospective_max_issues == 30
        assert args.retrospective_max_batch_items == 20

    def test_review_prepare_flag(self, parser):
        args = parser.parse_args(["review", "--prepare"])
        assert args.prepare is True

    def test_review_allow_partial_flag(self, parser):
        args = parser.parse_args(["review", "--import", "issues.json", "--allow-partial"])
        assert args.import_file == "issues.json"
        assert args.allow_partial is True

    def test_review_validate_import_flag(self, parser):
        args = parser.parse_args(["review", "--validate-import", "issues.json"])
        assert args.validate_import_file == "issues.json"

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
                "issues.json",
            ]
        )
        assert args.external_submit is True
        assert args.session_id == "ext_20260223_000000_deadbeef"
        assert args.import_file == "issues.json"

    def test_review_manual_override_flag(self, parser):
        args = parser.parse_args(
            [
                "review",
                "--import",
                "issues.json",
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
                "issues.json",
                "--attested-external",
                "--attest",
                "I validated this review was completed without awareness of overall score and is unbiased.",
            ]
        )
        assert args.attested_external is True
        assert isinstance(args.attest, str)

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

    def test_missing_command_defaults_to_none(self, parser):
        args = parser.parse_args([])
        assert args.command is None

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

    def test_runtime_detector_registration_invalidates_cached_detector_names(self):
        from desloppify.base.registry import (
            DetectorMeta,
            register_detector,
            unregister_detector,
        )

        test_detector = "_test_cli_cache_refresh"
        cli_mod._DETECTOR_NAMES_CACHE["names"] = ["stale_only"]
        register_detector(
            DetectorMeta(
                name=test_detector,
                display="cache-refresh",
                dimension="Code quality",
                action_type="manual_fix",
                guidance="cache refresh regression test",
            )
        )
        assert "names" not in cli_mod._DETECTOR_NAMES_CACHE
        assert test_detector in _get_detector_names()

        # Cleanup dynamic detector mutation for test isolation.
        unregister_detector(test_detector)


# ===========================================================================
# state_path
# ===========================================================================


class TestStatePath:
    def test_auto_detects_lang_when_no_state_or_lang(self):
        """state_path auto-detects language and returns lang-specific path."""
        args = SimpleNamespace()
        # When auto_detect_lang finds a language, state_path returns lang-specific path
        with patch("desloppify.app.commands.helpers.state.auto_detect_lang_name", return_value="python"):
            result = state_path(args)
            assert result is not None
            assert "state-python.json" in str(result)
        # When auto_detect_lang finds nothing, state_path returns None
        with patch("desloppify.app.commands.helpers.state.auto_detect_lang_name", return_value=None), \
             patch("desloppify.app.commands.helpers.state._sole_existing_lang_state_file", return_value=None):
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
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.get_project_root",
            lambda: tmp_path,
        )

        args = SimpleNamespace(state=None, lang="python", command="status")
        result = state_path(args)
        assert result == existing

    def test_scan_does_not_fallback_to_other_lang_state(self, monkeypatch, tmp_path):
        state_dir = tmp_path / ".desloppify"
        state_dir.mkdir()
        (state_dir / "state-typescript.json").write_text("{}")
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.get_project_root",
            lambda: tmp_path,
        )

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
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.get_project_root",
            lambda: tmp_path,
        )
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
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.get_project_root",
            lambda: tmp_path,
        )

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

        monkeypatch.setattr(cli_mod, "get_project_root", lambda: project_root)
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.state.get_project_root",
            lambda: project_root,
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

    def test_non_review_command_honors_language_default_src_exactly(
        self, monkeypatch, tmp_path
    ):
        project_root = tmp_path / "proj"
        project_root.mkdir()
        monkeypatch.setattr(cli_mod, "get_project_root", lambda: project_root)
        with patch("desloppify.cli.resolve_lang") as mock_lang:
            mock_lang.return_value = SimpleNamespace(default_src=".")
            args = SimpleNamespace(command="scan", path=None)
            _resolve_default_path(args)

        assert args.path == str(project_root.resolve())


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

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: cwd_root)
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

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: root)
        args = SimpleNamespace(lang=None, path=str(src))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "python"

    def test_auto_detect_ignores_markers_above_active_project_root(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "package.json").write_text('{"name":"outside"}\n')

        project_root = tmp_path / "project"
        project_root.mkdir()
        scripts = project_root / "scripts"
        scripts.mkdir()
        (scripts / "job.py").write_text("print('x')\n")

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: project_root)
        args = SimpleNamespace(lang=None, path=str(scripts))

        assert lang_helpers_mod.resolve_detection_root(args) == scripts
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "python"

    def test_detection_root_includes_active_project_root_boundary(
        self, tmp_path, monkeypatch
    ):
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "package.json").write_text('{"name":"project"}\n')
        source = project_root / "src"
        source.mkdir()

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: project_root)
        args = SimpleNamespace(path=str(source))

        assert lang_helpers_mod.resolve_detection_root(args) == project_root

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

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: cwd_root)
        args = SimpleNamespace(lang=None, path=str(target_src))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "typescript"

    def test_detection_root_still_walks_to_external_target_marker(
        self, tmp_path, monkeypatch
    ):
        project_root = tmp_path / "active_project"
        project_root.mkdir()

        external_root = tmp_path / "external_project"
        external_root.mkdir()
        (external_root / "package.json").write_text('{"name":"target"}\n')
        external_src = external_root / "src"
        external_src.mkdir()

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: project_root)
        args = SimpleNamespace(path=str(external_src))

        assert lang_helpers_mod.resolve_detection_root(args) == external_root

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

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: root)

        # Path points to python subtree; detection should use this subtree first,
        # not the entire repo where TypeScript files are more numerous.
        args = SimpleNamespace(lang=None, path=str(py_dir))
        lang = resolve_lang(args)
        assert lang is not None
        assert lang.name == "python"

    def test_lang_config_markers_include_plugin_markers(self, monkeypatch):
        class DummyCfg:
            detect_markers = ["deno.json", "custom.lock"]

        monkeypatch.setattr("desloppify.languages.framework.available_langs", lambda: ["dummy"])
        monkeypatch.setattr("desloppify.languages.framework.get_lang", lambda _name: DummyCfg())

        markers = lang_helpers_mod._lang_config_markers()
        assert "deno.json" in markers
        assert "custom.lock" in markers

    def test_lang_config_markers_skips_broken_plugin(self, monkeypatch):
        monkeypatch.setattr("desloppify.languages.framework.available_langs", lambda: ["dummy"])
        monkeypatch.setattr(
            "desloppify.languages.framework.get_lang",
            lambda _name: (_ for _ in ()).throw(ImportError("broken plugin")),
        )

        markers = lang_helpers_mod._lang_config_markers()
        assert "deno.json" not in markers
        assert "custom.lock" not in markers

    def test_lang_config_markers_refresh_after_plugin_change(self, monkeypatch):
        class FirstCfg:
            detect_markers = ["deno.json"]

        class SecondCfg:
            detect_markers = ["bun.lockb"]

        current_cfg = FirstCfg

        monkeypatch.setattr("desloppify.languages.framework.available_langs", lambda: ["dummy"])
        monkeypatch.setattr(
            "desloppify.languages.framework.get_lang",
            lambda _name: current_cfg(),
        )

        first_markers = lang_helpers_mod._lang_config_markers()
        assert "deno.json" in first_markers
        assert "bun.lockb" not in first_markers

        current_cfg = SecondCfg
        second_markers = lang_helpers_mod._lang_config_markers()
        assert "bun.lockb" in second_markers
        assert "deno.json" not in second_markers

    def test_resolve_detection_root_uses_plugin_marker(self, tmp_path, monkeypatch):
        cwd_root = tmp_path / "cwd_project"
        cwd_root.mkdir()
        (cwd_root / "pyproject.toml").write_text("[tool.pytest]\n")

        target_root = tmp_path / "target_project"
        target_root.mkdir()
        (target_root / "deno.json").write_text("{}\n")
        target_src = target_root / "src"
        target_src.mkdir()

        monkeypatch.setattr(lang_helpers_mod, "get_project_root", lambda: cwd_root)
        monkeypatch.setattr(
            lang_helpers_mod, "_lang_config_markers", lambda: ("deno.json",)
        )

        args = SimpleNamespace(path=str(target_src))
        resolved = lang_helpers_mod.resolve_detection_root(args)
        assert resolved == target_root


# ===========================================================================
# _project_root_from_state_path
# ===========================================================================


class TestProjectRootFromStatePath:
    """Infer project root from an explicit --state path."""

    def test_language_state_file(self, tmp_path: Path):
        dot = tmp_path / ".desloppify"
        dot.mkdir()
        sf = dot / "state-python.json"
        sf.write_text("{}")
        from desloppify.cli import _project_root_from_state_path

        assert _project_root_from_state_path(str(sf)) == tmp_path

    def test_plain_state_file(self, tmp_path: Path):
        dot = tmp_path / ".desloppify"
        dot.mkdir()
        sf = dot / "state.json"
        sf.write_text("{}")
        from desloppify.cli import _project_root_from_state_path

        assert _project_root_from_state_path(str(sf)) == tmp_path

    def test_none_input(self):
        from desloppify.cli import _project_root_from_state_path

        assert _project_root_from_state_path(None) is None

    def test_empty_string(self):
        from desloppify.cli import _project_root_from_state_path

        assert _project_root_from_state_path("") is None

    def test_non_desloppify_dir(self, tmp_path: Path):
        sf = tmp_path / "other" / "state-python.json"
        sf.parent.mkdir()
        sf.write_text("{}")
        from desloppify.cli import _project_root_from_state_path

        assert _project_root_from_state_path(str(sf)) is None

    def test_unexpected_filename(self, tmp_path: Path):
        dot = tmp_path / ".desloppify"
        dot.mkdir()
        sf = dot / "config.json"
        sf.write_text("{}")
        from desloppify.cli import _project_root_from_state_path

        assert _project_root_from_state_path(str(sf)) is None
