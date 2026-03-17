"""Direct unit tests for five transitive-only modules.

Covers:
- desloppify.engine._state.merge (MergeScanOptions, merge_scan)
- desloppify.intelligence.review.context_holistic.readers (_abs, _read_file_contents)
- desloppify.app.cli_support.parser_groups_admin/parser_groups (parser builders, helpers)
- desloppify.app.commands.move.apply (rollback, apply helpers)
- desloppify.languages._framework.base.shared_phases (entries_to_issues, log, find_external)
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import desloppify.app.cli_support.parser_groups as parser_groups_mod

# ── Module 3: parser_groups_admin ─────────────────────────────────────
import desloppify.app.cli_support.parser_groups_admin as parser_admin_mod

# ── Module 4: move_apply ──────────────────────────────────────────────
import desloppify.app.commands.move.apply as move_apply_mod

# ── Module 1: engine._state.merge ─────────────────────────────────────
import desloppify.engine._state.merge as merge_mod

# ── Module 2: readers ─────────────────────────────────────────────────
import desloppify.intelligence.review.context_holistic.readers as readers_mod

# ── Module 5: shared_phases ───────────────────────────────────────────
import desloppify.languages._framework.base.shared_phases as shared_phases_mod
from desloppify.engine._state.merge import MergeScanOptions, merge_scan

# =====================================================================
# Module 1: merge.py
# =====================================================================


class TestMergeScanOptions:
    """MergeScanOptions dataclass defaults."""

    def test_defaults(self):
        opts = MergeScanOptions()
        assert opts.lang is None
        assert opts.scan_path is None
        assert opts.force_resolve is False
        assert opts.exclude == ()
        assert opts.potentials is None
        assert opts.merge_potentials is False
        assert opts.codebase_metrics is None
        assert opts.include_slow is True
        assert opts.ignore is None
        assert opts.subjective_integrity_target is None
        assert opts.zone_lookup is None

    def test_override_values(self):
        opts = MergeScanOptions(
            lang="python",
            scan_path="src",
            force_resolve=True,
            exclude=("vendor/",),
            potentials={"smells": 100},
            merge_potentials=True,
            codebase_metrics={"files": 50},
            include_slow=False,
            ignore=["secret_*"],
            subjective_integrity_target=0.8,
            zone_lookup=lambda _path: "test",
        )
        assert opts.lang == "python"
        assert opts.scan_path == "src"
        assert opts.force_resolve is True
        assert opts.exclude == ("vendor/",)
        assert opts.potentials == {"smells": 100}
        assert opts.merge_potentials is True
        assert opts.codebase_metrics == {"files": 50}
        assert opts.include_slow is False
        assert opts.ignore == ["secret_*"]
        assert opts.subjective_integrity_target == 0.8
        assert callable(opts.zone_lookup)


class TestMergeScan:
    """merge_scan integration with mocked sub-functions."""

    def _make_state(self):
        from desloppify.engine._state.schema import empty_state, ensure_state_defaults

        state = empty_state()
        ensure_state_defaults(state)
        state["stats"]["open"] = 0
        return state

    @patch.object(merge_mod, "_recompute_stats")
    def test_merge_empty_scan_into_empty_state(self, mock_recompute):
        """Merging zero issues into empty state produces a clean diff."""
        mock_recompute.return_value = None
        state = self._make_state()
        diff = merge_scan(state, [], MergeScanOptions(lang="python"))
        assert diff["new"] == 0
        assert diff["auto_resolved"] == 0
        assert diff["reopened"] == 0
        assert diff["total_current"] == 0
        assert diff["ignored"] == 0
        assert diff["raw_issues"] == 0
        assert diff["suppressed_pct"] == 0.0

    @patch.object(merge_mod, "_recompute_stats")
    def test_merge_new_issues(self, mock_recompute):
        """New issues are counted correctly."""
        mock_recompute.return_value = None
        state = self._make_state()
        issues = [
            {
                "id": "smells::foo.py::debug_tag",
                "detector": "smells",
                "file": "foo.py",
                "tier": 2,
                "confidence": "high",
                "summary": "Debug tag found",
                "detail": {},
                "status": "open",
                "note": None,
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "resolved_at": None,
                "reopen_count": 0,
            },
        ]
        diff = merge_scan(state, issues, MergeScanOptions(lang="python"))
        assert diff["new"] == 1
        assert diff["total_current"] == 1
        assert "smells::foo.py::debug_tag" in state["work_items"]

    @patch.object(merge_mod, "_recompute_stats")
    def test_merge_keeps_disappeared_open_issue_when_file_exists(self, mock_recompute, tmp_path):
        """Open issues whose file still exists stay open even if absent from scan."""
        mock_recompute.return_value = None
        (tmp_path / "old.py").write_text("# still here")
        state = self._make_state()
        state["work_items"]["smells::old.py::leftover"] = {
            "id": "smells::old.py::leftover",
            "detector": "smells",
            "file": "old.py",
            "tier": 2,
            "confidence": "high",
            "summary": "Old issue",
            "detail": {},
            "status": "open",
            "note": None,
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-01-01T00:00:00+00:00",
            "resolved_at": None,
            "reopen_count": 0,
        }
        state["stats"]["open"] = 1
        diff = merge_scan(
            state, [], MergeScanOptions(lang="python", force_resolve=True, project_root=str(tmp_path))
        )
        assert diff["auto_resolved"] == 0
        assert state["work_items"]["smells::old.py::leftover"]["status"] == "open"

    @patch.object(merge_mod, "_recompute_stats")
    def test_merge_auto_resolves_issue_when_file_deleted(self, mock_recompute, tmp_path):
        """Open issues for files that no longer exist on disk are auto-resolved."""
        mock_recompute.return_value = None
        # tmp_path exists but old.py does NOT — simulates a deleted file
        state = self._make_state()
        state["work_items"]["smells::old.py::leftover"] = {
            "id": "smells::old.py::leftover",
            "detector": "smells",
            "file": "old.py",
            "tier": 2,
            "confidence": "high",
            "summary": "Old issue",
            "detail": {},
            "status": "open",
            "note": None,
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-01-01T00:00:00+00:00",
            "resolved_at": None,
            "reopen_count": 0,
        }
        state["stats"]["open"] = 1
        diff = merge_scan(
            state, [], MergeScanOptions(lang="python", force_resolve=True, project_root=str(tmp_path))
        )
        assert diff["auto_resolved"] == 1
        item = state["work_items"]["smells::old.py::leftover"]
        assert item["status"] == "auto_resolved"
        assert "no longer exists" in item["note"]

    @patch.object(merge_mod, "_recompute_stats")
    def test_merge_with_ignore_patterns(self, mock_recompute):
        """Issues matching ignore patterns are suppressed but still counted."""
        mock_recompute.return_value = None
        state = self._make_state()
        issues = [
            {
                "id": "smells::vendor/lib.py::debug",
                "detector": "smells",
                "file": "vendor/lib.py",
                "tier": 2,
                "confidence": "high",
                "summary": "Debug",
                "detail": {},
                "status": "open",
                "note": None,
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "resolved_at": None,
                "reopen_count": 0,
            },
        ]
        diff = merge_scan(
            state,
            issues,
            MergeScanOptions(lang="python", ignore=["vendor/*"]),
        )
        assert diff["ignored"] == 1
        assert diff["raw_issues"] == 1
        # Issue is inserted but suppressed:
        f = state["work_items"]["smells::vendor/lib.py::debug"]
        assert f["suppressed"] is True

    @patch.object(merge_mod, "_recompute_stats")
    def test_merge_none_options_uses_defaults(self, mock_recompute):
        """Passing options=None still works (uses default MergeScanOptions)."""
        mock_recompute.return_value = None
        state = self._make_state()
        state["stats"]["open"] = 0
        diff = merge_scan(state, [])
        assert diff["new"] == 0

    @patch.object(merge_mod, "_recompute_stats")
    def test_scan_history_capped_at_20(self, mock_recompute):
        """Scan history is capped at 20 entries."""
        mock_recompute.return_value = None
        state = self._make_state()
        state["stats"]["open"] = 0
        # Pre-fill 20 entries
        state["scan_history"] = [{"timestamp": f"t{i}"} for i in range(20)]
        merge_scan(state, [], MergeScanOptions(lang="python"))
        assert len(state["scan_history"]) == 20


# =====================================================================
# Module 2: readers.py
# =====================================================================


class TestReaders:
    """Tests for holistic review readers."""

    @patch("desloppify.intelligence.review.context_holistic.readers.resolve_path")
    def test_abs_delegates_to_resolve_path(self, mock_resolve):
        mock_resolve.return_value = "/abs/path/to/file.py"
        result = readers_mod._abs("file.py")
        assert result == "/abs/path/to/file.py"
        mock_resolve.assert_called_once_with("file.py")

    @patch("desloppify.intelligence.review.context_holistic.readers.read_file_text")
    @patch("desloppify.intelligence.review.context_holistic.readers.resolve_path")
    def test_read_file_contents_returns_existing_files(
        self, mock_resolve, mock_read
    ):
        mock_resolve.side_effect = lambda f: f"/abs/{f}"
        mock_read.side_effect = lambda path: f"contents of {path}"

        result = readers_mod._read_file_contents(["a.py", "b.py"])
        assert result == {
            "a.py": "contents of /abs/a.py",
            "b.py": "contents of /abs/b.py",
        }

    @patch("desloppify.intelligence.review.context_holistic.readers.read_file_text")
    @patch("desloppify.intelligence.review.context_holistic.readers.resolve_path")
    def test_read_file_contents_skips_missing_files(self, mock_resolve, mock_read):
        mock_resolve.side_effect = lambda f: f"/abs/{f}"
        mock_read.side_effect = lambda path: (
            "contents" if "exists" in path else None
        )

        result = readers_mod._read_file_contents(["exists.py", "missing.py"])
        assert "exists.py" in result
        assert "missing.py" not in result

    @patch("desloppify.intelligence.review.context_holistic.readers.read_file_text")
    @patch("desloppify.intelligence.review.context_holistic.readers.resolve_path")
    def test_read_file_contents_empty_list(self, mock_resolve, mock_read):
        result = readers_mod._read_file_contents([])
        assert result == {}
        mock_read.assert_not_called()


# =====================================================================
# Module 3: parser_groups_admin.py
# =====================================================================


class TestDeprecatedAction:
    """Removed deprecated parser actions stay removed."""

    def test_deprecated_action_removed(self):
        assert not hasattr(parser_admin_mod, "_DeprecatedAction")

    def test_deprecated_bool_action_removed(self):
        assert not hasattr(parser_admin_mod, "_DeprecatedBoolAction")


class TestDetectParser:
    """Tests for _add_detect_parser."""

    def test_detect_subcommand_arguments(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_detect_parser(sub, ["smells", "structural"])

        args = parser.parse_args(["detect", "smells", "--top", "10", "--json"])
        assert args.detector == "smells"
        assert args.top == 10
        assert args.json is True

    def test_detect_defaults(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_detect_parser(sub, ["smells"])

        args = parser.parse_args(["detect", "smells"])
        assert args.top == 20
        assert args.json is False
        assert args.fix is False
        assert args.category == "all"
        assert args.threshold is None
        assert args.file is None
        assert args.path is None
        assert args.lang_opt is None

    def test_detect_category_choices(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_detect_parser(sub, ["smells"])

        for cat in ["imports", "vars", "params", "all"]:
            args = parser.parse_args(["detect", "smells", "--category", cat])
            assert args.category == cat

    def test_detect_invalid_category_rejected(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_detect_parser(sub, ["smells"])

        with pytest.raises(SystemExit):
            parser.parse_args(["detect", "smells", "--category", "bogus"])


class TestMoveParser:
    def test_move_requires_source_and_dest(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_move_parser(sub)

        args = parser.parse_args(["move", "a.py", "b.py"])
        assert args.source == "a.py"
        assert args.dest == "b.py"
        assert args.dry_run is False

    def test_move_dry_run(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_move_parser(sub)

        args = parser.parse_args(["move", "a.py", "b.py", "--dry-run"])
        assert args.dry_run is True

    def test_move_missing_args(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_move_parser(sub)

        with pytest.raises(SystemExit):
            parser.parse_args(["move", "a.py"])


class TestReviewParser:
    def test_review_defaults(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(["review"])
        assert args.path is None
        assert args.state is None
        assert args.prepare is False
        assert args.import_file is None
        assert args.validate_import_file is None
        assert args.external_start is False
        assert args.external_submit is False
        assert args.session_id is None
        assert args.external_runner == "claude"
        assert args.session_ttl_hours == 24
        assert args.allow_partial is False
        assert args.dimensions is None
        assert args.retrospective is True
        assert args.retrospective_max_issues == 30
        assert args.retrospective_max_batch_items == 20
        assert args.run_batches is False
        assert args.runner == "codex"
        assert args.parallel is False
        assert args.dry_run is False
        assert args.packet is None
        assert args.only_batches is None
        assert args.scan_after_import is False

    def test_review_prepare_flag(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(["review", "--prepare", "--path", "/some/path"])
        assert args.prepare is True
        assert args.path == "/some/path"

    def test_review_import_file(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(["review", "--import", "results.json"])
        assert args.import_file == "results.json"

    def test_review_validate_import_file(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(["review", "--validate-import", "results.json"])
        assert args.validate_import_file == "results.json"

    def test_review_external_start_flag(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(
            ["review", "--external-start", "--external-runner", "claude"]
        )
        assert args.external_start is True
        assert args.external_runner == "claude"

    def test_review_external_submit_flag(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(
            [
                "review",
                "--external-submit",
                "--session-id",
                "ext_20260223_000000_deadbeef",
                "--import",
                "results.json",
            ]
        )
        assert args.external_submit is True
        assert args.session_id == "ext_20260223_000000_deadbeef"

    def test_review_allow_partial_flag(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_review_parser(sub)

        args = parser.parse_args(["review", "--import", "results.json", "--allow-partial"])
        assert args.allow_partial is True


class TestZoneParser:
    def test_zone_set(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_zone_parser(sub)

        args = parser.parse_args(["zone", "set", "foo.py", "test"])
        assert args.zone_action == "set"
        assert args.zone_path == "foo.py"
        assert args.zone_value == "test"

    def test_zone_clear(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_zone_parser(sub)

        args = parser.parse_args(["zone", "clear", "foo.py"])
        assert args.zone_action == "clear"
        assert args.zone_path == "foo.py"


class TestConfigParser:
    def test_config_set(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_config_parser(sub)

        args = parser.parse_args(["config", "set", "max_age", "60"])
        assert args.config_action == "set"
        assert args.config_key == "max_age"
        assert args.config_value == "60"

    def test_config_unset(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_config_parser(sub)

        args = parser.parse_args(["config", "unset", "max_age"])
        assert args.config_action == "unset"
        assert args.config_key == "max_age"

    def test_config_show(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_config_parser(sub)

        args = parser.parse_args(["config", "show"])
        assert args.config_action == "show"


class TestFixerHelpLines:
    @patch("desloppify.app.cli_support.parser_groups_admin.load_lang_config")
    def test_fixer_help_lines_with_fixers(self, mock_load_lang_config):
        mock_lang = MagicMock()
        mock_lang.fixers = {"unused": MagicMock(), "logs": MagicMock()}
        mock_load_lang_config.return_value = mock_lang

        lines = parser_admin_mod._fixer_help_lines(["python"])
        assert len(lines) == 1  # one lang line
        assert "logs, unused" in lines[0]

    @patch("desloppify.app.cli_support.parser_groups_admin.load_lang_config")
    def test_fixer_help_lines_import_error(self, mock_load_lang_config):
        mock_load_lang_config.side_effect = ImportError("no such lang")

        lines = parser_admin_mod._fixer_help_lines(["bogus"])
        assert "failed to load" in lines[0]


class TestFixParser:
    def test_fix_parser_args(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        with patch(
            "desloppify.app.cli_support.parser_groups_admin.load_lang_config"
        ) as mock_load:
            mock_load.side_effect = ImportError()
            parser_admin_mod._add_autofix_parser(sub, ["python"])

        args = parser.parse_args(
            ["autofix", "unused", "--path", "src", "--dry-run"]
        )
        assert args.fixer == "unused"
        assert args.path == "src"
        assert args.dry_run is True


class TestPlanAndVizParsers:
    def test_plan_parser(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_groups_mod.add_plan_parser(sub)

        args = parser.parse_args(["plan", "--output", "plan.md"])
        assert args.output == "plan.md"

    def test_viz_parser(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_viz_parser(sub)

        args = parser.parse_args(["viz", "--path", "src", "--output", "out.html"])
        assert args.path == "src"
        assert args.output == "out.html"


class TestDevParser:
    def test_dev_scaffold_lang_defaults(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_dev_parser(sub)

        args = parser.parse_args(["dev", "scaffold-lang", "go"])
        assert args.name == "go"
        assert args.default_src == "src"
        assert args.force is False
        assert args.wire_pyproject is True
        assert args.extension is None
        assert args.marker is None

    def test_dev_scaffold_lang_all_flags(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_dev_parser(sub)

        args = parser.parse_args([
            "dev", "scaffold-lang", "go",
            "--extension", ".go",
            "--extension", ".gomod",
            "--marker", "go.mod",
            "--default-src", ".",
            "--force",
            "--no-wire-pyproject",
        ])
        assert args.extension == [".go", ".gomod"]
        assert args.marker == ["go.mod"]
        assert args.default_src == "."
        assert args.force is True
        assert args.wire_pyproject is False


class TestLangsAndUpdateSkillParsers:
    def test_langs_parser(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_langs_parser(sub)

        args = parser.parse_args(["langs"])
        assert args.command == "langs"

    def test_update_skill_parser_no_interface(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_update_skill_parser(sub)

        args = parser.parse_args(["update-skill"])
        assert args.interface is None

    def test_update_skill_parser_with_interface(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_update_skill_parser(sub)

        args = parser.parse_args(["update-skill", "claude"])
        assert args.interface == "claude"

    def test_update_skill_parser_with_opencode_interface(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parser_admin_mod._add_update_skill_parser(sub)

        args = parser.parse_args(["update-skill", "opencode"])
        assert args.interface == "opencode"


# =====================================================================
# Module 4: move_apply.py
# =====================================================================


class TestRollbackWrittenFiles:
    @patch("desloppify.app.commands.move.apply.restore_files_best_effort")
    @patch("desloppify.app.commands.move.apply.warn_best_effort")
    def test_rollback_no_failures(self, mock_warn, mock_restore):
        mock_restore.return_value = []
        move_apply_mod._rollback_written_files({"a.py": "old a"})
        mock_restore.assert_called_once()
        mock_warn.assert_not_called()

    @patch("desloppify.app.commands.move.apply.restore_files_best_effort")
    @patch("desloppify.app.commands.move.apply.warn_best_effort")
    def test_rollback_with_failures(self, mock_warn, mock_restore):
        mock_restore.return_value = ["/bad/file.py"]
        move_apply_mod._rollback_written_files({"a.py": "old a"})
        mock_warn.assert_called_once()
        assert "Could not restore" in mock_warn.call_args[0][0]


class TestRollbackMoveTarget:
    def test_no_rollback_when_conditions_not_met(self, tmp_path):
        """No rollback if dest doesn't exist or source still exists."""
        source = str(tmp_path / "source.py")
        dest = str(tmp_path / "dest.py")
        # Neither exists
        move_apply_mod._rollback_move_target(dest, source, target_name="file")
        # Source still exists
        Path(source).write_text("content")
        Path(dest).write_text("content")
        move_apply_mod._rollback_move_target(dest, source, target_name="file")
        assert Path(source).exists()
        assert Path(dest).exists()

    def test_rollback_moves_dest_back_to_source(self, tmp_path):
        dest = tmp_path / "dest.py"
        source = tmp_path / "source.py"
        dest.write_text("moved content")
        # source should not exist
        assert not source.exists()
        move_apply_mod._rollback_move_target(str(dest), str(source), target_name="file")
        assert source.exists()
        assert source.read_text() == "moved content"

    @patch("desloppify.app.commands.move.apply.shutil.move", side_effect=OSError("fail"))
    @patch("desloppify.app.commands.move.apply.warn_best_effort")
    def test_rollback_os_error_warns(self, mock_warn, mock_move, tmp_path):
        dest = tmp_path / "dest.py"
        dest.write_text("content")
        source = tmp_path / "source.py"
        # Dest exists and source doesn't -- should attempt rollback
        move_apply_mod._rollback_move_target(str(dest), str(source), target_name="file")
        mock_warn.assert_called_once()
        assert "Could not move" in mock_warn.call_args[0][0]


class TestApplyFileMove:
    def test_file_move_basic(self, tmp_path):
        """Basic file move with no self/importer changes."""
        src = tmp_path / "a.py"
        dest = tmp_path / "b.py"
        src.write_text("original content")

        move_apply_mod.apply_file_move(str(src), str(dest), {}, [])
        assert not src.exists()
        assert dest.exists()
        assert dest.read_text() == "original content"

    def test_file_move_with_self_changes(self, tmp_path):
        """Self-changes (import rewrites in the moved file) are applied."""
        src = tmp_path / "a.py"
        dest = tmp_path / "sub" / "a.py"
        src.write_text("from foo import bar")

        move_apply_mod.apply_file_move(
            str(src),
            str(dest),
            {},
            [("from foo import bar", "from baz import bar")],
        )
        assert dest.exists()
        assert dest.read_text() == "from baz import bar"

    def test_file_move_with_importer_changes(self, tmp_path):
        """Importers that reference the moved file get rewritten."""
        src = tmp_path / "a.py"
        dest = tmp_path / "b.py"
        importer = tmp_path / "user.py"
        src.write_text("pass")
        importer.write_text("from a import thing")

        move_apply_mod.apply_file_move(
            str(src),
            str(dest),
            {str(importer): [("from a import thing", "from b import thing")]},
            [],
        )
        assert importer.read_text() == "from b import thing"

    def test_file_move_rollback_on_write_error(self, tmp_path):
        """If writing an importer fails, the move is rolled back."""
        src = tmp_path / "a.py"
        dest = tmp_path / "b.py"
        src.write_text("pass")

        # Pass an importer that will fail during write (dir path used as file)
        bad_importer = str(tmp_path / "nonexistent_dir" / "deep" / "file.py")
        # Create a Path that won't be readable:
        with pytest.raises((OSError, UnicodeDecodeError, shutil.Error)):
            move_apply_mod.apply_file_move(
                str(src),
                str(dest),
                {bad_importer: [("old", "new")]},
                [],
            )


class TestApplyDirectoryMove:
    def test_directory_move_basic(self, tmp_path):
        """Basic directory move with no changes."""
        src = tmp_path / "pkg"
        src.mkdir()
        (src / "mod.py").write_text("x = 1")

        dest = tmp_path / "new_pkg"
        move_apply_mod.apply_directory_move(
            str(src), str(dest), src, {}, {}
        )
        assert not src.exists()
        assert (dest / "mod.py").exists()
        assert (dest / "mod.py").read_text() == "x = 1"

    def test_directory_move_with_internal_changes(self, tmp_path):
        """Internal imports within the moved directory are updated."""
        src = tmp_path / "pkg"
        src.mkdir()
        (src / "a.py").write_text("from pkg.b import f")

        dest = tmp_path / "new_pkg"
        move_apply_mod.apply_directory_move(
            str(src),
            str(dest),
            src,
            {},  # no external changes
            {str(src / "a.py"): [("from pkg.b import f", "from new_pkg.b import f")]},
        )
        assert (dest / "a.py").read_text() == "from new_pkg.b import f"


# =====================================================================
# Module 5: shared_phases.py
# =====================================================================


class TestEntriesToIssues:
    def test_basic_conversion(self):
        entries = [
            {
                "file": "foo.py",
                "name": "debug_tag",
                "tier": 2,
                "confidence": "high",
                "summary": "Debug tag found",
                "detail": {"line": 42},
            },
        ]
        results = shared_phases_mod._entries_to_issues("smells", entries)
        assert len(results) == 1
        assert results[0]["detector"] == "smells"
        assert results[0]["tier"] == 2
        assert results[0]["confidence"] == "high"
        assert results[0]["summary"] == "Debug tag found"
        assert "detail" in results[0]

    def test_default_name(self):
        entries = [
            {
                "file": "bar.py",
                "tier": 3,
                "confidence": "medium",
                "summary": "Issue",
            },
        ]
        results = shared_phases_mod._entries_to_issues(
            "test_coverage", entries, default_name="coverage_gap"
        )
        assert len(results) == 1
        # The id should contain "coverage_gap" since no "name" in entry
        assert "coverage_gap" in results[0]["id"]

    def test_include_zone(self):
        class _FakeZone:
            def __init__(self, value: str):
                self.value = value

        entries = [
            {
                "file": "tests/foo.py",
                "tier": 3,
                "confidence": "low",
                "summary": "In test zone",
            },
        ]
        zone_map = {"tests/foo.py": _FakeZone("test")}
        results = shared_phases_mod._entries_to_issues(
            "security",
            entries,
            include_zone=True,
            zone_map=zone_map,
        )
        assert results[0]["zone"] == "test"

    def test_include_zone_missing_file(self):
        entries = [
            {
                "file": "unknown.py",
                "tier": 3,
                "confidence": "low",
                "summary": "Missing",
            },
        ]
        results = shared_phases_mod._entries_to_issues(
            "security",
            entries,
            include_zone=True,
            zone_map={},
        )
        assert "zone" not in results[0]

    def test_empty_entries(self):
        results = shared_phases_mod._entries_to_issues("smells", [])
        assert results == []


class TestLogPhaseSummary:
    @patch("desloppify.languages._framework.base.shared_phases.log")
    def test_with_results(self, mock_log):
        fake_issues = [{"id": "a"}, {"id": "b"}]
        shared_phases_mod._log_phase_summary("test coverage", fake_issues, 50, "production files")
        mock_log.assert_called_once()
        msg = mock_log.call_args[0][0]
        assert "test coverage" in msg
        assert "2 issues" in msg
        assert "50 production files" in msg

    @patch("desloppify.languages._framework.base.shared_phases.log")
    def test_clean(self, mock_log):
        shared_phases_mod._log_phase_summary("security", [], 100, "files scanned")
        mock_log.assert_called_once()
        msg = mock_log.call_args[0][0]
        assert "security" in msg
        assert "clean" in msg
        assert "100 files scanned" in msg
