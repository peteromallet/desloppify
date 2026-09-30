"""Exact issue selections must not mutate a sibling with a longer ID."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from desloppify.app.commands.plan.shared import patterns as plan_patterns
from desloppify.engine._state.resolution import match_issues, resolve_issues
from desloppify.engine.plan_state import empty_plan, plan_path_for_state, save_plan
from desloppify.state import empty_state, ensure_state_defaults, make_issue, save_state


def issue_state(*, target_status="open", suppressed=False):
    state = empty_state()
    for name in ("field", "field_extra", "other::abcd1234"):
        issue = make_issue(
            "dict_keys", "src/sample.py", f"dead_write::settings::{name}",
            tier=3, confidence="medium", summary=f"Synthetic field {name}",
        )
        state["work_items"][issue["id"]] = issue
    ids = list(state["work_items"])
    state["work_items"][ids[0]]["status"] = target_status
    state["work_items"][ids[0]]["suppressed"] = suppressed
    ensure_state_defaults(state)
    return state, ids


@pytest.mark.parametrize("status_filter", ["open", "all"])
def test_exact_state_id_wins_over_sibling_prefix(status_filter):
    state, (target, _, _) = issue_state()
    assert [i["id"] for i in match_issues(state, target, status_filter)] == [target]


@pytest.mark.parametrize("status", ["fixed", "wontfix", "false_positive"])
def test_closed_exact_id_does_not_fall_back_to_open_sibling(status):
    state, (target, sibling, _) = issue_state(target_status=status)
    assert match_issues(state, target) == []
    assert [i["id"] for i in match_issues(state, target, "all")] == [target]
    before = copy.deepcopy(state["work_items"][sibling])
    assert resolve_issues(state, target, "fixed", note="Reviewed synthetic finding") == []
    assert state["work_items"][sibling] == before


@pytest.mark.parametrize("status_filter", ["open", "all"])
def test_suppressed_exact_id_does_not_fall_back_to_sibling(status_filter):
    state, (target, _, _) = issue_state(suppressed=True)
    assert match_issues(state, target, status_filter) == []


@pytest.mark.parametrize("status", ["fixed", "wontfix", "false_positive"])
def test_exact_resolution_preserves_entire_sibling_record(status):
    state, (target, sibling, _) = issue_state()
    before = copy.deepcopy(state["work_items"][sibling])
    assert resolve_issues(state, target, status, note="Synthetic evidence", attestation="Reviewed") == [target]
    assert state["work_items"][target]["status"] == status
    assert state["work_items"][sibling] == before


def test_reopening_exact_closed_id_preserves_sibling_metadata():
    state, (target, sibling, _) = issue_state(target_status="false_positive")
    state["work_items"][sibling]["status"] = "wontfix"
    before = copy.deepcopy(state["work_items"][sibling])
    assert resolve_issues(state, target, "open", note="Recheck synthetic finding") == [target]
    assert state["work_items"][target]["reopen_count"] == 1
    assert state["work_items"][sibling] == before


@pytest.mark.parametrize("selector", ["glob", "prefix", "detector", "file", "directory"])
def test_explicit_bulk_selectors_keep_matching(selector):
    state, ids = issue_state()
    target, sibling, _ = ids
    pattern, expected = {
        "glob": (target + "*", [target, sibling]),
        "prefix": (target[:-2], [target, sibling]),
        "detector": ("dict_keys", ids),
        "file": ("src/sample.py", ids),
        "directory": ("src", ids),
    }[selector]
    assert [i["id"] for i in match_issues(state, pattern)] == expected


@pytest.mark.parametrize("selector", ["field", "abcd1234", "other"])
def test_name_and_hash_shorthand_keep_matching(selector):
    state, (target, _, hashed) = issue_state()
    expected = target if selector == "field" else hashed
    assert [i["id"] for i in match_issues(state, selector)] == [expected]


def test_glob_selected_exact_id_stays_exact_when_resolved_again():
    state, (target, sibling, _) = issue_state()
    selected = plan_patterns.resolve_ids_from_patterns(state, ["*" + target])
    assert selected == [target]
    before = copy.deepcopy(state["work_items"][sibling])
    for issue_id in selected:
        assert resolve_issues(state, issue_id, "false_positive", note="Synthetic review") == [target]
    assert state["work_items"][sibling] == before


@pytest.mark.parametrize("in_plan", [False, True])
def test_closed_state_exact_id_never_expands_in_plan_fallback(in_plan):
    state, (target, sibling, _) = issue_state(target_status="fixed")
    plan = empty_plan()
    plan["queue_order"] = [sibling] + ([target] if in_plan else [])
    assert plan_patterns.resolve_ids_from_patterns(state, [target], plan=plan) == ([target] if in_plan else [])


def test_exact_plan_only_id_wins_over_open_state_sibling():
    state, (target, sibling, _) = issue_state()
    del state["work_items"][target]
    plan = empty_plan()
    plan["queue_order"] = [target, sibling]
    assert plan_patterns.resolve_ids_from_patterns(state, [target], plan=plan) == [target]


def test_exact_queue_only_id_wins_over_synthetic_prefix_sibling(monkeypatch):
    state = empty_state()
    target = "subjective::naming"
    monkeypatch.setattr(plan_patterns, "_collect_queue_ids", lambda *_: {target, target + "_detail"})
    assert plan_patterns.resolve_ids_from_patterns(state, [target]) == [target]


def test_explicit_plan_glob_keeps_bulk_synthetic_selection():
    state = empty_state()
    target = "subjective::naming"
    plan = empty_plan()
    plan["queue_order"] = [target, target + "_detail"]
    assert plan_patterns.resolve_ids_from_patterns(state, [target + "*"], plan=plan) == plan["queue_order"]


@pytest.mark.parametrize("command", ["skip", "resolve"])
@pytest.mark.parametrize("leading_glob", [False, True])
def test_native_plan_commands_update_only_selected_exact_id(tmp_path, command, leading_glob):
    state, (target, sibling, _) = issue_state()
    state_dir = tmp_path / ".desloppify"
    state_dir.mkdir()
    state_path = state_dir / "state-python.json"
    state["last_scan"] = "2026-01-01T00:00:00+00:00"
    save_state(state, state_path)
    plan = empty_plan()
    plan["queue_order"] = list(state["work_items"])
    save_plan(plan, plan_path_for_state(state_path))
    (state_dir / "config.json").write_text(json.dumps({"generate_scorecard": False, "commit_tracking_enabled": False}))
    before = copy.deepcopy(state["work_items"][sibling])
    pattern = "*" + target if leading_glob else target
    arguments = ["--lang", "python", "plan", command, pattern,
        "--note", "Reviewed the synthetic finding against its fixture evidence",
        "--attest", "I have actually reviewed this finding and I am not gaming the score."]
    if command == "skip":
        arguments.append("--false-positive")
    else:
        arguments.append("--force-resolve")
    environment = dict(os.environ)
    source = str(Path(__file__).resolve().parents[4])
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-B", "-m", "desloppify", *arguments],
        cwd=tmp_path, env=environment, text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads(state_path.read_text())
    assert saved["work_items"][target]["status"] == ("false_positive" if command == "skip" else "fixed")
    assert saved["work_items"][sibling] == before
    saved_plan = json.loads(plan_path_for_state(state_path).read_text())
    if command == "skip":
        assert set(saved_plan["skipped"]) == {target}
    assert sibling in saved_plan["queue_order"]
