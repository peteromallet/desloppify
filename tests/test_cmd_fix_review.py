"""Tests for `desloppify fix review` command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from desloppify.commands.fix_cmd import _cmd_fix_review


class _FakeArgs:
    def __init__(self, path="/tmp/test", lang="python"):
        self.path = path
        self.lang = lang
        self.state_dir = None


def _make_prepare_result(total_candidates=3, dims=None):
    """Build a realistic prepare_review return value."""
    dims = dims or ["naming_quality", "error_consistency"]
    return {
        "command": "review",
        "language": "python",
        "dimensions": dims,
        "dimension_prompts": {
            "naming_quality": {
                "description": "Function/variable/file names that communicate intent",
                "look_for": ["Generic verbs", "Name/behavior mismatch", "Vocab divergence"],
                "skip": ["Framework names"],
            },
            "error_consistency": {
                "description": "Consistent error handling",
                "look_for": ["Mixed conventions", "Lost context", "Inconsistent returns"],
                "skip": ["Broad catches at boundaries"],
            },
        },
        "lang_guidance": {
            "patterns": ["Check for async def without await"],
            "naming": "Python uses snake_case.",
        },
        "context": {},
        "system_prompt": "...",
        "files": [{"file": f"module_{i}.py"} for i in range(total_candidates)],
        "total_candidates": total_candidates,
        "cache_status": {"fresh": 0, "stale": 0, "new": total_candidates},
    }


# Patch targets: lazy imports inside _cmd_fix_review resolve at source modules
_P_LANG = "desloppify.commands._helpers.resolve_lang"
_P_SP = "desloppify.commands._helpers.state_path"
_P_LOAD = "desloppify.state.load_state"
_P_PREP = "desloppify.review.prepare_review"
_P_SETUP = "desloppify.commands.review_cmd._setup_lang"
_P_WQ = "desloppify.commands.fix_cmd._write_query"


def _patch_all(prep_result, found_files=None):
    """Return a stack of patches for _cmd_fix_review."""
    if found_files is None:
        found_files = []
    mock_lang = MagicMock()
    mock_lang.name = "python"
    return (
        patch(_P_LANG, return_value=mock_lang),
        patch(_P_SP, return_value="/tmp/state.json"),
        patch(_P_LOAD, return_value={}),
        patch(_P_SETUP, return_value=found_files),
        patch(_P_PREP, return_value=prep_result),
        patch(_P_WQ),
    )


class TestFixReviewZeroCandidates:
    def test_prints_all_reviewed(self, capsys):
        args = _FakeArgs()
        patches = _patch_all(_make_prepare_result(total_candidates=0))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            _cmd_fix_review(args)
        out = capsys.readouterr().out
        assert "All production files have been reviewed" in out


class TestFixReviewDimensionPrompts:
    def test_prints_dimensions(self, capsys):
        args = _FakeArgs()
        patches = _patch_all(_make_prepare_result(total_candidates=3))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            _cmd_fix_review(args)
        out = capsys.readouterr().out
        assert "3 files need design review" in out
        assert "naming_quality" in out
        assert "error_consistency" in out
        assert "Generic verbs" in out
        assert "query.json" in out

    def test_prints_lang_guidance(self, capsys):
        args = _FakeArgs()
        patches = _patch_all(_make_prepare_result())
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            _cmd_fix_review(args)
        out = capsys.readouterr().out
        assert "snake_case" in out
        assert "async def" in out

    def test_prints_skip_items(self, capsys):
        args = _FakeArgs()
        patches = _patch_all(_make_prepare_result())
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            _cmd_fix_review(args)
        out = capsys.readouterr().out
        assert "Framework names" in out
        assert "Broad catches at boundaries" in out

    def test_prints_next_steps(self, capsys):
        args = _FakeArgs()
        patches = _patch_all(_make_prepare_result())
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            _cmd_fix_review(args)
        out = capsys.readouterr().out
        assert "desloppify review --import findings.json" in out


class TestFixReviewQueryData:
    def test_writes_query(self):
        args = _FakeArgs()
        data = _make_prepare_result(total_candidates=5)
        with patch(_P_LANG, return_value=MagicMock(name="python")), \
             patch(_P_SP, return_value="/tmp/state.json"), \
             patch(_P_LOAD, return_value={}), \
             patch(_P_SETUP, return_value=[]), \
             patch(_P_PREP, return_value=data), \
             patch(_P_WQ) as mock_wq:
            _cmd_fix_review(args)
        mock_wq.assert_called_once_with(data)

    def test_calls_prepare_review_with_files(self):
        args = _FakeArgs()
        found = ["/tmp/a.py", "/tmp/b.py"]
        with patch(_P_LANG, return_value=MagicMock(name="python")), \
             patch(_P_SP, return_value="/tmp/state.json"), \
             patch(_P_LOAD, return_value={}), \
             patch(_P_SETUP, return_value=found), \
             patch(_P_PREP, return_value=_make_prepare_result()) as mock_prep, \
             patch(_P_WQ):
            _cmd_fix_review(args)
        call_kwargs = mock_prep.call_args
        assert call_kwargs.kwargs.get("files") == found


class TestFixReviewInterception:
    """cmd_fix routes 'review' to _cmd_fix_review."""

    def test_review_dispatched(self):
        args = _FakeArgs()
        args.fixer = "review"
        args.dry_run = False
        with patch("desloppify.commands.fix_cmd._cmd_fix_review") as mock_review:
            from desloppify.commands.fix_cmd import cmd_fix
            cmd_fix(args)
        mock_review.assert_called_once_with(args)
