"""Regression tests for plan override state/plan transaction boundaries."""

from __future__ import annotations

import argparse
import copy

import pytest

from desloppify import state as state_mod
from desloppify.app.commands.helpers.command_runtime import CommandRuntime
from desloppify.app.commands.plan.override import io as override_io
from desloppify.app.commands.plan.override import skip as override_skip
from desloppify.app.commands.plan.override import resolve_cmd as override_resolve
from desloppify.base.exception_sets import CommandError
from desloppify.engine.plan_state import empty_plan, load_plan, save_plan
from desloppify.engine.plan_ops import skip_items

_ATTEST = "I have actually reviewed this and I am not gaming the score."


@pytest.mark.parametrize("pattern", ["strategy::verify-ci", "strategy::*"])
def test_resolving_strategy_persists_fixed_status(
    set_project_root, monkeypatch, pattern
) -> None:
    monkeypatch.chdir(set_project_root)
    state_file = set_project_root / ".desloppify" / "state-python.json"
    issue_id = "strategy::verify-ci"
    state = state_mod.empty_state()
    state["last_scan"] = "2026-03-01T00:00:00+00:00"
    state["scan_count"] = 3
    state["work_items"][issue_id] = {
        "id": issue_id,
        "status": "open",
        "detector": "strategy",
        "tier": 2,
        "summary": "Verify CI executes tests",
        "file": "",
        "confidence": "high",
        "detail": {},
    }
    state_mod.save_state(state, state_file)
    save_plan(_seed_plan(issue_id))

    override_resolve.cmd_plan_resolve(
        argparse.Namespace(
            patterns=[pattern],
            attest=_ATTEST,
            note="Configured explicit test execution and verified the completed CI run.",
            confirm=False,
            force_resolve=False,
            state=state_file,
            lang="python",
            path=".",
            exclude=None,
        )
    )

    resolved = state_mod.load_state(state_file)["work_items"][issue_id]
    assert resolved["status"] == "fixed"
    assert resolved["resolved_at"]
    assert resolved["resolution_attestation"]["text"] == _ATTEST
    assert issue_id not in load_plan()["queue_order"]


def _seed_state() -> tuple[dict, str]:
    state = state_mod.empty_state()
    state["last_scan"] = "2026-03-01T00:00:00+00:00"
    state["scan_count"] = 3
    issue = state_mod.make_issue(
        "review",
        "src/example.py",
        "sample-issue",
        tier=1,
        confidence="high",
        summary="sample",
    )
    issue_id = issue["id"]
    state["work_items"][issue_id] = issue
    return state, issue_id


def _seed_plan(issue_id: str) -> dict:
    plan = empty_plan()
    plan["queue_order"] = [issue_id]
    return plan


def test_save_plan_state_transactional_rolls_back_on_plan_write_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    plan_file = tmp_path / "plan.json"

    initial_state, issue_id = _seed_state()
    initial_plan = _seed_plan(issue_id)
    state_mod.save_state(initial_state, state_file)
    save_plan(initial_plan, plan_file)
    before_state = state_file.read_text()
    before_plan = plan_file.read_text()

    changed_state = copy.deepcopy(initial_state)
    state_mod.resolve_issues(
        changed_state,
        issue_id,
        "wontfix",
        note="intentional debt",
        attestation=_ATTEST,
    )
    changed_plan = copy.deepcopy(initial_plan)
    skip_items(
        changed_plan,
        [issue_id],
        kind="permanent",
        note="intentional debt",
        attestation=_ATTEST,
    )

    def _boom(*_args, **_kwargs):
        raise OSError("simulated plan write failure")

    monkeypatch.setattr(override_io, "save_plan", _boom)
    with pytest.raises(CommandError) as excinfo:
        override_io.save_plan_state_transactional(
            plan=changed_plan,
            plan_path=plan_file,
            state_data=changed_state,
            state_path_value=state_file,
        )
    assert isinstance(excinfo.value.__cause__, OSError)

    assert state_file.read_text() == before_state
    assert plan_file.read_text() == before_plan


def test_cmd_plan_skip_permanent_rollback_when_plan_write_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    plan_file = tmp_path / "plan.json"

    initial_state, issue_id = _seed_state()
    initial_plan = _seed_plan(issue_id)
    state_mod.save_state(initial_state, state_file)
    save_plan(initial_plan, plan_file)

    runtime = CommandRuntime(
        config={},
        state=copy.deepcopy(initial_state),
        state_path=state_file,
    )
    args = argparse.Namespace(
        runtime=runtime,
        patterns=[issue_id],
        reason=None,
        review_after=None,
        permanent=True,
        false_positive=False,
        note="intentional debt",
        attest=_ATTEST,
    )

    monkeypatch.setattr(
        override_skip, "resolve_ids_from_patterns", lambda *_a, **_k: [issue_id]
    )

    def _boom(*_args, **_kwargs):
        raise OSError("simulated plan write failure")

    monkeypatch.setattr(override_io, "save_plan", _boom)

    with pytest.raises(CommandError) as excinfo:
        override_skip.cmd_plan_skip(args)
    assert isinstance(excinfo.value.__cause__, OSError)

    state_after = state_mod.load_state(state_file)
    plan_after = load_plan(plan_file)
    assert state_after["issues"][issue_id]["status"] == "open"
    assert plan_after.get("queue_order", []) == [issue_id]
    assert plan_after.get("skipped", {}) == {}
