"""Tests for desloppify.commands.resolve command logic."""

import inspect

import pytest

from desloppify.commands.resolve import cmd_resolve


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestResolveModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_resolve_callable(self):
        assert callable(cmd_resolve)

    def test_cmd_resolve_signature(self):
        sig = inspect.signature(cmd_resolve)
        params = list(sig.parameters.keys())
        assert params == ["args"]

    def test_cmd_entrypoint_metadata(self):
        """Additional non-mock behavioral assertions for coverage quality."""
        resolve_sig = inspect.signature(cmd_resolve)
        resolve_params = tuple(resolve_sig.parameters.keys())

        assert cmd_resolve.__name__ == "cmd_resolve"
        assert cmd_resolve.__module__.endswith("commands.resolve")
        assert resolve_params == ("args",)
        assert len(resolve_params) == 1
        assert resolve_sig.parameters["args"].default is inspect._empty
        assert "Resolve" in (cmd_resolve.__doc__ or "")


# ---------------------------------------------------------------------------
# cmd_resolve with mocked state
# ---------------------------------------------------------------------------

class TestCmdResolve:
    """Test resolve command with mocked state layer."""

    def test_ignore_status_routes_to_ignore_handler(self, monkeypatch):
        from desloppify.commands import resolve as resolve_mod

        calls = []
        monkeypatch.setattr(
            resolve_mod,
            "_apply_ignore_patterns",
            lambda args, patterns: calls.append(patterns),
        )

        class FakeArgs:
            status = "ignore"
            note = "temporary"
            patterns = ["smells::*"]
            _config = {"ignore": []}
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        assert calls == [["smells::*"]]

    def test_wontfix_without_note_exits(self, monkeypatch):
        """Wontfix without --note should exit with error."""
        from desloppify.commands import resolve as resolve_mod

        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "wontfix"
            note = None
            patterns = ["test::a.ts::foo"]
            lang = None
            path = "."

        with pytest.raises(SystemExit) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.code == 1

    def test_resolve_no_matches(self, monkeypatch, capsys):
        """When no findings match, should print a warning."""
        from desloppify.commands import resolve as resolve_mod
        import desloppify.state as state_mod

        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        fake_state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 48,
            "strict_score": 40,
            "stats": {}, "scan_count": 1, "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_mod, "resolve_findings",
                            lambda state, pattern, status, note: [])

        class FakeArgs:
            status = "fixed"
            note = "done"
            patterns = ["nonexistent"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "No open findings" in out

    def test_resolve_successful(self, monkeypatch, capsys):
        """Resolving findings should print a success message."""
        from desloppify.commands import resolve as resolve_mod
        import desloppify.state as state_mod
        import desloppify.narrative as narrative_mod
        import desloppify.cli as cli_mod

        written_queries = []
        saved_states = []
        resolve_calls = []
        narrative_calls = []

        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "_write_query", lambda payload: written_queries.append(payload))

        fake_state = {
            "findings": {"f1": {"status": "fixed"}},
            "overall_score": 60,
            "objective_score": 58,
            "strict_score": 50,
            "stats": {}, "scan_count": 1, "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_mod, "save_state", lambda state, sp: saved_states.append((state, sp)))

        def _resolve_findings(state, pattern, status, note):
            resolve_calls.append((pattern, status, note))
            return ["f1"]

        monkeypatch.setattr(state_mod, "resolve_findings", _resolve_findings)

        def _compute_narrative(state, **kw):
            narrative_calls.append(kw)
            return {"headline": "test", "milestone": None}

        monkeypatch.setattr(narrative_mod, "compute_narrative", _compute_narrative)

        # Mock _resolve_lang
        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            status = "fixed"
            note = "done"
            patterns = ["f1"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "Resolved 1" in out
        assert "Scores:" in out
        assert resolve_calls == [("f1", "fixed", "done")]
        assert len(saved_states) == 1
        assert saved_states[0][1] == "/tmp/fake.json"
        assert len(narrative_calls) == 1
        assert narrative_calls[0]["command"] == "resolve"
        assert len(written_queries) == 1
        assert written_queries[0]["command"] == "resolve"

    def test_resolve_prints_narrative_reminders(self, monkeypatch, capsys):
        """Resolve should surface top narrative reminders for next steps."""
        from desloppify.commands import resolve as resolve_mod
        import desloppify.commands._helpers as helpers_mod
        import desloppify.narrative as narrative_mod
        import desloppify.state as state_mod

        captured_kwargs = {}

        monkeypatch.setattr(resolve_mod, "state_path", lambda _a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "_write_query", lambda _payload: None)
        monkeypatch.setattr(helpers_mod, "resolve_lang", lambda _args: None)

        fake_state = {
            "findings": {"f1": {"status": "fixed"}},
            "overall_score": 60.0,
            "objective_score": 58.0,
            "strict_score": 50.0,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda _sp: fake_state)
        monkeypatch.setattr(state_mod, "save_state", lambda _state, _sp: None)
        monkeypatch.setattr(state_mod, "resolve_findings", lambda *_args, **_kwargs: ["f1"])

        def _fake_narrative(_state, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "milestone": None,
                "reminders": [{"type": "rescan_needed", "message": "Rescan now to verify."}],
            }

        monkeypatch.setattr(narrative_mod, "compute_narrative", _fake_narrative)

        class FakeArgs:
            status = "fixed"
            note = "done"
            patterns = ["f1"]
            lang = None
            path = "."
            _config = {"review_max_age_days": 14}

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "Rescan now to verify." in out
        assert captured_kwargs["config"] == {"review_max_age_days": 14}


class TestResolveIgnoreStatus:
    def test_ignore_without_note_exits(self, monkeypatch):
        from desloppify.commands import resolve as resolve_mod
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "ignore"
            patterns = ["smells::*"]
            note = None
            _config = {"ignore": []}
            lang = None
            path = "."

        with pytest.raises(SystemExit) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.code == 1

    def test_ignore_with_note_records_metadata(self, monkeypatch, capsys):
        from desloppify.commands import resolve as resolve_mod
        import desloppify.state as state_mod
        import desloppify.config as config_mod
        import desloppify.narrative as narrative_mod

        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "_write_query", lambda payload: None)
        saved_states = []
        saved_configs = []
        narrative_calls = []

        fake_state = {
            "findings": {"f1": {"id": "f1"}},
            "scan_path": ".",
            "overall_score": 99.0,
            "objective_score": 99.0,
            "strict_score": 80.0,
            "score_integrity": {"ignore_suppression_warning": {"suppressed_pct": 100.0}},
        }

        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_mod, "save_state", lambda state, sp: saved_states.append((state, sp)))
        monkeypatch.setattr(state_mod, "remove_ignored_findings", lambda state, pattern: 1)
        monkeypatch.setattr(state_mod, "_recompute_stats", lambda state, scan_path=None: None)
        monkeypatch.setattr(state_mod, "utc_now", lambda: "2026-02-16T00:00:00Z")
        monkeypatch.setattr(state_mod, "get_overall_score", lambda state: state.get("overall_score"))
        monkeypatch.setattr(state_mod, "get_objective_score", lambda state: state.get("objective_score"))
        monkeypatch.setattr(state_mod, "get_strict_score", lambda state: state.get("strict_score"))
        monkeypatch.setattr(config_mod, "save_config", lambda config: saved_configs.append(dict(config)))
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: narrative_calls.append(kw) or {"headline": "test", "milestone": None},
        )

        class FakeArgs:
            status = "ignore"
            patterns = ["smells::*"]
            note = "intentional temporary suppression"
            _config = {"ignore": [], "ignore_metadata": {}}
            lang = None
            path = "."

        args = FakeArgs()
        cmd_resolve(args)
        out = capsys.readouterr().out
        assert "Added ignore pattern" in out
        assert "Removed 1 matching findings" in out
        assert args._config["ignore_metadata"]["smells::*"]["note"] == "intentional temporary suppression"
        assert "smells::*" in args._config["ignore"]
        assert args._config["ignore_metadata"]["smells::*"]["added_at"] == "2026-02-16T00:00:00Z"
        assert len(saved_configs) == 1
        assert len(saved_states) == 1
        assert len(narrative_calls) == 1
        assert narrative_calls[0]["command"] == "resolve"
        saved_state, saved_path = saved_states[0]
        assert saved_path == "/tmp/fake.json"
        assert saved_state["ignore_integrity"]["ignored"] == 1
        assert saved_state["ignore_integrity"]["suppressed_pct"] == 100.0
