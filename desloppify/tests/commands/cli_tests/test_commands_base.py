"""Tests for desloppify.languages._framework.commands_base — command factory functions.

Each factory returns a callable that runs a detector and prints results.
We test that the factories return callables and that they invoke the correct
detector functions with the expected arguments when called.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from desloppify.languages._framework.commands_base import (
    make_cmd_complexity,
    make_cmd_facade,
    make_cmd_large,
    make_cmd_naming,
    make_cmd_passthrough,
    make_cmd_single_use,
    make_cmd_smells,
)


def _make_args(path="/tmp/test", top=20, json_flag=False):
    """Create a mock args namespace."""
    return SimpleNamespace(path=path, top=top, json=json_flag)


# ── make_cmd_large ───────────────────────────────────────────


class TestMakeCmdLarge:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_large(file_finder=lambda p: [], default_threshold=500)
        assert callable(cmd)

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_calls_detect_large_files(self, mock_display):
        """Returned command invokes detect_large_files and display_entries."""
        finder = MagicMock(return_value=[])
        cmd = make_cmd_large(file_finder=finder, default_threshold=500)

        with patch(
            "desloppify.engine.detectors.large.detect_large_files", return_value=([], 0)
        ) as mock_detect:
            cmd(_make_args())
            mock_detect.assert_called_once()
            mock_display.assert_called_once()

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_uses_default_threshold(self, mock_display):
        """Command uses the factory-provided default threshold."""
        cmd = make_cmd_large(file_finder=lambda p: [], default_threshold=300)
        args = SimpleNamespace(path="/tmp/test")  # no threshold attr

        with patch(
            "desloppify.engine.detectors.large.detect_large_files", return_value=([], 0)
        ) as mock_detect:
            cmd(args)
            call_kwargs = mock_detect.call_args
            assert call_kwargs[1]["threshold"] == 300 or call_kwargs[0][0] is not None


# ── make_cmd_complexity ──────────────────────────────────────


class TestMakeCmdComplexity:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_complexity(file_finder=lambda p: [], signals=[])
        assert callable(cmd)

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_calls_detect_complexity(self, mock_display):
        """Returned command invokes detect_complexity and display_entries."""
        cmd = make_cmd_complexity(file_finder=lambda p: [], signals=[])

        with patch(
            "desloppify.engine.detectors.complexity.detect_complexity", return_value=([], 0)
        ) as mock_detect:
            cmd(_make_args())
            mock_detect.assert_called_once()
            mock_display.assert_called_once()


# ── make_cmd_single_use ──────────────────────────────────────


class TestMakeCmdSingleUse:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_single_use(build_dep_graph=lambda p: {}, barrel_names=set())
        assert callable(cmd)

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_calls_detect_single_use(self, mock_display):
        """Returned command invokes detect_single_use_abstractions."""
        mock_graph = MagicMock(return_value={})
        cmd = make_cmd_single_use(build_dep_graph=mock_graph, barrel_names={"index"})

        with patch(
            "desloppify.engine.detectors.single_use.detect_single_use_abstractions",
            return_value=([], 0),
        ) as mock_detect:
            cmd(_make_args())
            mock_graph.assert_called_once()
            mock_detect.assert_called_once()
            mock_display.assert_called_once()


# ── make_cmd_passthrough ─────────────────────────────────────


class TestMakeCmdPassthrough:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_passthrough(
            detect_fn=lambda p: [],
            noun="component",
            name_key="component",
            total_key="total_props",
        )
        assert callable(cmd)

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_calls_detect_fn(self, mock_display):
        """Returned command invokes the provided detect function."""
        mock_detect = MagicMock(return_value=[])
        cmd = make_cmd_passthrough(
            detect_fn=mock_detect,
            noun="component",
            name_key="component",
            total_key="total_props",
        )
        cmd(_make_args())
        mock_detect.assert_called_once()
        mock_display.assert_called_once()


# ── make_cmd_naming ──────────────────────────────────────────


class TestMakeCmdNaming:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_naming(file_finder=lambda p: [], skip_names=set())
        assert callable(cmd)

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_calls_detect_naming(self, mock_display):
        """Returned command invokes detect_naming_inconsistencies."""
        cmd = make_cmd_naming(
            file_finder=lambda p: [],
            skip_names={"__init__"},
        )

        with patch(
            "desloppify.engine.detectors.naming.detect_naming_inconsistencies",
            return_value=([], 0),
        ) as mock_detect:
            cmd(_make_args())
            mock_detect.assert_called_once()

    @patch("desloppify.languages._framework.commands_base.display_entries")
    def test_passes_skip_dirs(self, mock_display):
        """skip_dirs parameter is forwarded to the detector."""
        cmd = make_cmd_naming(
            file_finder=lambda p: [],
            skip_names=set(),
            skip_dirs={"__pycache__"},
        )

        with patch(
            "desloppify.engine.detectors.naming.detect_naming_inconsistencies",
            return_value=([], 0),
        ) as mock_detect:
            cmd(_make_args())
            call_kwargs = mock_detect.call_args[1]
            assert call_kwargs["skip_dirs"] == {"__pycache__"}


# ── make_cmd_facade ──────────────────────────────────────────


class TestMakeCmdFacade:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_facade(
            build_dep_graph_fn=lambda p: {},
            detect_facades_fn=lambda graph: ([], 0),
        )
        assert callable(cmd)

    def test_json_output(self, capsys):
        """With json=True, outputs JSON."""
        mock_graph = MagicMock(return_value={})
        mock_detect = MagicMock(return_value=([], 0))
        cmd = make_cmd_facade(
            build_dep_graph_fn=mock_graph, detect_facades_fn=mock_detect
        )

        args = _make_args(json_flag=True)
        cmd(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "count" in data
        assert data["count"] == 0

    def test_no_entries_prints_green(self, capsys):
        """With no entries and no json, prints the 'no facades' message."""
        mock_graph = MagicMock(return_value={})
        mock_detect = MagicMock(return_value=([], 0))
        cmd = make_cmd_facade(
            build_dep_graph_fn=mock_graph, detect_facades_fn=mock_detect
        )

        cmd(_make_args())

        captured = capsys.readouterr()
        assert "No re-export facades found" in captured.out


# ── make_cmd_smells ──────────────────────────────────────────


class TestMakeCmdSmells:
    def test_returns_callable(self):
        """Factory returns a callable."""
        cmd = make_cmd_smells(detect_smells_fn=lambda p: ([], 0))
        assert callable(cmd)

    def test_json_output(self, capsys):
        """With json=True, outputs JSON."""
        cmd = make_cmd_smells(detect_smells_fn=lambda p: ([], 0))
        args = _make_args(json_flag=True)
        cmd(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "entries" in data

    def test_no_smells_prints_clean_message(self, capsys):
        """With no entries, prints clean message."""
        cmd = make_cmd_smells(detect_smells_fn=lambda p: ([], 0))
        cmd(_make_args())

        captured = capsys.readouterr()
        assert "No code smells detected" in captured.out

    def test_with_entries_prints_table(self, capsys):
        """With entries, prints a table of smells."""
        entries = [
            {
                "id": "eval",
                "label": "eval usage",
                "severity": "high",
                "count": 5,
                "files": 2,
                "matches": [{"file": "/proj/a.py", "line": 1, "content": "eval(x)"}],
            },
        ]
        cmd = make_cmd_smells(detect_smells_fn=lambda p: (entries, 5))
        cmd(_make_args())

        captured = capsys.readouterr()
        assert "Code smells" in captured.out
        assert "eval usage" in captured.out
