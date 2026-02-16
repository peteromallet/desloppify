"""Tests for desloppify.commands.next — import verification and structure."""

import inspect


from desloppify.commands.next import cmd_next
from desloppify.commands import next as next_mod


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestNextModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_next_callable(self):
        assert callable(cmd_next)

    def test_cmd_next_signature(self):
        sig = inspect.signature(cmd_next)
        params = list(sig.parameters.keys())
        assert params == ["args"]

    def test_module_docstring(self):
        import desloppify.commands.next as mod
        assert mod.__doc__ is not None
        assert "next" in mod.__doc__.lower()


class TestNextHelpers:
    """Exercise command helper functions with minimal/no mocking."""

    def test_serialize_item_defaults_detail(self):
        item = {
            "id": "smells::src/a.py::x",
            "tier": 2,
            "confidence": "high",
            "file": "src/a.py",
            "summary": "example",
        }
        payload = next_mod._serialize_item(item)
        assert payload["id"] == item["id"]
        assert payload["tier"] == 2
        assert payload["confidence"] == "high"
        assert payload["detail"] == {}

    def test_write_output_file_writes_json(self, tmp_path, capsys):
        out_file = tmp_path / "next.json"
        next_mod._write_output_file(str(out_file), [{
            "id": "smells::src/a.py::x",
            "tier": 2,
            "confidence": "high",
            "file": "src/a.py",
            "summary": "example",
            "detail": {"line": 3},
        }])
        text = out_file.read_text()
        stdout = capsys.readouterr().out
        assert "\"id\": \"smells::src/a.py::x\"" in text
        assert "\"line\": 3" in text
        assert "Wrote 1 items to" in stdout

    def test_render_items_includes_resolution_and_review_nudge(self, capsys):
        item = {
            "id": "smells::src/a.py::x",
            "tier": 2,
            "confidence": "high",
            "file": ".",
            "summary": "example",
            "detail": {"category": "maintainability"},
        }
        findings = {
            "f1": {"status": "open", "detector": "review", "detail": {}},
            "f2": {"status": "open", "detector": "smells", "detail": {}},
        }
        next_mod._render_items([item], findings, {})
        out = capsys.readouterr().out
        assert "Next item" in out
        assert "Resolve with:" in out
        assert "desloppify resolve fixed" in out
        assert "desloppify issues" in out


# ---------------------------------------------------------------------------
# cmd_next output formatting (via monkeypatch)
# ---------------------------------------------------------------------------

class TestCmdNextOutput:
    """Test cmd_next output for empty state."""

    def test_no_items_prints_nothing_to_do(self, monkeypatch, capsys):
        """When there are no open findings, cmd_next should say 'Nothing to do'."""
        from desloppify.commands import next as next_mod

        # Mock load_state to return empty state
        calls = {"load_state": 0, "get_next_items": 0, "state_path": 0, "stale": 0}

        def mock_load_state(sp):
            calls["load_state"] += 1
            return {
                "findings": {},
                "overall_score": 100,
                "objective_score": 100,
                "strict_score": 100,
                "stats": {},
            }

        # Mock get_next_items to return empty list
        def mock_get_next_items(state, tier, count, scan_path=None):
            calls["get_next_items"] += 1
            return []

        # Mock state_path
        def mock_state_path(args):
            calls["state_path"] += 1
            return "/tmp/fake-state.json"

        # Mock check_tool_staleness
        def mock_check_staleness(state):
            calls["stale"] += 1
            return None

        # Mock _write_query (still private)
        written = []
        def mock_write_query(payload):
            written.append(payload)

        monkeypatch.setattr(next_mod, "state_path", mock_state_path)
        monkeypatch.setattr(next_mod, "_write_query", mock_write_query)

        # We need to patch the lazy imports inside cmd_next
        import desloppify.state as state_mod
        import desloppify.plan as plan_mod
        import desloppify.utils as utils_mod
        monkeypatch.setattr(state_mod, "load_state", mock_load_state)
        monkeypatch.setattr(plan_mod, "get_next_items", mock_get_next_items)
        monkeypatch.setattr(utils_mod, "check_tool_staleness", mock_check_staleness)

        class FakeArgs:
            tier = None
            count = 1
            output = None
            lang = None
            path = "."

        cmd_next(FakeArgs())
        out = capsys.readouterr().out
        assert "Nothing to do" in out
        assert len(written) == 1
        assert written[0]["command"] == "next"
        assert written[0]["items"] == []
        assert calls["state_path"] == 1
        assert calls["load_state"] == 1
        assert calls["get_next_items"] == 1
        assert calls["stale"] == 1

    def test_items_flow_prints_narrative_reminders(self, monkeypatch, capsys):
        """When items exist, cmd_next should show top narrative reminders."""
        from desloppify.commands import next as next_mod
        import desloppify.commands._helpers as helpers_mod
        import desloppify.narrative as narrative_mod
        import desloppify.plan as plan_mod
        import desloppify.state as state_mod
        import desloppify.utils as utils_mod

        captured_kwargs = {}

        monkeypatch.setattr(next_mod, "state_path", lambda _args: "/tmp/fake-state.json")
        written = []
        monkeypatch.setattr(next_mod, "_write_query", lambda payload: written.append(payload))
        monkeypatch.setattr(next_mod, "_render_items", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(helpers_mod, "resolve_lang", lambda _args: None)
        monkeypatch.setattr(utils_mod, "check_tool_staleness", lambda _state: None)
        monkeypatch.setattr(state_mod, "load_state", lambda _sp: {
            "findings": {"f1": {"id": "f1", "status": "open", "detector": "smells", "file": "src/a.py"}},
            "scan_path": ".",
            "dimension_scores": {},
            "overall_score": 80.0,
            "objective_score": 78.0,
            "strict_score": 76.0,
        })
        monkeypatch.setattr(plan_mod, "get_next_items", lambda *_args, **_kwargs: [{
            "id": "smells::src/a.py::foo",
            "tier": 2,
            "confidence": "high",
            "file": "src/a.py",
            "summary": "test summary",
            "detail": {"line": 1},
            "detector": "smells",
        }])

        def _fake_narrative(_state, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "reminders": [
                    {"type": "review_stale", "message": "Design review is stale — rerun review."},
                ],
            }

        monkeypatch.setattr(narrative_mod, "compute_narrative", _fake_narrative)

        class FakeArgs:
            tier = None
            count = 1
            output = None
            lang = None
            path = "."
            _config = {"review_max_age_days": 21}

        cmd_next(FakeArgs())
        out = capsys.readouterr().out
        assert "Reminders:" in out
        assert "Design review is stale" in out
        assert captured_kwargs["config"] == {"review_max_age_days": 21}
        assert len(written) == 1
        assert written[0]["command"] == "next"
