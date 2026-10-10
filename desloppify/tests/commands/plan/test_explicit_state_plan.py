"""Explicit state selections keep queue reads and plan mutations together."""

from __future__ import annotations

import json

import pytest

from desloppify import cli
from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine._plan.persistence import load_plan, plan_lock, save_plan
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._state.schema import empty_state


def _write_queue(directory, label):
    directory.mkdir(parents=True, exist_ok=True)
    issue_id = f"review::src/{label}.rs::ownership"
    state = empty_state()
    state["last_scan"] = "2026-01-01T00:00:00+00:00"
    state["work_items"][issue_id] = {
        "id": issue_id,
        "status": "open",
        "detector": "review",
        "file": f"src/{label}.rs",
        "summary": f"{label} ownership defect",
        "confidence": "high",
        "tier": 3,
        "detail": {"dimension": "design_coherence"},
    }
    state_file = directory / "state-rust.json"
    state_file.write_text(json.dumps(state))
    plan = empty_plan()
    plan["queue_order"] = [issue_id]
    plan["refresh_state"]["lifecycle_phase"] = "execute"
    save_plan(plan, directory / "plan.json")
    return state_file


@pytest.mark.parametrize("command", ["next", "queue"])
def test_cli_reads_plan_beside_explicit_state(monkeypatch, tmp_path, capsys, command):
    _write_queue(tmp_path / ".desloppify", "frontend")
    selected = _write_queue(tmp_path / ".desloppify" / "rust", "backend")
    monkeypatch.chdir(tmp_path)
    args = (
        ["next", "--state", str(selected)]
        if command == "next"
        else ["plan", "--state", str(selected), "queue"]
    )
    monkeypatch.setattr("sys.argv", ["desloppify", "--lang", "rust", *args])

    cli.main()

    output = capsys.readouterr().out
    assert "backend ownership defect" in output
    assert "frontend ownership defect" not in output


def test_cli_mutates_only_selected_plan_and_restores_default(monkeypatch, tmp_path):
    root_state = _write_queue(tmp_path / ".desloppify", "frontend")
    selected = _write_queue(tmp_path / ".desloppify" / "rust", "backend")
    root_plan = root_state.with_name("plan.json")
    original = root_plan.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "desloppify",
            "--lang",
            "rust",
            "plan",
            "--state",
            str(selected),
            "cluster",
            "create",
            "backend-fixes",
        ],
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        cli.main()
        assert load_plan()["queue_order"] == ["review::src/frontend.rs::ownership"]

    assert root_plan.read_bytes() == original
    assert "backend-fixes" in load_plan(selected.with_name("plan.json"))["clusters"]


def test_symlinked_state_uses_plan_beside_selected_path(monkeypatch, tmp_path, capsys):
    selected = _write_queue(tmp_path / ".desloppify" / "rust", "backend")
    target = _write_queue(tmp_path / "stored-state", "unrelated")
    target.write_bytes(selected.read_bytes())
    selected.unlink()
    selected.symlink_to(target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["desloppify", "--lang", "rust", "next", "--state", str(selected)]
    )

    cli.main()

    assert "backend ownership defect" in capsys.readouterr().out


def test_runtime_plan_override_applies_to_locks_and_explicit_paths_win(tmp_path):
    selected = tmp_path / "rust" / "plan.json"
    explicit = tmp_path / "explicit.json"
    with runtime_scope(RuntimeContext(project_root=tmp_path, plan_file=selected)):
        with plan_lock():
            save_plan(empty_plan())
        save_plan(empty_plan(), explicit)

    assert selected.exists()
    assert selected.with_suffix(".lock").exists()
    assert explicit.exists()
    assert not (tmp_path / ".desloppify" / "plan.json").exists()
