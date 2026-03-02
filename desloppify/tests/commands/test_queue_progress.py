"""Tests for queue progress and frozen score display helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from desloppify.app.commands.helpers.queue_progress import (
    get_plan_start_strict,
    plan_aware_queue_count,
    print_execution_or_reveal,
    print_frozen_score_with_queue_context,
    show_score_with_plan_context,
)


# ── get_plan_start_strict ────────────────────────────────────


def test_get_plan_start_strict_returns_score():
    plan = {"plan_start_scores": {"strict": 74.4}}
    assert get_plan_start_strict(plan) == 74.4


def test_get_plan_start_strict_returns_none_when_no_plan():
    assert get_plan_start_strict(None) is None
    assert get_plan_start_strict({}) is None


def test_get_plan_start_strict_returns_none_when_no_scores():
    plan = {"plan_start_scores": {}}
    assert get_plan_start_strict(plan) is None


# ── plan_aware_queue_count ───────────────────────────────────


def test_plan_aware_queue_count_delegates_to_build_work_queue():
    mock_result = {"total": 5, "items": []}
    with patch(
        "desloppify.engine.work_queue.build_work_queue",
        return_value=mock_result,
    ) as mock_build:
        count = plan_aware_queue_count({"findings": {}}, plan={"queue_order": []})
        assert count == 5
        mock_build.assert_called_once()


# ── print_frozen_score_with_queue_context ────────────────────


def test_frozen_score_prints_score_and_queue(capsys):
    plan = {"plan_start_scores": {"strict": 74.4}}
    print_frozen_score_with_queue_context(plan, queue_remaining=10)
    output = capsys.readouterr().out
    assert "74.4" in output
    assert "10" in output


def test_frozen_score_skips_when_no_strict(capsys):
    plan = {"plan_start_scores": {}}
    print_frozen_score_with_queue_context(plan, queue_remaining=5)
    output = capsys.readouterr().out
    assert output == ""


# ── print_execution_or_reveal ────────────────────────────────


def test_reveal_uses_frozen_path_when_plan_active_and_queue_remaining(capsys):
    plan = {"plan_start_scores": {"strict": 80.0}}
    with patch(
        "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_count",
        return_value=3,
    ):
        print_execution_or_reveal({}, MagicMock(), plan)
    output = capsys.readouterr().out
    assert "80.0" in output
    assert "3" in output


def _mock_score_update_module():
    """Create a mock standing in for score_update to avoid circular import."""
    return MagicMock()


def test_reveal_uses_live_path_when_no_plan():
    mock_mod = _mock_score_update_module()
    with patch.dict(
        "sys.modules",
        {"desloppify.app.commands.helpers.score_update": mock_mod},
    ):
        prev = MagicMock()
        print_execution_or_reveal({}, prev, None)
        mock_mod.print_score_update.assert_called_once_with({}, prev)


def test_reveal_uses_live_path_when_queue_empty():
    plan = {"plan_start_scores": {"strict": 80.0}}
    mock_mod = _mock_score_update_module()
    with (
        patch(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_count",
            return_value=0,
        ),
        patch.dict(
            "sys.modules",
            {"desloppify.app.commands.helpers.score_update": mock_mod},
        ),
    ):
        prev = MagicMock()
        print_execution_or_reveal({}, prev, plan)
        mock_mod.print_score_update.assert_called_once_with({}, prev)


# ── show_score_with_plan_context ─────────────────────────────


def test_show_score_loads_plan_and_delegates():
    mock_plan = {"plan_start_scores": {"strict": 75.0}}
    with (
        patch(
            "desloppify.engine.plan.load_plan",
            return_value=mock_plan,
        ),
        patch(
            "desloppify.app.commands.helpers.queue_progress.print_execution_or_reveal"
        ) as mock_reveal,
    ):
        prev = MagicMock()
        show_score_with_plan_context({}, prev)
        mock_reveal.assert_called_once_with({}, prev, mock_plan)


def test_show_score_handles_plan_load_failure():
    with (
        patch(
            "desloppify.engine.plan.load_plan",
            side_effect=OSError("no plan"),
        ),
        patch(
            "desloppify.app.commands.helpers.queue_progress.print_execution_or_reveal"
        ) as mock_reveal,
    ):
        prev = MagicMock()
        show_score_with_plan_context({}, prev)
        mock_reveal.assert_called_once_with({}, prev, None)
