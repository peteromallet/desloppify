"""Direct tests for postflight refresh and full plan reconciliation paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.scan.plan_reconcile as reconcile_mod
from desloppify.engine._plan.schema import empty_plan

from desloppify.tests.commands.scan.test_plan_reconcile import (
    _make_issue,
    _make_state,
    _runtime,
)

# ---------------------------------------------------------------------------
# Tests: _clear_plan_start_scores_if_queue_empty
# ---------------------------------------------------------------------------

class TestClearPlanStartScoresIfQueueEmpty:

    def test_returns_false_when_no_start_scores(self):
        plan = empty_plan()
        state = _make_state()
        assert reconcile_mod._clear_plan_start_scores_if_queue_empty(state, plan) is False

    def test_clears_and_copies_to_state(self, monkeypatch):
        plan = empty_plan()
        plan["plan_start_scores"] = {
            "strict": 80.0, "overall": 85.0,
            "objective": 82.0, "verified": 78.0,
        }
        state = _make_state()

        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=0, queue_total=0, lifecycle_phase="execution"),
        )
        result = reconcile_mod._clear_plan_start_scores_if_queue_empty(state, plan)
        assert result is True
        assert plan["plan_start_scores"] == {}
        assert state["_plan_start_scores_for_reveal"]["strict"] == 80.0

    def test_does_not_clear_when_queue_has_items(self, monkeypatch):
        plan = empty_plan()
        plan["plan_start_scores"] = {
            "strict": 80.0, "overall": 85.0,
            "objective": 82.0, "verified": 78.0,
        }
        state = _make_state()

        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=3, queue_total=5, lifecycle_phase="execution"),
        )
        result = reconcile_mod._clear_plan_start_scores_if_queue_empty(state, plan)
        assert result is False
        assert plan["plan_start_scores"]["strict"] == 80.0

    def test_clears_when_only_subjective_items_remain(self, monkeypatch):
        """Plan-start scores clear when only subjective items remain.

        score_display_mode sees objective_actionable=0 + queue_total=3 →
        PHASE_TRANSITION (not FROZEN), so the cycle clears.
        """
        plan = empty_plan()
        plan["plan_start_scores"] = {
            "strict": 80.0, "overall": 85.0,
            "objective": 82.0, "verified": 78.0,
        }
        state = _make_state()

        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=0, queue_total=3, lifecycle_phase="execution"),
        )
        result = reconcile_mod._clear_plan_start_scores_if_queue_empty(state, plan)
        assert result is True
        assert plan["plan_start_scores"] == {}
        assert state["_plan_start_scores_for_reveal"]["strict"] == 80.0

    def test_swallows_queue_breakdown_exception(self, monkeypatch):
        plan = empty_plan()
        plan["plan_start_scores"] = {"strict": 80.0}
        state = _make_state()

        def _raise(s, p):
            raise OSError("disk read failed")

        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            _raise,
        )
        result = reconcile_mod._clear_plan_start_scores_if_queue_empty(state, plan)
        assert result is False
        # Scores not cleared on error
        assert plan["plan_start_scores"]["strict"] == 80.0


# ---------------------------------------------------------------------------
# Tests: _sync_postflight_scan_completion_and_log
# ---------------------------------------------------------------------------

class TestSyncPostflightScanCompletionAndLog:

    def test_marks_scan_complete_when_objective_queue_is_drained(self, monkeypatch):
        plan = empty_plan()
        state = _make_state(scan_count=7)

        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=0, queue_total=2),
        )
        changed = reconcile_mod._sync_postflight_scan_completion_and_log(plan, state)

        assert changed is True
        assert plan["refresh_state"]["postflight_scan_completed_at_scan_count"] == 7
        log_actions = [entry["action"] for entry in plan["execution_log"]]
        assert "complete_postflight_scan" in log_actions

    def test_does_not_mark_complete_when_deferred_backlog_exists(self, monkeypatch):
        plan = empty_plan()
        plan["skipped"] = {"issue-1": {"kind": "temporary"}}
        state = _make_state(scan_count=7)

        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=0, queue_total=1),
        )
        changed = reconcile_mod._sync_postflight_scan_completion_and_log(plan, state)

        assert changed is False
        assert plan["refresh_state"] == {}


# ---------------------------------------------------------------------------
# Tests: reconcile_plan_post_scan (full orchestration)
# ---------------------------------------------------------------------------

class TestReconcilePlanPostScan:

    def test_saves_when_superseded_issues_detected(self, monkeypatch):
        plan = empty_plan()
        plan["queue_order"] = ["issue-1", "issue-2"]
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        state = _make_state(issues={
            "issue-1": _make_issue(status="resolved"),
            "issue-2": _make_issue(status="open"),
        })

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        assert "issue-1" in saved[0]["superseded"]
        assert "issue-1" not in saved[0]["queue_order"]
        assert "issue-2" in saved[0]["queue_order"]

    def test_does_not_save_when_nothing_changed(self, monkeypatch):
        """Empty-boundary scans persist post-flight completion metadata once."""
        plan = empty_plan()
        plan["queue_order"] = ["workflow::communicate-score"]
        state = _make_state()

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))
        assert len(saved) == 1
        assert saved[0]["refresh_state"]["postflight_scan_completed_at_scan_count"] == 1

    def test_swallows_load_plan_exception(self, monkeypatch):
        monkeypatch.setattr(
            reconcile_mod, "load_plan",
            lambda _path=None: (_ for _ in ()).throw(OSError("boom")),
        )
        # Should not raise
        reconcile_mod.reconcile_plan_post_scan(_runtime())

    def test_swallows_save_plan_exception(self, monkeypatch):
        plan = empty_plan()
        plan["queue_order"] = ["issue-1"]
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        state = _make_state(issues={
            "issue-1": _make_issue(status="resolved"),
        })

        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan",
                            lambda p, _path=None: (_ for _ in ()).throw(OSError("disk full")))

        # Should not raise
        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

    def test_marks_postflight_scan_on_empty_plan(self, monkeypatch):
        plan = empty_plan()
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        # Scores get seeded because the state has scores and plan_start_scores was empty.
        assert isinstance(saved[0]["plan_start_scores"].get("strict"), float)
        assert saved[0]["refresh_state"]["postflight_scan_completed_at_scan_count"] == 1

    def test_force_rescan_marks_postflight_scan_complete(self, monkeypatch):
        plan = empty_plan()
        plan["queue_order"] = ["workflow::run-scan"]
        plan["plan_start_scores"] = {"strict": 86.4}
        state = _make_state(scan_count=5)

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state, force_rescan=True))

        assert len(saved) == 1
        assert saved[0]["plan_start_scores"] == {"strict": 86.4}
        assert saved[0]["refresh_state"]["postflight_scan_completed_at_scan_count"] == 5

    def test_superseded_issue_removed_from_clusters(self, monkeypatch):
        plan = empty_plan()
        plan["queue_order"] = ["issue-1", "issue-2"]
        plan["clusters"] = {
            "my-cluster": {
                "name": "my-cluster",
                "issue_ids": ["issue-1", "issue-2"],
            }
        }
        state = _make_state(issues={
            "issue-1": _make_issue(status="resolved"),
            "issue-2": _make_issue(status="open"),
        })

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        cluster = saved[0]["clusters"]["my-cluster"]
        assert "issue-1" not in cluster["issue_ids"]
        assert "issue-2" in cluster["issue_ids"]

    def test_superseded_issue_removed_from_skipped(self, monkeypatch):
        plan = empty_plan()
        plan["queue_order"] = []
        plan["skipped"] = {
            "issue-1": {
                "issue_id": "issue-1", "kind": "temporary",
                "skipped_at_scan": 1, "review_after": 5,
            },
        }
        state = _make_state(issues={
            "issue-1": _make_issue(status="resolved"),
        })

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        assert "issue-1" not in saved[0]["skipped"]
        assert "issue-1" in saved[0]["superseded"]

    def test_multiple_dirty_steps_save_once(self, monkeypatch):
        """Even when multiple reconciliation steps produce changes, save happens once."""
        plan = empty_plan()
        plan["queue_order"] = ["issue-1"]
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        state = _make_state(
            issues={"issue-1": _make_issue(status="resolved")},
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        assert "issue-1" in saved[0]["superseded"]
        assert saved[0]["refresh_state"]["postflight_scan_completed_at_scan_count"] == 1

    def test_plan_path_derived_from_state_path(self, monkeypatch):
        plan = empty_plan()
        state = _make_state()

        loaded_paths: list = []
        saved_paths: list = []

        def mock_load(path=None):
            loaded_paths.append(path)
            return plan

        def mock_save(p, path=None):
            saved_paths.append(path)

        monkeypatch.setattr(reconcile_mod, "load_plan", mock_load)
        monkeypatch.setattr(reconcile_mod, "save_plan", mock_save)

        rt = SimpleNamespace(
            state=state,
            state_path=Path("/project/.desloppify/state-python.json"),
            config={},
        )
        reconcile_mod.reconcile_plan_post_scan(rt)

        assert loaded_paths[0] == Path("/project/.desloppify/plan.json")

    def test_plan_path_none_when_state_path_none(self, monkeypatch):
        plan = empty_plan()
        state = _make_state()

        loaded_paths: list = []

        def mock_load(path=None):
            loaded_paths.append(path)
            return plan

        monkeypatch.setattr(reconcile_mod, "load_plan", mock_load)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: None)

        rt = SimpleNamespace(state=state, state_path=None, config={})
        reconcile_mod.reconcile_plan_post_scan(rt)
        assert loaded_paths[0] is None

    def test_execution_log_records_reconcile(self, monkeypatch):
        plan = empty_plan()
        plan["queue_order"] = ["issue-1"]
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        state = _make_state(issues={
            "issue-1": _make_issue(status="resolved"),
        })

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        actions = [e["action"] for e in saved[0].get("execution_log", [])]
        assert "reconcile" in actions

    def test_multiple_issues_superseded_at_once(self, monkeypatch):
        """When several queued issues disappear, all are superseded."""
        plan = empty_plan()
        plan["queue_order"] = ["a", "b", "c"]
        plan["overrides"] = {
            "a": {"issue_id": "a"},
            "b": {"issue_id": "b"},
            "c": {"issue_id": "c"},
        }
        state = _make_state(issues={
            "a": _make_issue(status="resolved"),
            "b": _make_issue(status="resolved"),
            "c": _make_issue(status="open"),
        })

        saved: list[dict] = []
        monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
        monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))

        reconcile_mod.reconcile_plan_post_scan(_runtime(state=state))

        assert len(saved) == 1
        assert "a" in saved[0]["superseded"]
        assert "b" in saved[0]["superseded"]
        assert "a" not in saved[0]["queue_order"]
        assert "b" not in saved[0]["queue_order"]
        assert "c" in saved[0]["queue_order"]
