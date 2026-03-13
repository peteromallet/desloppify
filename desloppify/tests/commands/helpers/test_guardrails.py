"""Regression tests for triage guardrails around deferred mid-cycle triage."""

from __future__ import annotations

import pytest

from desloppify.app.commands.helpers.guardrails import (
    require_triage_current_or_exit,
    triage_guardrail_messages,
    triage_guardrail_status,
)
from desloppify.base.exception_sets import CommandError
from desloppify.engine._plan.schema import empty_plan


def _pending_triage_plan() -> dict:
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 72.0}
    plan["epic_triage_meta"] = {"triaged_ids": ["review::old"]}
    return plan


def _pending_triage_state() -> dict:
    return {
        "issues": {
            "obj::1": {
                "id": "obj::1",
                "status": "open",
                "detector": "complexity",
                "summary": "Objective work still open",
            },
            "review::old": {
                "id": "review::old",
                "status": "open",
                "detector": "review",
                "summary": "Previously triaged review issue",
                "detail": {"dimension": "naming"},
            },
            "review::new": {
                "id": "review::new",
                "status": "open",
                "detector": "review",
                "summary": "New review issue",
                "detail": {"dimension": "naming"},
            },
        }
    }


def test_triage_guardrail_status_marks_pending_behind_objective_backlog() -> None:
    result = triage_guardrail_status(
        plan=_pending_triage_plan(),
        state=_pending_triage_state(),
    )

    assert result.is_stale is True
    assert result.pending_behind_objective_backlog is True
    assert result.new_ids == {"review::new"}


def test_triage_guardrail_messages_use_pending_copy_when_triage_is_deferred() -> None:
    messages = triage_guardrail_messages(
        plan=_pending_triage_plan(),
        state=_pending_triage_state(),
    )

    assert any("activate after the current objective backlog is clear" in msg for msg in messages)
    assert any(msg.startswith("TRIAGE PENDING") for msg in messages)
    assert not any("Run the staged triage runner" in msg for msg in messages)


def test_require_triage_current_allows_objective_resolve_while_pending(capsys) -> None:
    require_triage_current_or_exit(
        state=_pending_triage_state(),
        plan=_pending_triage_plan(),
        patterns=["obj::1"],
        attest="",
    )

    out = capsys.readouterr().out
    assert "TRIAGE PENDING" in out


def test_require_triage_current_blocks_review_resolve_while_pending() -> None:
    with pytest.raises(CommandError) as exc_info:
        require_triage_current_or_exit(
            state=_pending_triage_state(),
            plan=_pending_triage_plan(),
            patterns=["review::new"],
            attest="",
        )

    assert "triage is pending behind the current objective backlog" in str(exc_info.value)
