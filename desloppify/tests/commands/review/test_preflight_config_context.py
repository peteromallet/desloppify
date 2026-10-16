"""Review preparation must use the same configured target as its queue."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from desloppify.app.commands.review import cmd as review_cmd
from desloppify.base.exception_sets import CommandError
from desloppify.engine._plan import persistence as plan_persistence
from desloppify.engine._plan.schema import empty_plan

DIMENSION = "logic_clarity"
REMINDER = "stale_wontfix::src/old.py::accepted"


def _fixture(
    tmp_path, monkeypatch, *, target=100, queued_objective=False, review_issue=False
):
    reminder = {
        "id": REMINDER,
        "detector": "stale_wontfix",
        "status": "open",
        "file": "src/old.py",
        "confidence": "high",
        "detail": {},
    }
    state = {
        "last_scan": "2026-01-02T00:00:00+00:00",
        "scan_count": 2,
        "issues": {REMINDER: reminder},
        "subjective_assessments": {
            DIMENSION: {
                "score": 90.0,
                "needs_review_refresh": True,
                "refresh_reason": "review_issue_fixed",
                "stale_since": "2026-01-02T00:00:00+00:00",
            }
        },
        "dimension_scores": {
            "Logic clarity": {
                "score": 90.0,
                "strict": 90.0,
                "checks": 1,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": DIMENSION,
                        "placeholder": False,
                    }
                },
            }
        },
    }
    plan = empty_plan()
    plan["queue_order"] = [f"subjective::{DIMENSION}"]
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["refresh_state"] = {"lifecycle_phase": "plan"}
    plan["epic_triage_meta"] = {"triaged_ids": [REMINDER]}
    if queued_objective:
        plan["queue_order"].insert(0, REMINDER)
        plan["refresh_state"]["lifecycle_phase"] = "execute"
    if review_issue:
        fid = "review::src/new.py::pending"
        state["issues"][fid] = {
            "id": fid,
            "detector": "review",
            "status": "open",
            "file": "src/new.py",
            "confidence": "high",
            "detail": {"dimension": DIMENSION},
        }
        plan["queue_order"].insert(0, fid)
        plan["epic_triage_meta"]["triaged_ids"].append(fid)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(plan_persistence, "PLAN_FILE", path)
    config = {} if target is None else {"target_strict_score": target}
    runtime = SimpleNamespace(state=state, state_path=None, config=config)
    return runtime


@pytest.mark.parametrize("mode", ["prepare", "run_batches", "external_start"])
def test_configured_target_keeps_stale_assessment_runnable(tmp_path, monkeypatch, mode):
    runtime = _fixture(tmp_path, monkeypatch)
    before_config = deepcopy(runtime.config)
    selected = Mock()
    monkeypatch.setattr(review_cmd, "do_" + mode, selected)
    args = SimpleNamespace(
        dimensions=DIMENSION,
        force_review_rerun=False,
        run_batches=mode == "run_batches",
        external_start=mode == "external_start",
    )
    opts = review_cmd.ReviewOptions(
        run_batches=args.run_batches, external_start=args.external_start
    )
    review_cmd._run_review_mode(
        args,
        opts=opts,
        runtime=runtime,
        state=runtime.state,
        lang=None,
        state_file=None,
    )
    selected.assert_called_once()
    assert runtime.config == before_config
    assert runtime.state["issues"][REMINDER]["status"] == "open"


@pytest.mark.parametrize("target", [None, 85])
def test_default_and_explicit_default_keep_their_backlog_gate(
    tmp_path, monkeypatch, target
):
    runtime = _fixture(tmp_path, monkeypatch, target=target)
    before = deepcopy(runtime.state)
    args = SimpleNamespace(
        dimensions=DIMENSION,
        force_review_rerun=False,
        run_batches=True,
        external_start=False,
    )
    with pytest.raises(CommandError, match="objective: 1"):
        review_cmd._run_review_mode(
            args,
            opts=review_cmd.ReviewOptions(run_batches=True),
            runtime=runtime,
            state=runtime.state,
            lang=None,
            state_file=None,
        )
    assert runtime.state == before


@pytest.mark.parametrize(
    "backlog,phase",
    [("objective", "execute"), ("review", "plan"), ("review", "execute")],
)
def test_configured_target_preserves_genuine_prerequisite_gates(
    tmp_path, monkeypatch, backlog, phase
):
    runtime = _fixture(
        tmp_path,
        monkeypatch,
        queued_objective=backlog == "objective",
        review_issue=backlog == "review",
    )
    path = tmp_path / "plan.json"
    plan = json.loads(path.read_text())
    plan["refresh_state"]["lifecycle_phase"] = phase
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(review_cmd, "do_run_batches", Mock())
    before = deepcopy(runtime.state)
    args = SimpleNamespace(
        dimensions=DIMENSION,
        force_review_rerun=False,
        run_batches=True,
        external_start=False,
    )
    with pytest.raises(CommandError):
        review_cmd._run_review_mode(
            args,
            opts=review_cmd.ReviewOptions(run_batches=True),
            runtime=runtime,
            state=runtime.state,
            lang=None,
            state_file=None,
        )
    assert runtime.state == before


def test_configured_public_planning_phase_keeps_parked_objective_policy(
    tmp_path, monkeypatch
):
    runtime = _fixture(tmp_path, monkeypatch, queued_objective=True)
    path = tmp_path / "plan.json"
    plan = json.loads(path.read_text())
    plan["refresh_state"]["lifecycle_phase"] = "plan"
    path.write_text(json.dumps(plan))
    selected = Mock()
    monkeypatch.setattr(review_cmd, "do_run_batches", selected)
    args = SimpleNamespace(
        dimensions=DIMENSION,
        force_review_rerun=False,
        run_batches=True,
        external_start=False,
    )
    review_cmd._run_review_mode(
        args,
        opts=review_cmd.ReviewOptions(run_batches=True),
        runtime=runtime,
        state=runtime.state,
        lang=None,
        state_file=None,
    )
    selected.assert_called_once()
    assert runtime.state["issues"][REMINDER]["status"] == "open"
