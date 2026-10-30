"""Tests for autofix command helpers."""

import desloppify.app.commands.autofix.apply_flow as fix_apply_mod
from desloppify.app.commands.autofix.apply_flow import (
    _SKIP_REASON_LABELS,
    _print_fix_retro,
    _print_fix_summary,
    _resolve_fixer_results,
)
from desloppify.app.commands.autofix.cmd import (
    cmd_autofix,
)
from desloppify.languages._framework.base.types import FixerConfig, FixResult

# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


class TestFixModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_autofix_callable(self):
        assert callable(cmd_autofix)

    def test_fix_result_is_dataclass(self):
        r = FixResult(entries=[])
        assert hasattr(r, "entries")
        assert hasattr(r, "skip_reasons")

    def test_skip_reason_labels_is_dict(self):
        assert isinstance(_SKIP_REASON_LABELS, dict)
        assert len(_SKIP_REASON_LABELS) > 0


# ---------------------------------------------------------------------------
# FixResult
# ---------------------------------------------------------------------------


class TestFixResult:
    """FixResult is a dataclass with entries list and skip_reasons dict."""

    def test_empty_init(self):
        r = FixResult(entries=[])
        assert len(r.entries) == 0
        assert r.skip_reasons == {}

    def test_init_with_data(self):
        r = FixResult(entries=[1, 2, 3])
        assert len(r.entries) == 3
        assert r.entries == [1, 2, 3]
        assert r.skip_reasons == {}

    def test_skip_reasons_independent(self):
        """Each instance should have its own skip_reasons dict (not shared)."""
        r1 = FixResult(entries=[])
        r2 = FixResult(entries=[])
        r1.skip_reasons["test"] = 5
        assert r2.skip_reasons == {}

    def test_entries_behave_as_list(self):
        r = FixResult(entries=[{"file": "a.ts", "removed": ["x"]}])
        r.entries.append({"file": "b.ts", "removed": ["y"]})
        assert len(r.entries) == 2
        assert r.entries[1]["file"] == "b.ts"

    def test_skip_reasons_assignable(self):
        r = FixResult(entries=[])
        r.skip_reasons = {"rest_element": 3, "function_param": 2}
        assert r.skip_reasons["rest_element"] == 3


# ---------------------------------------------------------------------------
# _resolve_fixer_results
# ---------------------------------------------------------------------------


class TestResolveFixerResults:
    """_resolve_fixer_results marks matching issues as fixed."""

    def _make_state_with_issues(self, *issues):
        work_items: dict[str, dict] = {}
        state = {"work_items": work_items, "issues": work_items}
        for fid, status in issues:
            work_items[fid] = {
                "id": fid,
                "status": status,
                "detector": "unused",
                "file": "a.ts",
                "tier": 2,
                "confidence": "high",
                "summary": "test",
                "note": None,
            }
        return state

    def test_resolves_matching_open_issues(self, monkeypatch):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        state = self._make_state_with_issues(
            ("unused::a.ts::foo", "open"),
            ("unused::a.ts::bar", "open"),
        )
        results = [{"file": "a.ts", "removed": ["foo"]}]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert resolved == ["unused::a.ts::foo"]
        assert state["work_items"]["unused::a.ts::foo"]["status"] == "fixed"
        assert state["work_items"]["unused::a.ts::bar"]["status"] == "open"

    def test_skips_already_fixed(self, monkeypatch):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        state = self._make_state_with_issues(
            ("unused::a.ts::foo", "fixed"),
        )
        results = [{"file": "a.ts", "removed": ["foo"]}]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert resolved == []

    def test_skips_nonexistent_issues(self, monkeypatch):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        state = self._make_state_with_issues()
        results = [{"file": "a.ts", "removed": ["ghost"]}]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert resolved == []

    def test_adds_auto_fix_note(self, monkeypatch):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        state = self._make_state_with_issues(("unused::a.ts::foo", "open"))
        results = [{"file": "a.ts", "removed": ["foo"]}]
        _resolve_fixer_results(state, results, "unused", "unused-imports")
        note = state["work_items"]["unused::a.ts::foo"]["note"]
        assert "auto-fixed" in note
        assert "unused-imports" in note

    def test_multiple_files(self, monkeypatch):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        state = self._make_state_with_issues(
            ("unused::a.ts::foo", "open"),
            ("unused::b.ts::bar", "open"),
        )
        state["work_items"]["unused::b.ts::bar"]["file"] = "b.ts"

        results = [
            {"file": "a.ts", "removed": ["foo"]},
            {"file": "b.ts", "removed": ["bar"]},
        ]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert len(resolved) == 2


# ---------------------------------------------------------------------------
# _print_fix_summary
# ---------------------------------------------------------------------------


class TestPrintFixSummary:
    """_print_fix_summary prints per-file summary table."""

    def test_basic_output(self, monkeypatch, capsys):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        fixer = FixerConfig(
            label="unused imports",
            detect=lambda: None,
            fix=lambda: None,
            detector="unused",
            verb="Removed",
            dry_verb="Would remove",
        )
        results = [{"file": "a.ts", "removed": ["foo", "bar"], "lines_removed": 5}]
        _print_fix_summary(fixer, results, 2, 5, dry_run=False)
        out = capsys.readouterr().out
        assert "Removed 2" in out
        assert "unused imports" in out
        assert "5 lines" in out

    def test_dry_run_uses_dry_verb(self, monkeypatch, capsys):
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)

        fixer = FixerConfig(
            label="unused imports",
            detect=lambda: None,
            fix=lambda: None,
            detector="unused",
            verb="Removed",
            dry_verb="Would remove",
        )
        results = [{"file": "a.ts", "removed": ["foo"]}]
        _print_fix_summary(fixer, results, 1, 0, dry_run=True)
        out = capsys.readouterr().out
        assert "Would remove" in out


# ---------------------------------------------------------------------------
# _print_fix_retro
# ---------------------------------------------------------------------------


class TestPrintFixRetro:
    """_print_fix_retro prints post-fix reflection."""

    def test_basic_retro(self, capsys):
        _print_fix_retro("unused-imports", 10, 8, 6)
        out = capsys.readouterr().out
        assert "Fixed 8/10" in out
        assert "2 skipped" in out
        assert "6 issues resolved" in out
        assert "Checklist:" in out

    def test_retro_with_skip_reasons(self, capsys):
        _print_fix_retro(
            "unused-vars",
            10,
            7,
            5,
            skip_reasons={"rest_element": 2, "function_param": 1},
        )
        out = capsys.readouterr().out
        assert "Skip reasons" in out
        assert "rest" in out.lower()

    def test_no_skip_reasons_with_skipped(self, capsys):
        _print_fix_retro("unused-imports", 10, 7, 5, skip_reasons=None)
        out = capsys.readouterr().out
        assert "skipped" in out.lower()
        assert "fixer" in out.lower()  # suggestion about improving fixer


class TestFixNarrativeReminders:
    def test_report_dry_run_uses_fix_command(self, monkeypatch, capsys):
        from types import SimpleNamespace

        import desloppify.app.commands.autofix.apply_flow as fix_mod
        import desloppify.intelligence.narrative.core as narrative_mod
        from desloppify.app.commands.helpers.command_runtime import CommandRuntime

        captured_kwargs = {}

        monkeypatch.setattr(fix_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(fix_mod, "resolve_lang", lambda _args: None)

        def _fake_narrative(_state, **kwargs):
            captured_kwargs.update(kwargs)
            return {"reminders": []}

        monkeypatch.setattr(narrative_mod, "compute_narrative", _fake_narrative)

        args = SimpleNamespace(
            runtime=CommandRuntime(
                config={"review_max_age_days": 10},
                state={},
                state_path=None,
            ),
            lang=None,
            path=".",
        )
        fix_mod._report_dry_run(
            args,
            fixer_name="unused-imports",
            entries=[{"file": "a.ts", "name": "foo"}],
            results=[{"file": "a.ts", "removed": ["foo"]}],
            total_items=1,
        )
        _ = capsys.readouterr().out
        context = captured_kwargs["context"]
        assert context.command == "autofix"


# ---------------------------------------------------------------------------
# Tool-backed (generic) fixers through the command
# ---------------------------------------------------------------------------


class TestToolBackedFixers:
    """cmd_autofix runs tool-backed fixers with the scan path and reports per file."""

    def _run(self, monkeypatch, fixer, *, dry_run):
        from types import SimpleNamespace

        import desloppify.app.commands.autofix.cmd as cmd_mod

        applied = {}
        monkeypatch.setattr(cmd_mod, "resolve_fixer_config", lambda _a, _n: (None, fixer))
        monkeypatch.setattr(cmd_mod, "_warn_uncommitted_changes", lambda: None)
        monkeypatch.setattr(cmd_mod, "show_fix_dry_run_samples", lambda *_a: None)
        monkeypatch.setattr(cmd_mod, "_report_dry_run", lambda *_a: None)
        monkeypatch.setattr(
            cmd_mod,
            "_apply_and_report",
            lambda *a: applied.update(results=a[5], total_items=a[6]),
        )
        monkeypatch.setattr(fix_apply_mod, "rel", lambda p: p)
        cmd_autofix(SimpleNamespace(fixer="lint", dry_run=dry_run, path="proj"))
        return applied

    def _fixer(self, calls):
        def fix(entries, dry_run=False, path=None):
            calls.append(path)
            return FixResult(
                entries=[{"file": "a.kt", "fixed": True, "fixed_count": 2, "summary": "2 fixed"}]
            )

        return FixerConfig(
            label="Fix lint issues",
            detect=lambda _p: [
                {"file": "a.kt", "line": 1, "message": "x"},
                {"file": "a.kt", "line": 2, "message": "y"},
            ],
            fix=fix,
            detector="lint",
            takes_scan_path=True,
        )

    def test_passes_scan_path_and_counts_items(self, monkeypatch, capsys):
        from pathlib import Path

        calls = []
        applied = self._run(monkeypatch, self._fixer(calls), dry_run=False)
        assert calls == [Path("proj")]
        assert applied["total_items"] == 2
        out = capsys.readouterr().out
        assert "Fixed 2 Fix lint issues across 1 files" in out
        assert "a.kt  →  2 fixed" in out

    def test_fixers_without_flag_get_no_path(self, monkeypatch):
        received = {}

        def fix(entries, *, dry_run=False):
            received["called"] = True
            return FixResult(entries=[{"file": "a.ts", "removed": ["foo"]}])

        fixer = FixerConfig(
            label="unused imports",
            detect=lambda _p: [{"file": "a.ts", "name": "foo", "line": 1}],
            fix=fix,
            detector="unused",
        )
        applied = self._run(monkeypatch, fixer, dry_run=False)
        assert received == {"called": True}
        assert applied["total_items"] == 1


class TestDryRunPreview:
    """show_fix_dry_run_samples shows flagged lines for tool-backed fixers."""

    def test_tool_backed_results_show_flagged_lines(self, tmp_path, monkeypatch, capsys):
        from desloppify.app.commands.autofix import preview as preview_mod

        source = tmp_path / "a.kt"
        source.write_text("fun a() {\n    val x = 1\n}\n", encoding="utf-8")
        monkeypatch.setattr(preview_mod, "rel", lambda p: p)
        entries = [{"file": str(source), "line": 2, "message": "Unexpected indentation"}]
        results = [{"file": str(source), "fixed_count": 1, "summary": "1 issue"}]
        preview_mod.show_fix_dry_run_samples(entries, results)
        out = capsys.readouterr().out
        assert "Sample flagged lines" in out
        assert "Unexpected indentation (line 2)" in out
        assert "val x = 1" in out
        assert "skipped" not in out
