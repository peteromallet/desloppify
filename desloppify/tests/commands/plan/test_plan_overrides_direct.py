"""Direct tests for plan override helper modules."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.app.commands.plan.override.io as override_io_mod
import desloppify.app.commands.plan.override.misc as override_misc_mod
import desloppify.app.commands.plan.override.resolve_cmd as override_resolve_cmd_mod
import desloppify.app.commands.plan.override.resolve_helpers as resolve_helpers_mod
import desloppify.app.commands.plan.override.resolve_workflow as resolve_workflow_mod
import desloppify.app.commands.plan.override.skip as override_skip_mod
import desloppify.app.commands.plan.reorder_handlers as reorder_handlers_mod
from desloppify.base.exception_sets import CommandError


def test_override_io_snapshot_restore_and_plan_file_resolution(
    monkeypatch, tmp_path
) -> None:
    assert override_io_mod._plan_file_for_state(None) is None

    state_path = tmp_path / "state.json"
    expected_plan_path = tmp_path / "state.plan.json"
    monkeypatch.setattr(
        override_io_mod, "plan_path_for_state", lambda _path: expected_plan_path
    )
    assert override_io_mod._plan_file_for_state(state_path) == expected_plan_path

    target = tmp_path / "sample.txt"
    assert override_io_mod._snapshot_file(target) is None

    target.write_text("before", encoding="utf-8")
    snap = override_io_mod._snapshot_file(target)
    assert snap == "before"

    override_io_mod._restore_file_snapshot(target, "after")
    assert target.read_text(encoding="utf-8") == "after"

    override_io_mod._restore_file_snapshot(target, None)
    assert not target.exists()


def test_override_resolve_helpers_cover_synthetic_split_and_blocked_stages(
    capsys,
) -> None:
    synthetic, remaining = resolve_helpers_mod.split_synthetic_patterns(
        ["triage::reflect", "workflow::create-plan", "unused::src/a.py::X"]
    )
    assert synthetic == ["triage::reflect", "workflow::create-plan"]
    assert remaining == ["unused::src/a.py::X"]
    assert resolve_helpers_mod.resolve_synthetic_ids(
        ["triage::reflect", "unused::src/a.py::X"]
    ) == (["triage::reflect"], ["unused::src/a.py::X"])

    plan = {
        "queue_order": ["triage::observe", "triage::reflect", "triage::organize"],
        "epic_triage_meta": {"triage_stages": {}},
    }
    blocked = resolve_helpers_mod.blocked_triage_stages(plan)
    assert blocked["triage::reflect"] == ["triage::observe"]
    assert blocked["triage::organize"] == ["triage::reflect"]

    state = {
        "issues": {
            "i1": {"status": "open", "summary": "First", "detector": "review"},
            "i2": {"status": "open", "summary": "Second", "detector": "review"},
        }
    }
    cluster_plan = {"clusters": {"small": {"issue_ids": ["i1", "i2"]}}}
    blocked_cluster = resolve_helpers_mod.check_cluster_guard(
        ["small"], cluster_plan, state
    )
    assert blocked_cluster is False
    out = capsys.readouterr().out
    assert out == ""

    step_cluster_plan = {
        "clusters": {
            "step-cluster": {
                "issue_ids": ["i1", "i2"],
                "action_steps": [{"title": "Do auth fix", "issue_refs": ["i1", "i2"]}],
            }
        }
    }
    blocked_step_cluster = resolve_helpers_mod.check_cluster_guard(
        ["step-cluster"], step_cluster_plan, state
    )
    assert blocked_step_cluster is False


def test_override_resolve_cmd_confirm_allows_small_cluster(monkeypatch) -> None:
    state = {
        "issues": {
            "i1": {"status": "open", "summary": "First", "detector": "review"},
            "i2": {"status": "open", "summary": "Second", "detector": "review"},
        }
    }
    plan = {"clusters": {"small": {"issue_ids": ["i1", "i2"]}}}
    delegated: list[argparse.Namespace] = []

    monkeypatch.setattr(
        override_resolve_cmd_mod,
        "command_runtime",
        lambda _args: SimpleNamespace(state=state),
    )
    monkeypatch.setattr(override_resolve_cmd_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(override_resolve_cmd_mod, "cmd_resolve", delegated.append)

    override_resolve_cmd_mod.cmd_plan_resolve(
        argparse.Namespace(
            patterns=["small"],
            attest=None,
            note="resolved the small cluster by applying the reviewed fix",
            confirm=True,
            force_resolve=False,
            state=None,
            lang=None,
            path=".",
            exclude=None,
        )
    )

    assert len(delegated) == 1
    assert delegated[0].patterns == ["small"]
    assert delegated[0].status == "fixed"
    assert delegated[0].attest.startswith("I have actually resolved the small cluster")


def test_override_resolve_cmd_confirm_requires_note(capsys) -> None:
    args = argparse.Namespace(
        patterns=["unused::src/a.py::X"],
        attest=None,
        note=None,
        confirm=True,
        force_resolve=False,
        state=None,
        lang=None,
        path=".",
        exclude=None,
    )
    override_resolve_cmd_mod.cmd_plan_resolve(args)
    out = capsys.readouterr().out
    assert "--confirm requires --note" in out


def test_override_resolve_cmd_rejects_protected_review_id(monkeypatch, capsys) -> None:
    state = {
        "issues": {
            "held": {"id": "held", "status": "open", "detector": "review"},
        }
    }
    plan = {"epic_triage_meta": {"protected_review_issue_ids": ["held"]}}
    delegated: list[argparse.Namespace] = []

    monkeypatch.setattr(
        override_resolve_cmd_mod,
        "command_runtime",
        lambda _args: SimpleNamespace(state=state),
    )
    monkeypatch.setattr(override_resolve_cmd_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(override_resolve_cmd_mod, "cmd_resolve", delegated.append)

    override_resolve_cmd_mod.cmd_plan_resolve(
        argparse.Namespace(
            patterns=["held"],
            attest=None,
            note="Kept this review finding out of the automated triage queue",
            confirm=True,
            force_resolve=False,
            state=None,
            lang=None,
            path=".",
            exclude=None,
        )
    )

    assert delegated == []
    assert "Cannot resolve protected review item" in capsys.readouterr().out


def test_override_skip_cmd_rejects_protected_review_id(monkeypatch, capsys) -> None:
    state = {
        "scan_metadata": {"source": "scan"},
        "last_scan": "2026-07-31T00:00:00+00:00",
        "issues": {
            "held": {"id": "held", "status": "open", "detector": "review"},
        }
    }
    plan = {"epic_triage_meta": {"protected_review_issue_ids": ["held"]}}
    state_transitions: list[str] = []

    monkeypatch.setattr(
        override_skip_mod,
        "command_runtime",
        lambda _args: SimpleNamespace(state=state, state_path=Path("state.json")),
    )
    monkeypatch.setattr(override_skip_mod, "load_plan", lambda _path=None: plan)
    monkeypatch.setattr(
        override_skip_mod,
        "_apply_state_skip_resolution",
        lambda **_kwargs: state_transitions.append("resolved"),
    )

    override_skip_mod.cmd_plan_skip(
        argparse.Namespace(
            patterns=["held"],
            reason="later",
            review_after=None,
            permanent=False,
            false_positive=False,
            note=None,
            attest=None,
            confirm=False,
        )
    )

    assert state_transitions == []
    assert "Cannot skip protected review item" in capsys.readouterr().out


def test_override_resolve_cmd_handles_synthetic_only_resolution(
    monkeypatch, capsys
) -> None:
    plan = {"queue_order": ["triage::observe"], "clusters": {}}
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(resolve_workflow_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(resolve_workflow_mod, "blocked_triage_stages", lambda _plan: {})
    monkeypatch.setattr(
        resolve_workflow_mod,
        "purge_ids",
        lambda _plan, ids: calls.append(("purge", list(ids))),
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "auto_complete_steps",
        lambda _plan: ["step complete"],
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "append_log_entry",
        lambda *_a, **_k: calls.append(("log", [])),
    )
    monkeypatch.setattr(resolve_workflow_mod, "save_plan", lambda *_a, **_k: None)

    args = argparse.Namespace(
        patterns=["triage::observe"],
        attest=None,
        note=None,
        confirm=False,
        force_resolve=False,
        state=None,
        lang=None,
        path=".",
        exclude=None,
    )
    override_resolve_cmd_mod.cmd_plan_resolve(args)
    out = capsys.readouterr().out
    assert "Resolved: triage::observe" in out
    assert ("purge", ["triage::observe"]) in calls


def test_resolve_workflow_patterns_triage_gate_blocks_and_logs(
    monkeypatch, capsys
) -> None:
    plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        "epic_triage_meta": {"triage_stages": {}},
    }
    logs: list[tuple[str, dict]] = []
    injected: list[bool] = []

    monkeypatch.setattr(resolve_workflow_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(resolve_workflow_mod, "blocked_triage_stages", lambda _plan: {})
    monkeypatch.setattr(
        resolve_workflow_mod, "has_triage_in_queue", lambda _plan: False
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "inject_triage_stages",
        lambda _plan: injected.append(True),
    )
    monkeypatch.setattr(resolve_workflow_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        resolve_workflow_mod,
        "append_log_entry",
        lambda _plan, action, **kwargs: logs.append((action, kwargs)),
    )

    args = argparse.Namespace(
        force_resolve=False, state=None, lang=None, path=".", exclude=None
    )
    outcome = resolve_workflow_mod.resolve_workflow_patterns(
        args,
        synthetic_ids=[resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        real_patterns=[],
        note=None,
    )
    out = capsys.readouterr().out

    assert outcome.status == "blocked"
    assert outcome.remaining_patterns == []
    assert "triage not complete" in out
    assert "Remaining stages:" in out
    assert injected == [True]
    assert any(action == "workflow_blocked" for action, _ in logs)


def test_resolve_workflow_patterns_force_resolve_requires_long_note(
    monkeypatch, capsys
) -> None:
    plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        "epic_triage_meta": {"triage_stages": {}},
    }
    monkeypatch.setattr(resolve_workflow_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(resolve_workflow_mod, "blocked_triage_stages", lambda _plan: {})
    monkeypatch.setattr(resolve_workflow_mod, "has_triage_in_queue", lambda _plan: True)
    monkeypatch.setattr(resolve_workflow_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        resolve_workflow_mod, "append_log_entry", lambda *_a, **_k: None
    )

    args = argparse.Namespace(
        force_resolve=True, state=None, lang=None, path=".", exclude=None
    )
    outcome = resolve_workflow_mod.resolve_workflow_patterns(
        args,
        synthetic_ids=[resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        real_patterns=[],
        note="too short",
    )
    out = capsys.readouterr().out

    assert outcome.status == "blocked"
    assert "--force-resolve still requires --note (min 50 chars)" in out


def test_resolve_workflow_patterns_scan_gate_blocks_without_new_scan(
    monkeypatch, capsys
) -> None:
    plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_SCORE_CHECKPOINT_ID],
        "epic_triage_meta": {
            "triage_stages": {},
            "last_completed_at": "2026-03-09T00:00:00+00:00",
        },
        "scan_count_at_plan_start": 9,
        "scan_gate_skipped": False,
    }
    logs: list[tuple[str, dict]] = []

    monkeypatch.setattr(resolve_workflow_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(resolve_workflow_mod, "blocked_triage_stages", lambda _plan: {})
    monkeypatch.setattr(resolve_workflow_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        resolve_workflow_mod, "state_path", lambda _args: Path("state.json")
    )
    monkeypatch.setattr(
        resolve_workflow_mod.state_mod, "load_state", lambda _path: {"scan_count": 9}
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "append_log_entry",
        lambda _plan, action, **kwargs: logs.append((action, kwargs)),
    )

    args = argparse.Namespace(
        force_resolve=False, state=None, lang=None, path=".", exclude=None
    )
    outcome = resolve_workflow_mod.resolve_workflow_patterns(
        args,
        synthetic_ids=[resolve_workflow_mod.WORKFLOW_SCORE_CHECKPOINT_ID],
        real_patterns=[],
        note=None,
    )
    out = capsys.readouterr().out

    assert outcome.status == "blocked"
    assert "no scan has run this cycle" in out
    assert "desloppify scan" in out
    assert any(action == "scan_gate_blocked" for action, _ in logs)


def test_resolve_workflow_patterns_reconciles_when_create_plan_drains_queue(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        "epic_triage_meta": {
            "triage_stages": {},
            "last_completed_at": "2026-03-09T00:00:00+00:00",
        },
        "scan_count_at_plan_start": 9,
    }
    seen: list[object] = []

    monkeypatch.setattr(resolve_workflow_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(resolve_workflow_mod, "blocked_triage_stages", lambda _plan: {})
    monkeypatch.setattr(
        resolve_workflow_mod, "save_plan", lambda *_a, **_k: seen.append("save")
    )
    monkeypatch.setattr(
        resolve_workflow_mod, "state_path", lambda _args: Path("state.json")
    )
    monkeypatch.setattr(
        resolve_workflow_mod.state_mod,
        "load_state",
        lambda _path: {"scan_count": 10, "config": {"target_strict_score": 96}},
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "append_log_entry",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        resolve_workflow_mod, "live_planned_queue_empty", lambda _plan: True
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "has_open_review_issues",
        lambda _state, _plan=None: True,
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 96.0,
    )
    monkeypatch.setattr(
        resolve_workflow_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            (
                "reconcile",
                list(_plan.get("queue_order", [])),
                target_strict,
                _plan.get("refresh_state", {}).get("workflow_plan_just_resolved"),
            )
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": False, "lifecycle_phase": "triage"},
        )(),
    )

    args = argparse.Namespace(
        force_resolve=False, state=None, lang=None, path=".", exclude=None
    )
    outcome = resolve_workflow_mod.resolve_workflow_patterns(
        args,
        synthetic_ids=[resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        real_patterns=[],
        note="Detailed workflow completion note",
    )

    assert outcome.status == "handled"
    assert ("target", {"target_strict_score": 96}) in seen
    assert (
        "reconcile",
        [],
        96.0,
        True,
    ) in seen


def test_cmd_plan_resolve_workflow_gate_integration_paths(monkeypatch, capsys) -> None:
    """Command-level workflow gating smoke: triage block, short forced note, scan gate."""
    current_plan: dict = {}
    state = {"scan_count": 0}
    resolve_calls: list[argparse.Namespace] = []

    monkeypatch.setattr(resolve_workflow_mod, "load_plan", lambda: current_plan)
    monkeypatch.setattr(resolve_workflow_mod, "blocked_triage_stages", lambda _plan: {})
    monkeypatch.setattr(resolve_workflow_mod, "has_triage_in_queue", lambda _plan: True)
    monkeypatch.setattr(resolve_workflow_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        resolve_workflow_mod, "append_log_entry", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        resolve_workflow_mod, "state_path", lambda _args: Path("state.json")
    )
    monkeypatch.setattr(
        resolve_workflow_mod.state_mod, "load_state", lambda _path: state
    )
    monkeypatch.setattr(
        override_resolve_cmd_mod,
        "cmd_resolve",
        lambda resolve_args: resolve_calls.append(resolve_args),
    )

    current_plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        "epic_triage_meta": {"triage_stages": {}},
    }
    override_resolve_cmd_mod.cmd_plan_resolve(
        argparse.Namespace(
            patterns=[resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
            attest=None,
            note=None,
            confirm=False,
            force_resolve=False,
            state=None,
            lang=None,
            path=".",
            exclude=None,
        )
    )
    out_triage = capsys.readouterr().out

    current_plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
        "epic_triage_meta": {"triage_stages": {}},
    }
    override_resolve_cmd_mod.cmd_plan_resolve(
        argparse.Namespace(
            patterns=[resolve_workflow_mod.WORKFLOW_CREATE_PLAN_ID],
            attest=None,
            note="too short",
            confirm=False,
            force_resolve=True,
            state=None,
            lang=None,
            path=".",
            exclude=None,
        )
    )
    out_short = capsys.readouterr().out

    current_plan = {
        "queue_order": [resolve_workflow_mod.WORKFLOW_SCORE_CHECKPOINT_ID],
        "epic_triage_meta": {
            "triage_stages": {},
            "last_completed_at": "2026-03-09T00:00:00+00:00",
        },
        "scan_count_at_plan_start": 4,
        "scan_gate_skipped": False,
    }
    state["scan_count"] = 4
    override_resolve_cmd_mod.cmd_plan_resolve(
        argparse.Namespace(
            patterns=[resolve_workflow_mod.WORKFLOW_SCORE_CHECKPOINT_ID],
            attest=None,
            note=None,
            confirm=False,
            force_resolve=False,
            state=None,
            lang=None,
            path=".",
            exclude=None,
        )
    )
    out_scan = capsys.readouterr().out

    assert "triage not complete" in out_triage
    assert "--force-resolve still requires --note (min 50 chars)" in out_short
    assert "no scan has run this cycle" in out_scan
    assert resolve_calls == []


def test_override_misc_focus_and_scan_gate_paths(monkeypatch, capsys) -> None:
    plan = {
        "clusters": {"alpha": {}},
        "active_cluster": None,
        "scan_count_at_plan_start": 3,
        "scan_gate_skipped": False,
    }
    monkeypatch.setattr(override_misc_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(override_misc_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(override_misc_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_misc_mod,
        "set_focus",
        lambda p, name: p.update({"active_cluster": name}),
    )
    monkeypatch.setattr(
        override_misc_mod, "clear_focus", lambda p: p.update({"active_cluster": None})
    )

    override_misc_mod.cmd_plan_focus(
        argparse.Namespace(clear=False, cluster_name="alpha")
    )
    out_focus = capsys.readouterr().out
    assert "Focused on: alpha" in out_focus
    assert plan["active_cluster"] == "alpha"

    override_misc_mod.cmd_plan_focus(argparse.Namespace(clear=True, cluster_name=None))
    out_clear = capsys.readouterr().out
    assert "Focus cleared" in out_clear

    monkeypatch.setattr(
        override_misc_mod, "state_path", lambda _args: Path("state.json")
    )
    monkeypatch.setattr(
        override_misc_mod, "load_state", lambda _path: {"scan_count": 3}
    )

    override_misc_mod.cmd_plan_scan_gate(argparse.Namespace(skip=False, note=None))
    out_blocked = capsys.readouterr().out
    assert "Scan gate: BLOCKED" in out_blocked

    override_misc_mod.cmd_plan_scan_gate(
        argparse.Namespace(skip=True, note="too short")
    )
    out_short = capsys.readouterr().out
    assert "requires --note with at least 50 chars" in out_short

    long_note = (
        "Skipping scan gate in this direct test because we are verifying "
        "guard behavior and not advancing a real cycle."
    )
    override_misc_mod.cmd_plan_scan_gate(argparse.Namespace(skip=True, note=long_note))
    out_skip = capsys.readouterr().out
    assert "marked as satisfied" in out_skip
    assert plan["scan_gate_skipped"] is True


def test_plan_promote_moves_backlog_items_into_queue(monkeypatch, capsys) -> None:
    plan = {"queue_order": [], "clusters": {}}
    runtime = SimpleNamespace(state={"issues": {"unused::a": {"status": "open"}}})
    moved: list[tuple[list[str], str, str | None]] = []

    monkeypatch.setattr(reorder_handlers_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(
        reorder_handlers_mod, "require_issue_inventory", lambda _state: True
    )
    monkeypatch.setattr(reorder_handlers_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(reorder_handlers_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        reorder_handlers_mod, "append_log_entry", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        reorder_handlers_mod,
        "resolve_ids_from_patterns",
        lambda *_a, **_k: ["unused::a"],
    )

    def _move_items(plan_obj, issue_ids, position, target=None, offset=None):
        moved.append((list(issue_ids), position, target))
        plan_obj["queue_order"].extend(issue_ids)
        return len(issue_ids)

    monkeypatch.setattr(reorder_handlers_mod, "move_items", _move_items)

    reorder_handlers_mod.cmd_plan_promote(
        argparse.Namespace(patterns=["unused"], position="top", target=None)
    )
    out = capsys.readouterr().out

    assert "Promoted 1 item(s)" in out
    assert moved == [(["unused::a"], "top", None)]
    assert plan["queue_order"] == ["unused::a"]
    assert plan["promoted_ids"] == ["unused::a"]


def test_plan_promote_filters_resolved_cluster_members(monkeypatch, capsys) -> None:
    plan = {
        "queue_order": [],
        "clusters": {"cluster-a": {"issue_ids": ["fixed::a", "unused::b"]}},
    }
    runtime = SimpleNamespace(
        state={
            "issues": {
                "fixed::a": {"id": "fixed::a", "status": "fixed"},
                "unused::b": {"id": "unused::b", "status": "open"},
            }
        }
    )
    saved: list[dict] = []

    monkeypatch.setattr(reorder_handlers_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(reorder_handlers_mod, "require_issue_inventory", lambda _state: True)
    monkeypatch.setattr(reorder_handlers_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(reorder_handlers_mod, "save_plan", lambda plan_obj: saved.append(plan_obj))
    monkeypatch.setattr(reorder_handlers_mod, "append_log_entry", lambda *_a, **_k: None)

    reorder_handlers_mod.cmd_plan_promote(
        argparse.Namespace(patterns=["cluster-a"], position="top", target=None)
    )
    out = capsys.readouterr().out

    assert "Promoted 1 item(s)" in out
    assert plan["queue_order"] == ["unused::b"]
    assert plan["promoted_ids"] == ["unused::b"]
    assert saved == [plan]


def test_plan_promote_noops_when_cluster_has_no_actionable_members(monkeypatch, capsys) -> None:
    plan = {"queue_order": [], "clusters": {"cluster-a": {"issue_ids": ["fixed::a"]}}}
    runtime = SimpleNamespace(
        state={"issues": {"fixed::a": {"id": "fixed::a", "status": "fixed"}}}
    )
    saved: list[dict] = []

    monkeypatch.setattr(reorder_handlers_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(reorder_handlers_mod, "require_issue_inventory", lambda _state: True)
    monkeypatch.setattr(reorder_handlers_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(reorder_handlers_mod, "save_plan", lambda plan_obj: saved.append(plan_obj))

    reorder_handlers_mod.cmd_plan_promote(
        argparse.Namespace(patterns=["cluster-a"], position="top", target=None)
    )
    out = capsys.readouterr().out

    assert "No matching actionable issues found" in out
    assert plan["queue_order"] == []
    assert saved == []


def test_override_skip_helpers_and_commands(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        override_skip_mod, "skip_kind_requires_attestation", lambda _kind: True
    )
    monkeypatch.setattr(
        override_skip_mod,
        "validate_attestation",
        lambda _att, **_kwargs: False,
    )
    assert (
        override_skip_mod._validate_skip_requirements(
            kind="permanent",
            attestation=None,
            note="x",
        )
        is False
    )

    monkeypatch.setattr(override_skip_mod, "skip_kind_state_status", lambda _kind: None)
    assert (
        override_skip_mod._apply_state_skip_resolution(
            kind="temporary",
            state_file=None,
            issue_ids=["i1"],
            note=None,
            attestation=None,
        )
        is None
    )
    monkeypatch.setattr(
        override_skip_mod, "skip_kind_requires_attestation", lambda _kind: False
    )

    runtime = SimpleNamespace(
        state={"last_scan": "2026-03-01T00:00:00+00:00", "scan_count": 2, "issues": {}},
        state_path=None,
    )
    monkeypatch.setattr(override_skip_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(
        override_skip_mod, "require_issue_inventory", lambda _state: True
    )
    monkeypatch.setattr(
        override_skip_mod, "load_plan", lambda _plan_file=None: {"queue_order": []}
    )
    monkeypatch.setattr(
        override_skip_mod,
        "resolve_ids_from_patterns",
        lambda *_a, **_k: [f"i{n}" for n in range(6)],
    )

    with pytest.raises(CommandError):
        override_skip_mod.cmd_plan_skip(
            argparse.Namespace(
                patterns=["review::*"],
                reason=None,
                review_after=None,
                permanent=False,
                false_positive=False,
                note=None,
                attest=None,
                confirm=False,
            )
        )

    plan = {"queue_order": ["i1"], "skipped": {"i1": {"kind": "temporary"}}}
    monkeypatch.setattr(override_skip_mod, "load_plan", lambda _plan_file=None: plan)
    monkeypatch.setattr(
        override_skip_mod,
        "resolve_ids_from_patterns",
        lambda *_a, **_k: ["i1"],
    )
    monkeypatch.setattr(
        override_skip_mod,
        "unskip_items",
        lambda *_a, **_k: (1, ["i1"], []),
    )
    monkeypatch.setattr(
        override_skip_mod.state_mod,
        "load_state",
        lambda _path: {"issues": {"i1": {"status": "wontfix"}}},
    )
    monkeypatch.setattr(
        override_skip_mod.state_mod,
        "resolve_issues",
        lambda _state, fid, _status: [fid],
    )
    monkeypatch.setattr(override_skip_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_skip_mod,
        "save_plan_state_transactional",
        lambda **_kwargs: None,
    )

    override_skip_mod.cmd_plan_unskip(argparse.Namespace(patterns=["i1"], force=False))
    out = capsys.readouterr().out
    assert "Unskipped 1 item(s)" in out


def test_cmd_plan_skip_reconciles_with_fresh_state_after_invalidation(
    monkeypatch,
) -> None:
    runtime_state = {
        "scan_count": 2,
        "issues": {},
        "config": {"target_strict_score": 90},
    }
    fresh_state = {"scan_count": 2, "issues": {}, "config": {"target_strict_score": 91}}
    runtime = SimpleNamespace(state=runtime_state, state_path=None)
    plan = {"queue_order": ["i1"]}
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(override_skip_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(
        override_skip_mod, "require_issue_inventory", lambda _state: True
    )
    monkeypatch.setattr(override_skip_mod, "load_plan", lambda _plan_file=None: plan)
    monkeypatch.setattr(
        override_skip_mod, "resolve_ids_from_patterns", lambda *_a, **_k: ["i1"]
    )
    monkeypatch.setattr(
        override_skip_mod, "_apply_state_skip_resolution", lambda **_k: fresh_state
    )
    monkeypatch.setattr(override_skip_mod, "skip_items", lambda *_a, **_k: 1)
    monkeypatch.setattr(override_skip_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_skip_mod, "invalidate_postflight_scan", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        override_skip_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 91.0,
    )
    monkeypatch.setattr(
        override_skip_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            ("reconcile", _state, target_strict)
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": True, "lifecycle_phase": "execute"},
        )(),
    )
    monkeypatch.setattr(
        override_skip_mod, "save_plan_state_transactional", lambda **_k: None
    )
    monkeypatch.setattr(
        override_skip_mod,
        "emit_transition_message",
        lambda phase: seen.append(("emit", phase)),
    )
    monkeypatch.setattr(override_skip_mod, "print_user_message", lambda _msg: None)

    override_skip_mod.cmd_plan_skip(
        argparse.Namespace(
            patterns=["i1"],
            reason=None,
            review_after=None,
            permanent=False,
            false_positive=False,
            note=None,
            attest=None,
            confirm=False,
        )
    )

    assert ("target", {"target_strict_score": 91}) in seen
    assert ("reconcile", fresh_state, 91.0) in seen
    assert ("emit", "execute") in seen


def test_cmd_plan_unskip_reconciles_with_reopened_state(monkeypatch) -> None:
    runtime_state = {"issues": {}, "config": {"target_strict_score": 90}}
    fresh_state = {
        "issues": {"i1": {"status": "wontfix"}},
        "config": {"target_strict_score": 92},
    }
    runtime = SimpleNamespace(state=runtime_state, state_path=None)
    plan = {"queue_order": ["i1"], "skipped": {"i1": {"kind": "temporary"}}}
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(override_skip_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(
        override_skip_mod, "require_issue_inventory", lambda _state: True
    )
    monkeypatch.setattr(override_skip_mod, "load_plan", lambda _plan_file=None: plan)
    monkeypatch.setattr(
        override_skip_mod, "resolve_ids_from_patterns", lambda *_a, **_k: ["i1"]
    )
    monkeypatch.setattr(
        override_skip_mod, "unskip_items", lambda *_a, **_k: (1, ["i1"], [])
    )
    monkeypatch.setattr(override_skip_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_skip_mod.state_mod, "load_state", lambda _path: fresh_state
    )
    monkeypatch.setattr(
        override_skip_mod.state_mod,
        "resolve_issues",
        lambda _state, fid, _status: [fid],
    )
    monkeypatch.setattr(
        override_skip_mod, "invalidate_postflight_scan", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        override_skip_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 92.0,
    )
    monkeypatch.setattr(
        override_skip_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            ("reconcile", _state, target_strict)
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": True, "lifecycle_phase": "execute"},
        )(),
    )
    monkeypatch.setattr(
        override_skip_mod, "save_plan_state_transactional", lambda **_k: None
    )
    monkeypatch.setattr(
        override_skip_mod,
        "emit_transition_message",
        lambda phase: seen.append(("emit", phase)),
    )

    override_skip_mod.cmd_plan_unskip(argparse.Namespace(patterns=["i1"], force=False))

    assert ("target", {"target_strict_score": 92}) in seen
    assert ("reconcile", fresh_state, 92.0) in seen
    assert ("emit", "execute") in seen


def test_cmd_plan_backlog_reconciles_after_invalidation(monkeypatch) -> None:
    runtime_state = {"issues": {}, "config": {"target_strict_score": 90}}
    runtime = SimpleNamespace(state=runtime_state, state_path=None)
    state_data = {
        "work_items": {"i1": {"status": "deferred"}},
        "config": {"target_strict_score": 93},
    }
    plan = {"queue_order": ["i1"], "skipped": {"i1": {"kind": "temporary"}}}
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(override_skip_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(
        override_skip_mod, "require_issue_inventory", lambda _state: True
    )
    monkeypatch.setattr(override_skip_mod, "load_plan", lambda _plan_file=None: plan)
    monkeypatch.setattr(
        override_skip_mod, "resolve_ids_from_patterns", lambda *_a, **_k: ["i1"]
    )
    monkeypatch.setattr(override_skip_mod, "backlog_items", lambda *_a, **_k: ["i1"])
    monkeypatch.setattr(
        override_skip_mod.state_mod, "load_state", lambda _path: state_data
    )
    monkeypatch.setattr(
        override_skip_mod.state_mod,
        "resolve_issues",
        lambda _state, fid, _status: [fid],
    )
    monkeypatch.setattr(override_skip_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_skip_mod, "invalidate_postflight_scan", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        override_skip_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 93.0,
    )
    monkeypatch.setattr(
        override_skip_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            ("reconcile", _state, target_strict)
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": True, "lifecycle_phase": "execute"},
        )(),
    )
    monkeypatch.setattr(
        override_skip_mod, "save_plan_state_transactional", lambda **_k: None
    )
    monkeypatch.setattr(
        override_skip_mod,
        "emit_transition_message",
        lambda phase: seen.append(("emit", phase)),
    )

    override_skip_mod.cmd_plan_backlog(argparse.Namespace(patterns=["i1"]))

    assert ("target", {"target_strict_score": 93}) in seen
    assert ("reconcile", state_data, 93.0) in seen
    assert ("emit", "execute") in seen


def test_cmd_plan_reopen_reconciles_after_invalidation(monkeypatch) -> None:
    state_data = {"config": {"target_strict_score": 94}}
    plan = {"queue_order": [], "skipped": {}}
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(
        override_misc_mod, "state_path", lambda _args: Path("state.json")
    )
    monkeypatch.setattr(override_misc_mod, "load_state", lambda _path: state_data)
    monkeypatch.setattr(
        override_misc_mod, "_plan_file_for_state", lambda _path: Path("state.plan.json")
    )
    monkeypatch.setattr(override_misc_mod, "load_plan", lambda _path=None: plan)
    monkeypatch.setattr(
        override_misc_mod, "resolve_issues", lambda _state, _pattern, _status: ["i1"]
    )
    monkeypatch.setattr(
        override_misc_mod, "purge_uncommitted_ids", lambda *_a, **_k: None
    )
    monkeypatch.setattr(override_misc_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_misc_mod, "invalidate_postflight_scan", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        override_misc_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 94.0,
    )
    monkeypatch.setattr(
        override_misc_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            ("reconcile", _state, target_strict)
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": True, "lifecycle_phase": "execute"},
        )(),
    )
    monkeypatch.setattr(
        override_misc_mod, "save_plan_state_transactional", lambda **_k: None
    )
    monkeypatch.setattr(
        override_misc_mod,
        "emit_transition_message",
        lambda phase: seen.append(("emit", phase)),
    )

    override_misc_mod.cmd_plan_reopen(argparse.Namespace(patterns=["i1"]))

    assert ("target", {"target_strict_score": 94}) in seen
    assert ("reconcile", state_data, 94.0) in seen
    assert ("emit", "execute") in seen


def test_cmd_plan_reopen_keeps_protected_review_hold_out_of_queue(monkeypatch) -> None:
    state_data = {
        "config": {},
        "work_items": {"held": {"id": "held", "status": "fixed", "detector": "review"}},
    }
    plan = {
        "queue_order": [],
        "skipped": {},
        "epic_triage_meta": {"protected_review_issue_ids": ["held"]},
    }

    monkeypatch.setattr(
        override_misc_mod, "state_path", lambda _args: Path("state.json")
    )
    monkeypatch.setattr(override_misc_mod, "load_state", lambda _path: state_data)
    monkeypatch.setattr(
        override_misc_mod, "_plan_file_for_state", lambda _path: Path("plan.json")
    )
    monkeypatch.setattr(override_misc_mod, "load_plan", lambda _path=None: plan)
    monkeypatch.setattr(
        override_misc_mod,
        "resolve_issues",
        lambda state, _pattern, _status: state["work_items"]["held"].update(status="open") or ["held"],
    )
    monkeypatch.setattr(
        override_misc_mod, "purge_uncommitted_ids", lambda *_a, **_k: None
    )
    monkeypatch.setattr(override_misc_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        override_misc_mod, "save_plan_state_transactional", lambda **_k: None
    )

    override_misc_mod.cmd_plan_reopen(argparse.Namespace(patterns=["held"]))

    assert state_data["work_items"]["held"]["status"] == "open"
    assert plan["queue_order"] == []


def test_cmd_plan_skip_invalid_permanent_skip_exits_nonzero(monkeypatch) -> None:
    runtime = SimpleNamespace(
        state={"last_scan": "2026-03-01T00:00:00+00:00", "scan_count": 2, "issues": {}},
        state_path=None,
    )
    monkeypatch.setattr(override_skip_mod, "command_runtime", lambda _args: runtime)
    monkeypatch.setattr(
        override_skip_mod, "require_issue_inventory", lambda _state: True
    )

    with pytest.raises(CommandError) as excinfo:
        override_skip_mod.cmd_plan_skip(
            argparse.Namespace(
                patterns=["review::foo::deadbeef"],
                reason=None,
                review_after=None,
                permanent=True,
                false_positive=False,
                note="Reviewed as intentional architecture debt with a concrete justification.",
                attest="I reviewed this and will suppress it.",
                confirm=False,
            )
        )

    assert excinfo.value.exit_code == 2


def test_validate_skip_requirements_accepts_review_attestation() -> None:
    assert override_skip_mod._validate_skip_requirements(
        kind="permanent",
        attestation=(
            "I have reviewed this triage skip against the code and I am not gaming "
            "the score by suppressing a real defect."
        ),
        note="Reviewed and intentionally accepted for now.",
    )


def test_validate_skip_requirements_accepts_i_have_actually_attestation() -> None:
    assert override_skip_mod._validate_skip_requirements(
        kind="permanent",
        attestation=(
            "I have actually reviewed this triage skip against the code and I am "
            "not gaming the score by suppressing a real defect."
        ),
        note="Reviewed and intentionally accepted for now.",
    )
