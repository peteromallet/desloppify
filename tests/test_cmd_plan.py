"""Tests for desloppify.commands.plan_cmd — plan generation command."""

import inspect

import pytest

from desloppify.commands.plan_cmd import cmd_plan_output


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestPlanModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_plan_output_callable(self):
        assert callable(cmd_plan_output)

    def test_cmd_plan_output_signature(self):
        sig = inspect.signature(cmd_plan_output)
        params = list(sig.parameters.keys())
        assert params == ["args"]


# ---------------------------------------------------------------------------
# cmd_plan_output behaviour
# ---------------------------------------------------------------------------

class TestCmdPlanOutput:
    """Test plan command with mocked state."""

    def test_no_scan_prints_warning(self, monkeypatch, capsys):
        """When no scan has been performed, should print a warning."""
        from desloppify.commands import plan_cmd
        import desloppify.state as state_mod

        monkeypatch.setattr(plan_cmd, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(state_mod, "load_state", lambda sp: {
            "findings": {}, "score": 0, "last_scan": None,
        })

        class FakeArgs:
            lang = None
            path = "."
            output = None

        cmd_plan_output(FakeArgs())
        out = capsys.readouterr().out
        assert "No scans yet" in out

    def test_writes_to_output_file(self, monkeypatch, tmp_path):
        """When --output is specified, plan should be written to file."""
        from desloppify.commands import plan_cmd
        import desloppify.state as state_mod
        import desloppify.plan as plan_mod

        monkeypatch.setattr(plan_cmd, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(state_mod, "load_state", lambda sp: {
            "findings": {}, "score": 80, "last_scan": "2025-01-01",
        })
        monkeypatch.setattr(plan_mod, "generate_plan_md",
                            lambda state: "# Plan\n\nNothing to do.")

        output_path = tmp_path / "plan.md"

        class FakeArgs:
            lang = None
            path = "."
            output = str(output_path)

        cmd_plan_output(FakeArgs())
        assert output_path.exists()
        content = output_path.read_text()
        assert "# Plan" in content

    def test_prints_plan_when_no_output(self, monkeypatch, capsys):
        """When no --output, plan should be printed to stdout."""
        from desloppify.commands import plan_cmd
        import desloppify.state as state_mod
        import desloppify.plan as plan_mod

        monkeypatch.setattr(plan_cmd, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(state_mod, "load_state", lambda sp: {
            "findings": {}, "score": 80, "last_scan": "2025-01-01",
        })
        monkeypatch.setattr(plan_mod, "generate_plan_md",
                            lambda state: "# Plan\n\n## Tier 1")

        class FakeArgs:
            lang = None
            path = "."
            output = None

        cmd_plan_output(FakeArgs())
        out = capsys.readouterr().out
        assert "# Plan" in out
        assert "## Tier 1" in out
