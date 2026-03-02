"""Tests for scan queue preflight guard (queue-cycle gating)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from desloppify.app.commands.scan.scan_preflight import scan_queue_preflight


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
        "desloppify.app.commands.scan.scan_preflight.load_plan",
        side_effect=OSError("no plan"),
    ):
        scan_queue_preflight(args)


def test_plan_without_start_scores_passes():
    """Plan without plan_start_scores means no active cycle."""
    args = SimpleNamespace(profile=None, force_rescan=False)
    with patch(
        "desloppify.app.commands.scan.scan_preflight.load_plan",
        return_value={},
    ):
        scan_queue_preflight(args)


# ── Queue clear = scan allowed ──────────────────────────────


def test_queue_clear_allows_scan():
    """When queue has zero remaining items, scan proceeds."""
    args = SimpleNamespace(profile=None, force_rescan=False, state=None, lang="python")
    plan = {"plan_start_scores": {"strict": 80.0}}
    with (
        patch(
            "desloppify.app.commands.scan.scan_preflight.load_plan",
            return_value=plan,
        ),
        patch(
            "desloppify.app.commands.scan.scan_preflight.state_path",
            return_value="/tmp/test-state.json",
        ),
        patch("desloppify.app.commands.scan.scan_preflight.state_mod") as mock_state_mod,
        patch(
            "desloppify.app.commands.scan.scan_preflight.plan_aware_queue_count",
            return_value=0,
        ),
    ):
        mock_state_mod.load_state.return_value = {"findings": {}}
        scan_queue_preflight(args)


# ── Queue remaining = gate ──────────────────────────────────


def test_queue_remaining_blocks_scan():
    """When queue has remaining items, scan is blocked with sys.exit(1)."""
    args = SimpleNamespace(profile=None, force_rescan=False, state=None, lang="python")
    plan = {"plan_start_scores": {"strict": 80.0}}
    with (
        patch(
            "desloppify.app.commands.scan.scan_preflight.load_plan",
            return_value=plan,
        ),
        patch(
            "desloppify.app.commands.scan.scan_preflight.state_path",
            return_value="/tmp/test-state.json",
        ),
        patch("desloppify.app.commands.scan.scan_preflight.state_mod") as mock_state_mod,
        patch(
            "desloppify.app.commands.scan.scan_preflight.plan_aware_queue_count",
            return_value=5,
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        mock_state_mod.load_state.return_value = {"findings": {}}
        scan_queue_preflight(args)
    assert exc_info.value.code == 1


# ── --force-rescan ──────────────────────────────────────────


def test_force_rescan_without_attest_exits():
    """--force-rescan without proper attestation is rejected."""
    args = SimpleNamespace(profile=None, force_rescan=True, attest=None)
    with pytest.raises(SystemExit) as exc_info:
        scan_queue_preflight(args)
    assert exc_info.value.code == 1


def test_force_rescan_with_wrong_attest_exits():
    """--force-rescan with wrong attestation text is rejected."""
    args = SimpleNamespace(profile=None, force_rescan=True, attest="wrong text")
    with pytest.raises(SystemExit) as exc_info:
        scan_queue_preflight(args)
    assert exc_info.value.code == 1


def test_force_rescan_with_valid_attest_passes():
    """--force-rescan with correct attestation bypasses the gate and clears plan scores."""
    args = SimpleNamespace(
        profile=None,
        force_rescan=True,
        attest="I understand this is not the intended workflow",
    )
    plan = {"plan_start_scores": {"strict": 80.0}}
    with (
        patch(
            "desloppify.app.commands.scan.scan_preflight.load_plan",
            return_value=plan,
        ),
        patch(
            "desloppify.app.commands.scan.scan_preflight.save_plan",
        ) as mock_save,
    ):
        scan_queue_preflight(args)
        # Plan start scores should be cleared
        assert plan["plan_start_scores"] == {}
        mock_save.assert_called_once_with(plan)


def test_force_rescan_tolerates_missing_plan():
    """--force-rescan with valid attestation works even if no plan file exists."""
    args = SimpleNamespace(
        profile=None,
        force_rescan=True,
        attest="I understand this is not the intended workflow",
    )
    with patch(
        "desloppify.app.commands.scan.scan_preflight.load_plan",
        side_effect=OSError("no plan"),
    ):
        scan_queue_preflight(args)
