"""Frozen-cycle coverage stays separate from later review arrivals."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from desloppify.app.commands.plan.triage.services import default_triage_services
from desloppify.app.commands.plan.triage.stages.reflect import cmd_stage_reflect
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.triage.prompt import collect_triage_input


def _issue(issue_id: str, *, kind: str = "review_defect", status: str = "open") -> dict:
    return {
        "id": issue_id,
        "status": status,
        "detector": "review" if kind == "review_defect" else "concerns",
        "work_item_kind": kind,
        "summary": "Synthetic lifecycle issue",
        "detail": {"dimension": "error_consistency"},
    }


def _frozen_cycle() -> tuple[dict, dict]:
    plan = empty_plan()
    plan["epic_triage_meta"] = {
        "active_triage_issue_ids": ["review::aaaa1111", "review::bbbb2222"],
        "triaged_ids": ["concerns::cccc3333", "review::eeee5555"],
    }
    state = {
        "last_scan": "2026-01-01T00:00:00Z",
        "work_items": {
            "review::aaaa1111": _issue("review::aaaa1111"),
            "review::bbbb2222": _issue("review::bbbb2222"),
            "concerns::cccc3333": _issue("concerns::cccc3333", kind="review_concern"),
            "review::dddd4444": _issue("review::dddd4444"),
            "review::eeee5555": _issue("review::eeee5555", status="fixed"),
            "unused::sample.py::dead": {
                "status": "open",
                "detector": "unused",
                "work_item_kind": "mechanical_defect",
            },
        },
    }
    return plan, state


def test_collector_only_requires_the_frozen_cycle() -> None:
    plan, state = _frozen_cycle()
    original_state = deepcopy(state)

    triage_input = collect_triage_input(plan, state)

    assert set(triage_input.review_issues) == {
        "review::aaaa1111",
        "review::bbbb2222",
    }
    assert set(triage_input.objective_backlog_issues) == {"unused::sample.py::dead"}
    assert state == original_state


def test_frozen_scope_preserves_live_history_and_new_arrival_context() -> None:
    plan, state = _frozen_cycle()
    plan["completed_clusters"] = [
        {"name": "previous-work", "issue_ids": ["review::eeee5555"]},
    ]

    triage_input = collect_triage_input(plan, state)

    assert triage_input.resolved_since_last == {"review::eeee5555"}
    assert set(triage_input.resolved_issues) == {"review::eeee5555"}
    assert triage_input.new_since_last == {"review::dddd4444"}
    assert triage_input.completed_clusters == plan["completed_clusters"]
    assert state["work_items"]["concerns::cccc3333"]["status"] == "open"


def _reflect(plan: dict, state: dict, issue_ids: list[str]) -> None:
    plan["queue_order"] = ["triage::reflect"]
    plan["epic_triage_meta"]["triage_stages"] = {
        "observe": {"report": "Synthetic findings observed.", "confirmed_at": "2026-01-01"},
    }
    report = (
        "error_consistency: Compare the current lifecycle findings against prior "
        "completed work and preserve unrelated issues for later review cycles.\n"
        "## Coverage Ledger\n"
        + "".join(f'- {issue_id} -> cluster "lifecycle-fixes"\n' for issue_id in issue_ids)
    )
    services = replace(
        default_triage_services(),
        command_runtime=lambda _args: SimpleNamespace(state=state),
        load_plan=lambda: plan,
        save_plan=lambda _plan: None,
        append_log_entry=lambda *_args, **_kwargs: None,
    )
    cmd_stage_reflect(argparse.Namespace(report=report, attestation=None), services=services)


def test_reflect_accepts_complete_frozen_subset_without_dispositioning_other_issues() -> None:
    plan, state = _frozen_cycle()
    original_state = deepcopy(state)

    _reflect(plan, state, ["review::aaaa1111", "review::bbbb2222"])

    meta = plan["epic_triage_meta"]
    stage = meta["triage_stages"]["reflect"]
    assert stage["issue_count"] == 2
    assert stage["cited_ids"] == ["review::aaaa1111", "review::bbbb2222"]
    assert set(meta["issue_dispositions"]) == {"review::aaaa1111", "review::bbbb2222"}
    assert meta["active_triage_issue_ids"] == ["review::aaaa1111", "review::bbbb2222"]
    assert state == original_state


def test_reflect_still_blocks_a_missing_in_scope_issue(capsys) -> None:
    plan, state = _frozen_cycle()
    original_state = deepcopy(state)

    _reflect(plan, state, ["review::aaaa1111"])

    assert "bbbb2222" in capsys.readouterr().out
    assert "reflect" not in plan["epic_triage_meta"]["triage_stages"]
    assert state == original_state


@pytest.mark.parametrize("active_ids", [None, []])
def test_unfrozen_reflect_requires_every_live_review_issue(active_ids, capsys) -> None:
    plan, state = _frozen_cycle()
    if active_ids is None:
        plan["epic_triage_meta"].pop("active_triage_issue_ids")
    else:
        plan["epic_triage_meta"]["active_triage_issue_ids"] = active_ids

    _reflect(plan, state, ["review::aaaa1111", "review::bbbb2222"])

    out = capsys.readouterr().out
    assert "cccc3333" in out
    assert "dddd4444" in out
    assert "reflect" not in plan["epic_triage_meta"]["triage_stages"]


@pytest.mark.parametrize("active_ids", [None, []])
def test_unfrozen_reflect_accepts_complete_live_review_coverage(active_ids) -> None:
    plan, state = _frozen_cycle()
    original_state = deepcopy(state)
    if active_ids is None:
        plan["epic_triage_meta"].pop("active_triage_issue_ids")
    else:
        plan["epic_triage_meta"]["active_triage_issue_ids"] = active_ids

    _reflect(
        plan,
        state,
        ["review::aaaa1111", "review::bbbb2222", "concerns::cccc3333", "review::dddd4444"],
    )

    stage = plan["epic_triage_meta"]["triage_stages"]["reflect"]
    assert stage["issue_count"] == 4
    assert len(stage["cited_ids"]) == 4
    assert state == original_state
