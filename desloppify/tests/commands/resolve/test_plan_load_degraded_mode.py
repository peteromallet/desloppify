"""Tests for resolve degraded-mode behavior when plan loading fails."""

from __future__ import annotations

from unittest.mock import MagicMock

import desloppify.app.commands.resolve.apply as apply_mod
import desloppify.app.commands.resolve.plan_load as plan_load_mod
import desloppify.app.commands.resolve.queue_guard as queue_guard_mod
from desloppify.engine._work_queue.context import PlanLoadStatus


def test_try_expand_cluster_warns_when_plan_load_is_degraded(monkeypatch) -> None:
    monkeypatch.setattr(
        apply_mod,
        "resolve_plan_load_status",
        lambda: PlanLoadStatus(
            plan=None,
            degraded=True,
            error_kind="JSONDecodeError",
        ),
    )
    warn = MagicMock()
    monkeypatch.setattr(apply_mod, "warn_plan_load_degraded_once", warn)

    assert apply_mod._try_expand_cluster("cluster-a") is None
    warn.assert_called_once()
    kwargs = warn.call_args.kwargs
    assert kwargs["error_kind"] == "JSONDecodeError"
    assert "Cluster-name pattern expansion is disabled" in kwargs["behavior"]


def test_queue_order_guard_warns_when_plan_load_is_degraded(monkeypatch) -> None:
    monkeypatch.setattr(
        queue_guard_mod,
        "resolve_plan_load_status",
        lambda: PlanLoadStatus(
            plan=None,
            degraded=True,
            error_kind="OSError",
        ),
    )
    warn = MagicMock()
    monkeypatch.setattr(queue_guard_mod, "warn_plan_load_degraded_once", warn)

    blocked = queue_guard_mod._check_queue_order_guard(
        state={"issues": {}},
        patterns=["smells::src/app.py::x"],
        status="fixed",
    )
    assert blocked is False
    warn.assert_called_once()
    kwargs = warn.call_args.kwargs
    assert kwargs["error_kind"] == "OSError"
    assert "Queue-order enforcement is disabled" in kwargs["behavior"]


def test_plan_load_warning_prints_once(capsys) -> None:
    plan_load_mod._reset_degraded_plan_warning_for_tests()
    plan_load_mod.warn_plan_load_degraded_once(
        error_kind="RuntimeError",
        behavior="Queue-order enforcement is disabled until recovery.",
    )
    plan_load_mod.warn_plan_load_degraded_once(
        error_kind="RuntimeError",
        behavior="Cluster expansion is disabled until recovery.",
    )
    err = capsys.readouterr().err
    assert err.count("Warning: resolve is running in degraded mode") == 1
    assert "Queue-order enforcement is disabled until recovery." in err
