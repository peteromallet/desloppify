"""An explicit state file keeps default plan I/O beside that state."""

from __future__ import annotations

import json
import sys

import pytest

import desloppify.cli as cli
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._state.schema import empty_state


@pytest.fixture
def isolated_states(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_file = tmp_path / ".desloppify" / "typescript" / "state-typescript.json"
    state_file.parent.mkdir(parents=True)
    issue_id = "security::src/service.ts::scoped"
    state = empty_state()
    state.update(last_scan="2026-10-10T00:00:00+00:00", scan_count=1, scan_path=".")
    state["work_items"][issue_id] = {
        "id": issue_id,
        "detector": "security",
        "file": "src/service.ts",
        "summary": "Scoped TypeScript finding",
        "status": "open",
        "tier": 1,
        "confidence": "high",
        "detail": {},
    }
    state_file.write_text(json.dumps(state))
    scoped_plan = empty_plan()
    scoped_plan["queue_order"] = [issue_id]
    scoped_path = state_file.parent / "plan.json"
    scoped_path.write_text(json.dumps(scoped_plan))
    root_plan = empty_plan()
    root_plan["queue_order"] = ["security::src/php.php::foreign"]
    root_plan["skipped"] = {"php-only": {"kind": "temporary"}}
    root_path = tmp_path / ".desloppify" / "plan.json"
    root_path.write_text(json.dumps(root_plan))
    return state_file, scoped_path, root_path


@pytest.mark.parametrize("command", [["next"], ["plan", "queue"]])
def test_explicit_state_queue_reads_its_sibling_plan(
    isolated_states,
    command,
    monkeypatch,
    capsys,
):
    state_file, scoped_path, root_path = isolated_states
    before = {path: path.read_bytes() for path in [state_file, scoped_path, root_path]}
    argv = [
        "desloppify",
        "--lang",
        "typescript",
        command[0],
        "--state",
        str(state_file),
    ]
    argv.extend(command[1:])
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert "Scoped TypeScript finding" in capsys.readouterr().out
    assert {path: path.read_bytes() for path in before} == before


def test_explicit_state_plan_reset_writes_only_its_sibling_plan(
    isolated_states,
    monkeypatch,
):
    state_file, scoped_path, root_path = isolated_states
    root_before = root_path.read_bytes()
    state_before = state_file.read_bytes()
    scoped_before = scoped_path.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "desloppify",
            "--lang",
            "typescript",
            "plan",
            "--state",
            str(state_file),
            "reset",
        ],
    )
    cli.main()
    assert json.loads(scoped_path.read_text())["queue_order"] == []
    assert scoped_path.with_suffix(".json.bak").read_bytes() == scoped_before
    assert root_path.read_bytes() == root_before
    assert state_file.read_bytes() == state_before


def test_explicit_state_plan_context_does_not_leak_to_next_invocation(
    isolated_states,
    monkeypatch,
):
    state_file, scoped_path, root_path = isolated_states
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "desloppify",
            "--lang",
            "typescript",
            "plan",
            "--state",
            str(state_file),
            "reset",
        ],
    )
    cli.main()
    scoped_before = scoped_path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["desloppify", "plan", "reset"])
    cli.main()
    assert json.loads(root_path.read_text())["queue_order"] == []
    assert scoped_path.read_bytes() == scoped_before
