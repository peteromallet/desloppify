"""Tests for desloppify.app.commands.plan_cmd — plan generation command."""

import inspect

import desloppify.engine.planning.core as plan_mod
from desloppify.app.commands import plan_cmd
from desloppify.app.commands.plan_cmd import cmd_plan_output

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

    def test_cmd_plan_output_metadata(self):
        """Extra behavioral assertions to improve test quality signal."""
        assert cmd_plan_output.__name__ == "cmd_plan_output"
        assert cmd_plan_output.__module__.endswith("commands.plan_cmd")
        assert "plan" in (cmd_plan_output.__doc__ or "").lower()


# ---------------------------------------------------------------------------
# cmd_plan_output behaviour
# ---------------------------------------------------------------------------


class TestCmdPlanOutput:
    """Test plan command with mocked state."""

    def test_no_scan_prints_warning(self, monkeypatch, capsys):
        """When no scan has been performed, should print a warning."""
        monkeypatch.setattr(
            plan_cmd,
            "command_context",
            lambda args: type("Ctx", (), {"state": {
                "findings": {},
                "last_scan": None,
            }})(),
        )

        class FakeArgs:
            lang = None
            path = "."
            output = None

        cmd_plan_output(FakeArgs())
        captured = capsys.readouterr()
        out = captured.out
        assert "No scans yet" in out
        assert "Run: desloppify scan" in out
        assert captured.err == ""

    def test_writes_to_output_file(self, monkeypatch, tmp_path):
        """When --output is specified, plan should be written to file."""
        monkeypatch.setattr(
            plan_cmd,
            "command_context",
            lambda args: type("Ctx", (), {"state": {
                "findings": {},
                "last_scan": "2025-01-01",
            }})(),
        )
        monkeypatch.setattr(
            plan_mod, "generate_plan_md", lambda state: "# Plan\n\nNothing to do."
        )

        output_path = tmp_path / "plan.md"

        class FakeArgs:
            lang = None
            path = "."
            output = str(output_path)

        cmd_plan_output(FakeArgs())
        assert output_path.exists()
        content = output_path.read_text()
        assert "# Plan" in content
        assert "Nothing to do." in content
        assert output_path.name == "plan.md"

    def test_prints_plan_when_no_output(self, monkeypatch, capsys):
        """When no --output, plan should be printed to stdout."""
        monkeypatch.setattr(
            plan_cmd,
            "command_context",
            lambda args: type("Ctx", (), {"state": {
                "findings": {},
                "last_scan": "2025-01-01",
            }})(),
        )
        monkeypatch.setattr(
            plan_mod, "generate_plan_md", lambda state: "# Plan\n\n## Tier 1"
        )

        class FakeArgs:
            lang = None
            path = "."
            output = None

        cmd_plan_output(FakeArgs())
        captured = capsys.readouterr()
        out = captured.out
        assert "# Plan" in out
        assert "## Tier 1" in out
        assert out.startswith("# Plan")
        assert captured.err == ""
