"""Tests for scan queue preflight guard (queue-cycle gating)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from desloppify.app.commands.scan.preflight import scan_queue_preflight
from desloppify.base.exception_sets import CommandError


def _plan_status(plan=None, *, degraded=False, error_kind=None):
    return SimpleNamespace(plan=plan, degraded=degraded, error_kind=error_kind)


# ── CI profile bypass ───────────────────────────────────────


def test_ci_profile_always_passes():
    """CI profile bypasses the gate entirely."""
    args = SimpleNamespace(profile="ci")
    # Should not raise or exit
    scan_queue_preflight(args)


# ── No plan = no gate ───────────────────────────────────────


def test_no_plan_file_passes():
    """When no plan exists, scan is allowed."""
    args = SimpleNamespace(profile=None, force_rescan=False)
    with patch(
        "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
        return_value=_plan_status(),
    ):
        scan_queue_preflight(args)


def test_plan_without_start_scores_passes():
    """Plan without plan_start_scores means no active cycle."""
    args = SimpleNamespace(profile=None, force_rescan=False)
    with patch(
        "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
        return_value=_plan_status({}),
    ):
        scan_queue_preflight(args)


# ── Queue clear = scan allowed ──────────────────────────────


def test_queue_clear_allows_scan():
    """When queue has zero remaining items, scan proceeds."""
    from desloppify.app.commands.helpers.queue_progress import QueueBreakdown

    args = SimpleNamespace(profile=None, force_rescan=False, state=None, lang="python")
    plan = {"plan_start_scores": {"strict": 80.0}}
    with (
        patch(
            "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
            return_value=_plan_status(plan),
        ),
        patch(
            "desloppify.app.commands.scan.preflight.state_path",
            return_value="/tmp/test-state.json",
        ),
        patch("desloppify.app.commands.scan.preflight.state_mod") as mock_state_mod,
        patch(
            "desloppify.app.commands.scan.preflight.plan_aware_queue_breakdown",
            return_value=QueueBreakdown(queue_total=0, workflow=0),
        ),
    ):
        mock_state_mod.load_state.return_value = {"issues": {}}
        scan_queue_preflight(args)


# ── Queue remaining = gate ──────────────────────────────────


def test_queue_remaining_blocks_scan():
    """When queue has remaining items, scan is blocked with CommandError."""
    from desloppify.app.commands.helpers.queue_progress import QueueBreakdown

    args = SimpleNamespace(profile=None, force_rescan=False, state=None, lang="python")
    plan = {"plan_start_scores": {"strict": 80.0}}
    with (
        patch(
            "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
            return_value=_plan_status(plan),
        ),
        patch(
            "desloppify.app.commands.scan.preflight.state_path",
            return_value="/tmp/test-state.json",
        ),
        patch("desloppify.app.commands.scan.preflight.state_mod") as mock_state_mod,
        patch(
            "desloppify.app.commands.scan.preflight.plan_aware_queue_breakdown",
            return_value=QueueBreakdown(queue_total=5, workflow=0),
        ),
        pytest.raises(CommandError) as exc_info,
    ):
        mock_state_mod.load_state.return_value = {"issues": {}}
        scan_queue_preflight(args)
    assert "remaining in your queue" in str(exc_info.value)


def test_queue_with_only_subjective_items_blocks_scan():
    """When queue contains only subjective items, scan is blocked.

    Mid-cycle scans regenerate clusters and issue IDs, which wipes
    triage state and reorders the queue.
    """
    from desloppify.app.commands.helpers.queue_progress import QueueBreakdown

    args = SimpleNamespace(profile=None, force_rescan=False, state=None, lang="python")
    plan = {"plan_start_scores": {"strict": 80.0}}
    breakdown = QueueBreakdown(queue_total=20, subjective=20, workflow=0)
    assert breakdown.objective_actionable == 0  # precondition
    with (
        patch(
            "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
            return_value=_plan_status(plan),
        ),
        patch(
            "desloppify.app.commands.scan.preflight.state_path",
            return_value="/tmp/test-state.json",
        ),
        patch("desloppify.app.commands.scan.preflight.state_mod") as mock_state_mod,
        patch(
            "desloppify.app.commands.scan.preflight.plan_aware_queue_breakdown",
            return_value=breakdown,
        ),
        pytest.raises(CommandError),
    ):
        mock_state_mod.load_state.return_value = {"issues": {}}
        scan_queue_preflight(args)


def test_queue_with_only_workflow_items_blocks_scan():
    """When queue contains only workflow items, scan is blocked.

    Mid-cycle scans regenerate clusters and issue IDs, which wipes
    triage state and reorders the queue.
    """
    from desloppify.app.commands.helpers.queue_progress import QueueBreakdown

    args = SimpleNamespace(profile=None, force_rescan=False, state=None, lang="python")
    plan = {"plan_start_scores": {"strict": 80.0}}
    breakdown = QueueBreakdown(queue_total=1, workflow=1)
    assert breakdown.objective_actionable == 0  # precondition
    with (
        patch(
            "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
            return_value=_plan_status(plan),
        ),
        patch(
            "desloppify.app.commands.scan.preflight.state_path",
            return_value="/tmp/test-state.json",
        ),
        patch("desloppify.app.commands.scan.preflight.state_mod") as mock_state_mod,
        patch(
            "desloppify.app.commands.scan.preflight.plan_aware_queue_breakdown",
            return_value=breakdown,
        ),
        pytest.raises(CommandError),
    ):
        mock_state_mod.load_state.return_value = {"issues": {}}
        scan_queue_preflight(args)


# ── --force-rescan ──────────────────────────────────────────


def test_force_rescan_without_attest_exits():
    """--force-rescan without proper attestation is rejected."""
    args = SimpleNamespace(profile=None, force_rescan=True, attest=None)
    with pytest.raises(CommandError) as exc_info:
        scan_queue_preflight(args)
    assert exc_info.value.exit_code == 1


def test_force_rescan_with_wrong_attest_exits():
    """--force-rescan with wrong attestation text is rejected."""
    args = SimpleNamespace(profile=None, force_rescan=True, attest="wrong text")
    with pytest.raises(CommandError) as exc_info:
        scan_queue_preflight(args)
    assert exc_info.value.exit_code == 1


def test_force_rescan_with_valid_attest_passes():
    """--force-rescan with correct attestation bypasses the gate without modifying plan."""
    args = SimpleNamespace(
        profile=None,
        force_rescan=True,
        attest="I understand this is not the intended workflow",
    )
    # Preflight no longer clears plan_start_scores — mid-cycle detection
    # is preserved so reconciliation can skip destructive steps.
    scan_queue_preflight(args)


def test_force_rescan_tolerates_missing_plan():
    """--force-rescan with valid attestation works even if no plan file exists."""
    args = SimpleNamespace(
        profile=None,
        force_rescan=True,
        attest="I understand this is not the intended workflow",
    )
    with patch(
        "desloppify.app.commands.scan.preflight.resolve_plan_load_status",
        return_value=_plan_status(),
    ):
        scan_queue_preflight(args)
