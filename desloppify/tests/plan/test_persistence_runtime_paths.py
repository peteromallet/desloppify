"""Regression tests for runtime-aware plan persistence defaults."""

from __future__ import annotations

import json

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
import desloppify.engine._plan.persistence as persistence_mod
from desloppify.engine._plan.schema import empty_plan


def test_plan_persistence_defaults_follow_runtime_project_root(tmp_path):
    plan = empty_plan()
    plan["queue_order"] = ["review::a.py::issue-1"]

    ctx = RuntimeContext(project_root=tmp_path)
    with runtime_scope(ctx):
        persistence_mod.save_plan(plan)
        loaded = persistence_mod.load_plan()

    expected = tmp_path / ".desloppify" / "plan.json"
    assert expected.exists()
    assert loaded["queue_order"] == ["review::a.py::issue-1"]


def test_plan_persistence_honors_monkeypatched_plan_file(monkeypatch, tmp_path):
    custom_plan_file = tmp_path / "custom" / "plan.json"
    monkeypatch.setattr(persistence_mod, "PLAN_FILE", custom_plan_file)

    plan = empty_plan()
    plan["queue_order"] = ["review::b.py::issue-2"]
    persistence_mod.save_plan(plan)
    loaded = persistence_mod.load_plan()

    assert custom_plan_file.exists()
    assert loaded["queue_order"] == ["review::b.py::issue-2"]


def test_resolve_plan_load_status_marks_backup_recovery_degraded(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    backup_file = tmp_path / "plan.json.bak"
    plan_file.write_text("{not json", encoding="utf-8")
    backup_file.write_text(
        '{"version": 8, "created": "2026-01-01T00:00:00+00:00", "updated": "2026-01-01T00:00:00+00:00", "queue_order": ["review::a.py::issue-1"], "deferred": [], "skipped": {}, "active_cluster": null, "overrides": {}, "clusters": {}, "superseded": {}, "promoted_ids": [], "plan_start_scores": {}, "refresh_state": {}, "execution_log": [], "epic_triage_meta": {}, "commit_log": [], "uncommitted_issues": [], "commit_tracking_branch": null}\n',
        encoding="utf-8",
    )

    status = persistence_mod.resolve_plan_load_status(plan_file)

    assert status.degraded is True
    assert status.recovery == "backup"
    assert status.error_kind == "JSONDecodeError"
    assert status.plan is not None
    assert status.plan["queue_order"] == ["review::a.py::issue-1"]
    assert "recovered from backup" in capsys.readouterr().err


def test_resolve_plan_load_status_marks_fresh_start_when_recovery_fails(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text("{not json", encoding="utf-8")

    status = persistence_mod.resolve_plan_load_status(plan_file)

    assert status.degraded is True
    assert status.recovery == "fresh_start"
    assert status.error_kind == "JSONDecodeError"
    assert status.plan == empty_plan()
    assert "starting fresh" in capsys.readouterr().err.lower()


def test_resolve_plan_load_status_migrates_legacy_lifecycle_in_memory_only(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '{"version": 8, "created": "2026-01-01T00:00:00+00:00", "updated": "2026-01-01T00:00:00+00:00", "queue_order": ["workflow::communicate-score"], "deferred": [], "skipped": {}, "active_cluster": null, "overrides": {}, "clusters": {}, "superseded": {}, "promoted_ids": [], "plan_start_scores": {}, "refresh_state": {"lifecycle_phase": "workflow"}, "execution_log": [], "epic_triage_meta": {}, "commit_log": [], "uncommitted_issues": [], "commit_tracking_branch": null}\n',
        encoding="utf-8",
    )

    status = persistence_mod.resolve_plan_load_status(plan_file)

    assert status.plan is not None
    assert status.plan["refresh_state"]["lifecycle_phase"] == "plan"
    assert json.loads(plan_file.read_text(encoding="utf-8"))["refresh_state"][
        "lifecycle_phase"
    ] == "workflow"


def test_resolve_plan_load_status_preserves_legacy_uncommitted_findings(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '{"version": 7, "created": "2026-01-01T00:00:00+00:00", "updated": "2026-01-01T00:00:00+00:00", "queue_order": [], "deferred": [], "skipped": {}, "active_cluster": null, "overrides": {}, "clusters": {}, "superseded": {}, "promoted_ids": [], "plan_start_scores": {}, "refresh_state": {}, "execution_log": [], "epic_triage_meta": {}, "commit_log": [], "uncommitted_findings": ["review::a.py::issue-1"], "uncommitted_issues": [], "commit_tracking_branch": null}\n',
        encoding="utf-8",
    )

    status = persistence_mod.resolve_plan_load_status(plan_file)

    assert status.plan is not None
    assert status.plan["uncommitted_issues"] == ["review::a.py::issue-1"]
    assert "uncommitted_findings" not in status.plan
