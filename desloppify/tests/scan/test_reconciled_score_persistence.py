"""Scan output, saved state and plan baselines share reconciled scores."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

import desloppify.app.commands.scan.plan_reconcile as plan_reconcile
import desloppify.app.commands.scan.workflow as workflow
from desloppify.app.commands.scan.reporting.summary import show_score_delta
from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine._plan.persistence import load_plan, save_plan
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._scoring.state_integration import recompute_stats
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.schema import empty_state
from desloppify.languages.framework import make_lang_run
from desloppify.languages.python import PythonConfig
from desloppify.state_score_snapshot import score_snapshot


def issue(name, weight):
    return make_issue(
        "test_coverage",
        f"src/{name}.py",
        "untested_module",
        tier=3,
        confidence="high",
        summary="Synthetic owner has no direct mapping",
        detail={"kind": "untested_module", "loc": 40, "loc_weight": weight},
    )


@pytest.fixture
def scan_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skipped = issue("skipped_owner", 2.0)
    active = issue("active_owner", 3.0)
    for name in ("skipped_owner", "active_owner"):
        owner = tmp_path / "src" / f"{name}.py"
        owner.parent.mkdir(exist_ok=True)
        owner.write_text("def owner():\n    return 1\n")
    state_dir = tmp_path / ".desloppify"
    state_dir.mkdir()
    runtime = workflow.ScanRuntime(
        args=SimpleNamespace(force_resolve=False),
        state_path=state_dir / "state.json",
        state=empty_state(),
        path=tmp_path,
        config={"ignore": [], "needs_rescan": False},
        lang=make_lang_run(PythonConfig()),
        lang_label="",
        profile="full",
        effective_include_slow=True,
        zone_overrides=None,
    )
    plan = empty_plan()
    plan["queue_order"] = [active["id"]]
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        yield runtime, plan, skipped, active


def run_merge(runtime, plan, skipped, active):
    plan_path = runtime.state_path.parent / "plan.json"
    save_plan(plan, plan_path)
    result = workflow.merge_scan_results(
        runtime,
        [skipped, active],
        {"test_coverage": 10},
        {"total_files": 2},
    )
    return result, load_plan(plan_path)


def expected_scores(state):
    expected = deepcopy(state)
    recompute_stats(expected, scan_path=expected.get("scan_path"))
    return expected


@pytest.mark.parametrize("force_rescan", [False, True])
@pytest.mark.parametrize(
    "kind,status",
    [
        ("false_positive", "false_positive"),
        ("triage_observe_auto", "false_positive"),
        ("permanent", "wontfix"),
        ("temporary", "deferred"),
        ("triaged_out", "triaged_out"),
    ],
)
def test_first_scan_outputs_and_baseline_use_existing_skip_disposition(
    scan_fixture,
    force_rescan,
    kind,
    status,
    capsys,
):
    runtime, plan, skipped, active = scan_fixture
    runtime.force_rescan = force_rescan
    plan["skipped"][skipped["id"]] = {"kind": kind}
    previous_history = {"timestamp": "2025-01-01T00:00:00Z", "strict_score": 71.0}
    runtime.state["scan_history"] = [dict(previous_history)]
    result, saved_plan = run_merge(runtime, plan, skipped, active)
    assert runtime.state["work_items"][skipped["id"]]["status"] == status
    expected = expected_scores(runtime.state)
    expected_snapshot = score_snapshot(expected)

    assert score_snapshot(runtime.state) == expected_snapshot
    assert runtime.state["dimension_scores"] == expected["dimension_scores"]
    assert runtime.state["stats"] == expected["stats"]
    persisted = json.loads(runtime.state_path.read_text())
    assert persisted["work_items"][skipped["id"]]["status"] == status
    assert persisted["dimension_scores"] == expected["dimension_scores"]
    assert persisted["stats"] == expected["stats"]
    assert score_snapshot(persisted) == expected_snapshot
    assert persisted["scan_history"][0] == previous_history
    current_history = persisted["scan_history"][-1]
    assert current_history["strict_score"] == expected_snapshot.strict
    assert current_history["overall_score"] == expected_snapshot.overall
    assert current_history["open"] == expected["stats"]["open"]
    for dimension, scores in expected["dimension_scores"].items():
        assert current_history["dimension_scores"][dimension] == {
            "score": scores["score"],
            "strict": scores.get("strict", scores["score"]),
        }
    assert saved_plan["plan_start_scores"]["strict"] == expected_snapshot.strict
    assert saved_plan["plan_start_scores"]["overall"] == expected_snapshot.overall

    events = [
        json.loads(line)
        for line in (runtime.state_path.parent / "progression.jsonl")
        .read_text()
        .splitlines()
    ]
    completed = next(e for e in events if e["event_type"] == "scan_complete")
    for dimension, scores in expected["dimension_scores"].items():
        assert completed["payload"]["dimension_scores"][dimension] == {
            key: scores[key] for key in ("score", "strict") if key in scores
        }
    capsys.readouterr()
    show_score_delta(
        runtime.state,
        result.prev_overall,
        result.prev_objective,
        result.prev_strict,
        result.prev_verified,
    )
    output = capsys.readouterr().out
    assert f"overall {expected_snapshot.overall:.1f}/100" in output
    assert f"strict {expected_snapshot.strict:.1f}/100" in output


def test_midcycle_scan_preserves_frozen_baseline_but_saves_live_scores(scan_fixture):
    runtime, plan, skipped, active = scan_fixture
    plan["plan_start_scores"] = {"strict": 73.0, "overall": 74.0}
    plan["skipped"][skipped["id"]] = {"kind": "false_positive"}
    _, saved_plan = run_merge(runtime, plan, skipped, active)
    expected = expected_scores(runtime.state)
    assert score_snapshot(runtime.state) == score_snapshot(expected)
    assert score_snapshot(json.loads(runtime.state_path.read_text())) == score_snapshot(
        expected
    )
    assert saved_plan["plan_start_scores"] == {"strict": 73.0, "overall": 74.0}


def test_expired_temporary_skip_is_reopened_and_persisted(scan_fixture):
    runtime, plan, skipped, active = scan_fixture
    plan["skipped"][skipped["id"]] = {
        "kind": "temporary",
        "skipped_at_scan": 0,
        "review_after": 1,
    }
    _, saved_plan = run_merge(runtime, plan, skipped, active)
    expected = expected_scores(runtime.state)
    assert runtime.state["work_items"][skipped["id"]]["status"] == "open"
    assert skipped["id"] not in saved_plan["skipped"]
    assert skipped["id"] in saved_plan["queue_order"]
    persisted = json.loads(runtime.state_path.read_text())
    assert persisted["work_items"][skipped["id"]]["status"] == "open"
    assert persisted["stats"] == expected["stats"]
    assert score_snapshot(persisted) == score_snapshot(expected)


@pytest.mark.parametrize("operation", ["load_plan", "save_plan"])
def test_plan_io_failure_keeps_scan_persistence_consistent(
    scan_fixture, monkeypatch, operation
):
    runtime, plan, skipped, active = scan_fixture
    plan["skipped"][skipped["id"]] = {"kind": "false_positive"}

    def fail(*args, **kwargs):
        raise OSError("synthetic plan I/O failure")

    monkeypatch.setattr(plan_reconcile, operation, fail)
    run_merge(runtime, plan, skipped, active)
    expected = expected_scores(runtime.state)
    persisted = json.loads(runtime.state_path.read_text())
    expected_status = "open" if operation == "load_plan" else "false_positive"
    assert persisted["work_items"][skipped["id"]]["status"] == expected_status
    assert persisted["stats"] == expected["stats"]
    assert score_snapshot(persisted) == score_snapshot(expected)


def test_failed_state_save_does_not_clear_needs_rescan(scan_fixture, monkeypatch):
    runtime, plan, skipped, active = scan_fixture
    runtime.config["needs_rescan"] = True

    def fail(*args, **kwargs):
        raise OSError("synthetic state I/O failure")

    monkeypatch.setattr(workflow, "save_state", fail)
    with pytest.raises(OSError, match="synthetic state I/O failure"):
        run_merge(runtime, plan, skipped, active)
    assert runtime.config["needs_rescan"] is True
    assert not runtime.state_path.exists()
    assert not (runtime.state_path.parent / "progression.jsonl").exists()


def test_completed_cycle_reveal_is_available_once_and_not_saved(scan_fixture, capsys):
    runtime, plan, skipped, active = scan_fixture
    plan["queue_order"] = []
    plan["plan_start_scores"] = {"strict": 73.0, "overall": 74.0}
    plan["skipped"][skipped["id"]] = {"kind": "false_positive"}
    save_plan(plan, runtime.state_path.parent / "plan.json")
    result = workflow.merge_scan_results(
        runtime, [skipped], {"test_coverage": 10}, {"total_files": 1}
    )
    assert runtime.state["_plan_start_scores_for_reveal"]["strict"] == 73.0
    assert "_plan_start_scores_for_reveal" not in json.loads(
        runtime.state_path.read_text()
    )
    capsys.readouterr()
    show_score_delta(
        runtime.state,
        result.prev_overall,
        result.prev_objective,
        result.prev_strict,
        result.prev_verified,
    )
    assert "SCORE UPDATE" in capsys.readouterr().out
    assert "_plan_start_scores_for_reveal" not in runtime.state
    show_score_delta(runtime.state, None, None, None, None)
    assert "SCORE UPDATE" not in capsys.readouterr().out
