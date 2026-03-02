"""Regression tests for plan override state/plan transaction boundaries."""

from __future__ import annotations

import argparse
import copy

import pytest

from desloppify import state as state_mod
from desloppify.app.commands.helpers.runtime import CommandRuntime
from desloppify.app.commands.plan import override_handlers
from desloppify.engine.plan import empty_plan, load_plan, save_plan, skip_items

_ATTEST = "I have actually reviewed this and I am not gaming the score."


def _seed_state() -> tuple[dict, str]:
    state = state_mod.empty_state()
    state["last_scan"] = "2026-03-01T00:00:00+00:00"
    state["scan_count"] = 3
    finding = state_mod.make_finding(
        "review",
        "src/example.py",
        "sample-finding",
        tier=1,
        confidence="high",
        summary="sample",
    )
    finding_id = finding["id"]
    state["findings"][finding_id] = finding
    return state, finding_id


def _seed_plan(finding_id: str) -> dict:
    plan = empty_plan()
    plan["queue_order"] = [finding_id]
    return plan


def test_save_plan_state_transactional_rolls_back_on_plan_write_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    plan_file = tmp_path / "plan.json"

    initial_state, finding_id = _seed_state()
    initial_plan = _seed_plan(finding_id)
    state_mod.save_state(initial_state, state_file)
    save_plan(initial_plan, plan_file)
    before_state = state_file.read_text()
    before_plan = plan_file.read_text()

    changed_state = copy.deepcopy(initial_state)
    state_mod.resolve_findings(
        changed_state,
        finding_id,
        "wontfix",
        note="intentional debt",
        attestation=_ATTEST,
    )
    changed_plan = copy.deepcopy(initial_plan)
    skip_items(
        changed_plan,
        [finding_id],
        kind="permanent",
        note="intentional debt",
        attestation=_ATTEST,
    )

    def _boom(*_args, **_kwargs):
        raise OSError("simulated plan write failure")

    monkeypatch.setattr(override_handlers, "save_plan", _boom)
    with pytest.raises(OSError):
        override_handlers._save_plan_state_transactional(
            plan=changed_plan,
            plan_path=plan_file,
            state_data=changed_state,
            state_path_value=state_file,
        )

    assert state_file.read_text() == before_state
    assert plan_file.read_text() == before_plan


def test_cmd_plan_skip_permanent_rollback_when_plan_write_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    plan_file = tmp_path / "plan.json"

    initial_state, finding_id = _seed_state()
    initial_plan = _seed_plan(finding_id)
    state_mod.save_state(initial_state, state_file)
    save_plan(initial_plan, plan_file)

    runtime = CommandRuntime(
        config={},
        state=copy.deepcopy(initial_state),
        state_path=state_file,
    )
    args = argparse.Namespace(
        runtime=runtime,
        patterns=[finding_id],
        reason=None,
        review_after=None,
        permanent=True,
        false_positive=False,
        note="intentional debt",
        attest=_ATTEST,
    )

    monkeypatch.setattr(override_handlers, "resolve_ids_from_patterns", lambda *_a, **_k: [finding_id])

    def _boom(*_args, **_kwargs):
        raise OSError("simulated plan write failure")

    monkeypatch.setattr(override_handlers, "save_plan", _boom)

    with pytest.raises(OSError):
        override_handlers.cmd_plan_skip(args)

    state_after = state_mod.load_state(state_file)
    plan_after = load_plan(plan_file)
    assert state_after["findings"][finding_id]["status"] == "open"
    assert plan_after.get("queue_order", []) == [finding_id]
    assert plan_after.get("skipped", {}) == {}
