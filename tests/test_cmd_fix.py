"""Tests for desloppify.commands.fix_cmd — fix command helpers."""

import pytest

from desloppify.lang.base import FixerConfig, FixResult
from desloppify.commands.fix_cmd import (
    _resolve_fixer_results,
    _print_fix_summary,
    _print_fix_retro,
    _SKIP_REASON_LABELS,
    cmd_fix,
)


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestFixModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_fix_callable(self):
        assert callable(cmd_fix)

    def test_fix_result_is_dataclass(self):
        r = FixResult(entries=[])
        assert hasattr(r, "entries")
        assert hasattr(r, "skip_reasons")

    def test_skip_reason_labels_is_dict(self):
        assert isinstance(_SKIP_REASON_LABELS, dict)
        assert len(_SKIP_REASON_LABELS) > 0

    def test_fix_review_is_not_special_alias(self, monkeypatch):
        from types import SimpleNamespace
        import desloppify.commands.fix_cmd as fix_mod

        called = []

        def _fake_load(_args, fixer_name):
            called.append(fixer_name)
            raise SystemExit(1)

        monkeypatch.setattr(fix_mod, "_load_fixer", _fake_load)
        args = SimpleNamespace(fixer="review", dry_run=True, path=".")
        with pytest.raises(SystemExit):
            fix_mod.cmd_fix(args)
        assert called == ["review"]


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
    """_resolve_fixer_results marks matching findings as fixed."""

    def _make_state_with_findings(self, *findings):
        state = {"findings": {}}
        for fid, status in findings:
            state["findings"][fid] = {
                "id": fid, "status": status, "detector": "unused",
                "file": "a.ts", "tier": 2, "confidence": "high",
                "summary": "test", "note": None,
            }
        return state

    def test_resolves_matching_open_findings(self, monkeypatch):
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        state = self._make_state_with_findings(
            ("unused::a.ts::foo", "open"),
            ("unused::a.ts::bar", "open"),
        )
        results = [{"file": "a.ts", "removed": ["foo"]}]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert resolved == ["unused::a.ts::foo"]
        assert state["findings"]["unused::a.ts::foo"]["status"] == "fixed"
        assert state["findings"]["unused::a.ts::bar"]["status"] == "open"

    def test_skips_already_fixed(self, monkeypatch):
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        state = self._make_state_with_findings(
            ("unused::a.ts::foo", "fixed"),
        )
        results = [{"file": "a.ts", "removed": ["foo"]}]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert resolved == []

    def test_skips_nonexistent_findings(self, monkeypatch):
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        state = self._make_state_with_findings()
        results = [{"file": "a.ts", "removed": ["ghost"]}]
        resolved = _resolve_fixer_results(state, results, "unused", "unused-imports")
        assert resolved == []

    def test_adds_auto_fix_note(self, monkeypatch):
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        state = self._make_state_with_findings(("unused::a.ts::foo", "open"))
        results = [{"file": "a.ts", "removed": ["foo"]}]
        _resolve_fixer_results(state, results, "unused", "unused-imports")
        note = state["findings"]["unused::a.ts::foo"]["note"]
        assert "auto-fixed" in note
        assert "unused-imports" in note

    def test_multiple_files(self, monkeypatch):
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        state = self._make_state_with_findings(
            ("unused::a.ts::foo", "open"),
            ("unused::b.ts::bar", "open"),
        )
        state["findings"]["unused::b.ts::bar"]["file"] = "b.ts"

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
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        fixer = FixerConfig(label="unused imports", detect=lambda: None, fix=lambda: None, detector="unused", verb="Removed", dry_verb="Would remove")
        results = [{"file": "a.ts", "removed": ["foo", "bar"], "lines_removed": 5}]
        _print_fix_summary(fixer, results, 2, 5, dry_run=False)
        out = capsys.readouterr().out
        assert "Removed 2" in out
        assert "unused imports" in out
        assert "5 lines" in out

    def test_dry_run_uses_dry_verb(self, monkeypatch, capsys):
        from desloppify.commands import fix_cmd
        monkeypatch.setattr(fix_cmd, "rel", lambda p: p)

        fixer = FixerConfig(label="unused imports", detect=lambda: None, fix=lambda: None, detector="unused", verb="Removed", dry_verb="Would remove")
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
        assert "6 findings resolved" in out
        assert "Checklist:" in out

    def test_retro_with_skip_reasons(self, capsys):
        _print_fix_retro("unused-vars", 10, 7, 5,
                         skip_reasons={"rest_element": 2, "function_param": 1})
        out = capsys.readouterr().out
        assert "Skip reasons" in out
        assert "rest" in out.lower()

    def test_no_skip_reasons_with_skipped(self, capsys):
        _print_fix_retro("unused-imports", 10, 7, 5, skip_reasons=None)
        out = capsys.readouterr().out
        assert "skipped" in out.lower()
        assert "fixer" in out.lower()  # suggestion about improving fixer


class TestFixNarrativeReminders:
    def test_report_dry_run_uses_fix_dry_run_command_and_prints_reminders(self, monkeypatch, capsys):
        from types import SimpleNamespace

        import desloppify.commands._helpers as helpers_mod
        import desloppify.commands.fix_cmd as fix_mod
        import desloppify.narrative as narrative_mod

        captured_kwargs = {}

        monkeypatch.setattr(fix_mod, "_write_query", lambda _payload: None)
        monkeypatch.setattr(helpers_mod, "resolve_lang", lambda _args: None)

        def _fake_narrative(_state, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "reminders": [{"type": "review_not_run", "message": "Run subjective review soon."}],
            }

        monkeypatch.setattr(narrative_mod, "compute_narrative", _fake_narrative)

        args = SimpleNamespace(_preloaded_state={}, _config={"review_max_age_days": 10}, lang=None, path=".")
        fix_mod._report_dry_run(
            args,
            fixer_name="unused-imports",
            entries=[{"file": "a.ts", "name": "foo"}],
            results=[{"file": "a.ts", "removed": ["foo"]}],
            total_items=1,
        )
        out = capsys.readouterr().out
        assert "Run subjective review soon." in out
        assert captured_kwargs["command"] == "fix_dry_run"
        assert captured_kwargs["config"] == {"review_max_age_days": 10}
