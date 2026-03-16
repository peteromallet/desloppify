"""Tests for queue progress and frozen score display helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from desloppify.app.commands.helpers.queue_progress import (
    QueueBreakdown,
    ScoreDisplayMode,
    format_queue_block,
    format_queue_headline,
    get_plan_start_strict,
    plan_aware_queue_breakdown,
    print_execution_or_reveal,
    print_frozen_score_with_queue_context,
    score_display_mode,
    show_score_with_plan_context,
)
from desloppify.engine._work_queue.helpers import is_subjective_queue_item

# ── is_subjective_queue_item ─────────────────────────────────────


def testis_subjective_queue_item_plain():
    assert is_subjective_queue_item({"kind": "subjective_dimension"}) is True


def testis_subjective_queue_item_issue():
    assert is_subjective_queue_item({"kind": "issue"}) is False


def testis_subjective_queue_item_collapsed_cluster_all_subjective():
    item = {
        "kind": "cluster",
        "members": [
            {"kind": "subjective_dimension"},
            {"kind": "subjective_dimension"},
        ],
    }
    assert is_subjective_queue_item(item) is True


def testis_subjective_queue_item_collapsed_cluster_mixed():
    item = {
        "kind": "cluster",
        "members": [
            {"kind": "subjective_dimension"},
            {"kind": "issue"},
        ],
    }
    assert is_subjective_queue_item(item) is False


def testis_subjective_queue_item_collapsed_cluster_empty_members():
    assert is_subjective_queue_item({"kind": "cluster", "members": []}) is False


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


# ── QueueBreakdown ───────────────────────────────────────────


def test_queue_breakdown_defaults():
    b = QueueBreakdown()
    assert b.queue_total == 0
    assert b.plan_ordered == 0
    assert b.stale_plan_ordered == 0
    assert b.skipped == 0
    assert b.subjective == 0
    assert b.workflow == 0
    assert b.objective_actionable == 0
    assert b.focus_cluster is None
    assert b.focus_cluster_count == 0
    assert b.focus_cluster_total == 0


def test_queue_breakdown_objective_actionable_zero_for_review_phase() -> None:
    b = QueueBreakdown(queue_total=4, lifecycle_phase="review")
    assert b.objective_actionable == 0


def test_queue_breakdown_objective_actionable_excludes_subjective_and_workflow():
    b = QueueBreakdown(queue_total=10, subjective=3, workflow=2)
    assert b.objective_actionable == 5


def test_queue_breakdown_objective_actionable_floors_at_zero():
    b = QueueBreakdown(queue_total=3, subjective=2, workflow=1)
    assert b.objective_actionable == 0


def test_queue_breakdown_objective_actionable_with_only_subjective():
    """When only subjective items remain, objective_actionable is 0."""
    b = QueueBreakdown(queue_total=5, subjective=5, workflow=0)
    assert b.objective_actionable == 0


def test_queue_breakdown_frozen():
    b = QueueBreakdown(queue_total=10, plan_ordered=5)
    with pytest.raises(AttributeError):
        b.queue_total = 20  # type: ignore[misc]


# ── score_display_mode ──────────────────────────────────────


def test_score_display_mode_live_when_no_plan_start():
    b = QueueBreakdown(queue_total=10)
    assert score_display_mode(b, None) is ScoreDisplayMode.LIVE


def test_score_display_mode_live_when_no_breakdown():
    assert score_display_mode(None, 80.0) is ScoreDisplayMode.LIVE


def test_score_display_mode_frozen_when_objective_work_remains():
    b = QueueBreakdown(queue_total=5, subjective=2, workflow=0)
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.FROZEN


def test_score_display_mode_phase_transition_when_only_subjective():
    b = QueueBreakdown(queue_total=3, subjective=3, workflow=0)
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.PHASE_TRANSITION


def test_score_display_mode_phase_transition_when_only_workflow():
    b = QueueBreakdown(queue_total=1, subjective=0, workflow=1)
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.PHASE_TRANSITION


def test_score_display_mode_live_when_scan_phase_is_active() -> None:
    b = QueueBreakdown(queue_total=1, workflow=1, lifecycle_phase="scan")
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.LIVE


def test_score_display_mode_frozen_when_execute_phase_is_active() -> None:
    b = QueueBreakdown(queue_total=1, lifecycle_phase="execute")
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.FROZEN


def test_score_display_mode_live_when_queue_empty():
    b = QueueBreakdown(queue_total=0)
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.LIVE


@pytest.mark.parametrize("phase", ["review", "execute", "workflow"])
def test_score_display_mode_live_when_queue_drained_any_lifecycle(phase: str):
    """queue_total=0 always returns LIVE regardless of lifecycle phase (#441)."""
    b = QueueBreakdown(queue_total=0, lifecycle_phase=phase)
    assert score_display_mode(b, 80.0) is ScoreDisplayMode.LIVE


# ── format_queue_headline ────────────────────────────────────


def test_headline_basic():
    b = QueueBreakdown(queue_total=100)
    headline = format_queue_headline(b)
    assert "100 items" in headline


def test_headline_with_plan_and_skipped():
    b = QueueBreakdown(
        queue_total=1934,
        plan_ordered=292,
        skipped=23,
    )
    headline = format_queue_headline(b)
    assert "1934 items" in headline
    assert "292 planned" in headline
    assert "23 skipped" in headline


def test_headline_with_stale_tracked_items():
    b = QueueBreakdown(
        queue_total=1,
        workflow=1,
        stale_plan_ordered=77,
        skipped=2201,
    )
    headline = format_queue_headline(b)
    assert "1 item" in headline
    assert "77 stale tracked" in headline
    assert "2201 skipped" in headline


def test_headline_omits_zero_segments():
    b = QueueBreakdown(
        queue_total=50,
        plan_ordered=0,
        skipped=0,
        subjective=0,
    )
    headline = format_queue_headline(b)
    assert "planned" not in headline
    assert "skipped" not in headline
    assert "subjective" not in headline


def test_headline_singular_item():
    b = QueueBreakdown(queue_total=1)
    headline = format_queue_headline(b)
    assert "1 item" in headline
    assert "items" not in headline


def test_headline_with_subjective():
    b = QueueBreakdown(
        queue_total=50,
        subjective=5,
    )
    headline = format_queue_headline(b)
    assert "5 subjective" in headline


def test_headline_no_plan_mode():
    """When no plan data, segments are omitted."""
    b = QueueBreakdown(queue_total=200)
    headline = format_queue_headline(b)
    assert "planned" not in headline
    assert "skipped" not in headline


# ── format_queue_block ───────────────────────────────────────


def test_block_no_focus_with_plan():
    b = QueueBreakdown(
        queue_total=100,
        plan_ordered=50,
        skipped=10,
    )
    block = format_queue_block(b)
    texts = [text for text, _style in block]
    joined = "\n".join(texts)
    assert "Queue:" in joined
    assert "desloppify plan queue" in joined
    assert "Focus:" not in joined


def test_block_with_focus():
    b = QueueBreakdown(
        queue_total=100,
        plan_ordered=50,
        focus_cluster="smart-t1-review",
        focus_cluster_count=12,
        focus_cluster_total=50,
    )
    block = format_queue_block(b)
    texts = [text for text, _style in block]
    styles = [style for _text, style in block]
    joined = "\n".join(texts)
    assert "Focus:" in joined
    assert "smart-t1-review" in joined
    assert "12/50" in joined
    assert "Unfocus:" in joined
    # Focus banner is cyan
    assert styles[0] == "cyan"


def test_block_simple_mode():
    """No plan — should show 'Start planning' hint."""
    b = QueueBreakdown(
        queue_total=200,
    )
    block = format_queue_block(b)
    texts = [text for text, _style in block]
    joined = "\n".join(texts)
    assert "Start planning" in joined
    assert "desloppify plan" in joined


def test_block_with_frozen_score():
    b = QueueBreakdown(
        queue_total=100,
        plan_ordered=50,
    )
    block = format_queue_block(b, frozen_score=74.4)
    texts = [text for text, _style in block]
    joined = "\n".join(texts)
    assert "74.4" in joined
    assert "frozen at plan start" in joined


def test_block_warns_when_plan_contains_stale_tracked_items():
    b = QueueBreakdown(
        queue_total=1,
        workflow=1,
        stale_plan_ordered=12,
    )
    block = format_queue_block(b)
    texts = [text for text, _style in block]
    styles = [style for _text, style in block]
    joined = "\n".join(texts)
    assert "12 plan-tracked items are stale" in joined
    assert "desloppify plan queue" in joined
    assert "yellow" in styles


# ── plan_aware_queue_breakdown ───────────────────────────────


def test_plan_aware_queue_breakdown_basic():
    # Items list must match total since collapse is now caller-side
    mock_items = (
        [{"id": f"f{i}", "kind": "issue"} for i in range(49)]
        + [{"id": "s1", "kind": "subjective_dimension"}]
    )
    mock_result = {
        "total": 50,
        "items": mock_items,
    }
    plan = {
        "queue_order": ["a", "b", "c"],
        "skipped": {"c": {"kind": "temporary"}},
    }
    with patch(
        "desloppify.app.commands.helpers.queue_progress.build_execution_queue",
        return_value=mock_result,
    ), patch(
        "desloppify.app.commands.helpers.queue_progress.queue_context",
        return_value=SimpleNamespace(snapshot=SimpleNamespace(phase="execute")),
    ):
        breakdown = plan_aware_queue_breakdown({"issues": {}}, plan=plan)
    assert breakdown.queue_total == 50
    assert breakdown.plan_ordered == 2  # a, b (c is skipped)
    assert breakdown.skipped == 1
    assert breakdown.subjective == 1
    assert breakdown.lifecycle_phase == "execute"


def test_plan_aware_queue_breakdown_no_plan():
    mock_items = [{"id": f"f{i}", "kind": "issue"} for i in range(30)]
    mock_result = {
        "total": 30,
        "items": mock_items,
    }
    with patch(
        "desloppify.app.commands.helpers.queue_progress.build_execution_queue",
        return_value=mock_result,
    ):
        breakdown = plan_aware_queue_breakdown({"issues": {}})
    assert breakdown.queue_total == 30
    assert breakdown.plan_ordered == 0
    assert breakdown.skipped == 0
    assert breakdown.focus_cluster is None


def test_plan_aware_queue_breakdown_with_focus():
    mock_result = {
        "total": 10,
        "items": [],
    }
    plan = {
        "queue_order": [],
        "skipped": {},
        "active_cluster": "smart-batch",
        "clusters": {
            "smart-batch": {
                "issue_ids": ["f1", "f2", "f3"],
            },
        },
    }
    state = {
        "issues": {
            "f1": {"status": "open"},
            "f2": {"status": "resolved"},
            "f3": {"status": "open"},
        },
    }
    with patch(
        "desloppify.app.commands.helpers.queue_progress.build_execution_queue",
        return_value=mock_result,
    ):
        breakdown = plan_aware_queue_breakdown(state, plan=plan)
    assert breakdown.focus_cluster == "smart-batch"
    assert breakdown.focus_cluster_total == 3
    assert breakdown.focus_cluster_count == 2  # f1, f3 open


def test_plan_aware_queue_breakdown_counts_only_live_queue_order_ids():
    mock_result = {
        "total": 1,
        "items": [{"id": "workflow::run-scan", "kind": "workflow_action"}],
    }
    plan = {
        "queue_order": ["stale-issue", "workflow::run-scan"],
        "skipped": {},
    }
    snapshot = SimpleNamespace(
        phase="scan",
        all_objective_items=(),
        all_initial_review_items=(),
        all_postflight_review_items=(),
        all_scan_items=({"id": "workflow::run-scan", "kind": "workflow_action"},),
        all_postflight_workflow_items=(),
        all_postflight_triage_items=(),
    )
    with patch(
        "desloppify.app.commands.helpers.queue_progress.build_execution_queue",
        return_value=mock_result,
    ), patch(
        "desloppify.app.commands.helpers.queue_progress.queue_context",
        return_value=SimpleNamespace(snapshot=snapshot),
    ):
        breakdown = plan_aware_queue_breakdown({"issues": {}}, plan=plan)
    assert breakdown.plan_ordered == 1
    assert breakdown.stale_plan_ordered == 1


# ── print_frozen_score_with_queue_context ────────────────────


def test_frozen_score_prints_score_and_queue(capsys):
    breakdown = QueueBreakdown(queue_total=10)
    print_frozen_score_with_queue_context(breakdown, frozen_strict=74.4)
    output = capsys.readouterr().out
    assert "74.4" in output
    assert "10" in output
    assert "will not update" in output


def test_frozen_score_with_breakdown(capsys):
    b = QueueBreakdown(queue_total=100, plan_ordered=50)
    print_frozen_score_with_queue_context(b, frozen_strict=80.0)
    output = capsys.readouterr().out
    assert "80.0" in output
    assert "Queue:" in output
    assert "100 items" in output


# ── print_execution_or_reveal ────────────────────────────────


def test_reveal_uses_frozen_path_when_plan_active_and_queue_remaining(capsys):
    plan = {"plan_start_scores": {"strict": 80.0}}
    breakdown = QueueBreakdown(queue_total=3)
    with patch(
        "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
        return_value=breakdown,
    ):
        print_execution_or_reveal({}, MagicMock(), plan)
    output = capsys.readouterr().out
    assert "80.0" in output
    assert "Queue:" in output


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


def test_reveal_shows_live_scores_when_only_subjective_remains():
    """When objective items are drained but subjective work remains,
    show live scores + phase-transition banner (not frozen scores)."""
    plan = {"plan_start_scores": {"strict": 75.0}}
    breakdown = QueueBreakdown(queue_total=2, subjective=2, workflow=0)
    mock_mod = _mock_score_update_module()
    with (
        patch(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            return_value=breakdown,
        ),
        patch.dict(
            "sys.modules",
            {"desloppify.app.commands.helpers.score_update": mock_mod},
        ),
    ):
        prev = MagicMock()
        print_execution_or_reveal({}, prev, plan)
        mock_mod.print_score_update.assert_called_once_with({}, prev)


def test_reveal_phase_transition_banner_content(capsys):
    """Phase-transition banner shows plan-start score and remaining item count."""
    plan = {"plan_start_scores": {"strict": 75.0}}
    breakdown = QueueBreakdown(queue_total=3, subjective=2, workflow=1)
    mock_mod = MagicMock()
    with (
        patch(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            return_value=breakdown,
        ),
        patch.dict(
            "sys.modules",
            {"desloppify.app.commands.helpers.score_update": mock_mod},
        ),
    ):
        print_execution_or_reveal({}, MagicMock(), plan)
    output = capsys.readouterr().out
    assert "75.0" in output
    assert "Objective queue complete" in output
    assert "3" in output  # remaining count
    assert "subjective" in output
    assert "workflow" in output


def test_reveal_shows_frozen_when_objective_remains(capsys):
    """When objective items remain, frozen score is still shown."""
    plan = {"plan_start_scores": {"strict": 80.0}}
    # 5 total: 2 subjective + 3 objective
    breakdown = QueueBreakdown(queue_total=5, subjective=2, workflow=0)
    with patch(
        "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
        return_value=breakdown,
    ):
        print_execution_or_reveal({}, MagicMock(), plan)
    output = capsys.readouterr().out
    assert "80.0" in output
    assert "Queue:" in output
    assert "Objective queue complete" not in output


def test_reveal_uses_live_path_when_queue_empty():
    plan = {"plan_start_scores": {"strict": 80.0}}
    mock_mod = _mock_score_update_module()
    breakdown = QueueBreakdown(queue_total=0)
    with (
        patch(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            return_value=breakdown,
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
            "desloppify.app.commands.helpers.queue_progress.load_plan",
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
            "desloppify.app.commands.helpers.queue_progress.load_plan",
            side_effect=OSError("no plan"),
        ),
        patch(
            "desloppify.app.commands.helpers.queue_progress.print_execution_or_reveal"
        ) as mock_reveal,
    ):
        prev = MagicMock()
        show_score_with_plan_context({}, prev)
        mock_reveal.assert_called_once_with({}, prev, None)
