"""Direct tests for scan plan reconciliation orchestration.

Tests exercise the real reconciliation logic with realistic plan and state
data structures, mocking only at I/O boundaries (load_plan, save_plan).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


import desloppify.app.commands.scan.plan_reconcile as reconcile_mod
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import QueueSyncResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runtime(*, state=None, config=None, force_rescan=False) -> SimpleNamespace:
    return SimpleNamespace(
        state=state or {},
        state_path=Path("/tmp/fake-state.json"),
        config=config or {},
        force_rescan=force_rescan,
    )


def _make_state(
    *,
    issues: dict | None = None,
    overall_score: float | None = None,
    objective_score: float | None = None,
    strict_score: float | None = None,
    verified_strict_score: float | None = None,
    scan_count: int = 1,
) -> dict:
    """Build a minimal but realistic state dict."""
    state: dict = {
        "issues": issues or {},
        "scan_count": scan_count,
        "dimension_scores": {},
        "subjective_assessments": {},
    }
    if overall_score is not None:
        state["overall_score"] = overall_score
    if objective_score is not None:
        state["objective_score"] = objective_score
    if strict_score is not None:
        state["strict_score"] = strict_score
    if verified_strict_score is not None:
        state["verified_strict_score"] = verified_strict_score
    return state


def _make_issue(
    detector: str = "complexity",
    file: str = "src/app.py",
    status: str = "open",
    **extra,
) -> dict:
    return {"detector": detector, "file": file, "status": status, **extra}


# ---------------------------------------------------------------------------
# Tests: _plan_has_user_content
# ---------------------------------------------------------------------------

class TestPlanHasUserContent:

    def test_empty_plan_has_no_user_content(self):
        plan = empty_plan()
        assert reconcile_mod._plan_has_user_content(plan) is False

    def test_plan_with_queue_order(self):
        plan = empty_plan()
        plan["queue_order"] = ["issue-1"]
        assert reconcile_mod._plan_has_user_content(plan) is True

    def test_plan_with_overrides(self):
        plan = empty_plan()
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        assert reconcile_mod._plan_has_user_content(plan) is True

    def test_plan_with_clusters(self):
        plan = empty_plan()
        plan["clusters"] = {"c1": {"name": "c1", "issue_ids": ["issue-1"]}}
        assert reconcile_mod._plan_has_user_content(plan) is True

    def test_plan_with_skipped(self):
        plan = empty_plan()
        plan["skipped"] = {"issue-1": {
            "issue_id": "issue-1", "kind": "temporary", "skipped_at_scan": 1,
        }}
        assert reconcile_mod._plan_has_user_content(plan) is True

    def test_empty_collections_are_falsy(self):
        """Empty queue_order, overrides, clusters, skipped all return False."""
        plan = empty_plan()
        plan["queue_order"] = []
        plan["overrides"] = {}
        plan["clusters"] = {}
        plan["skipped"] = {}
        assert reconcile_mod._plan_has_user_content(plan) is False


# ---------------------------------------------------------------------------
# Tests: _seed_plan_start_scores
# ---------------------------------------------------------------------------

class TestSeedPlanStartScores:

    def test_seeds_when_plan_start_scores_empty(self):
        plan = empty_plan()
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )
        assert reconcile_mod._seed_plan_start_scores(plan, state) is True
        assert plan["plan_start_scores"] == {
            "strict": 85.0, "overall": 90.0,
            "objective": 88.0, "verified": 80.0,
        }

    def test_seeding_clears_workflow_cycle_sentinels(self):
        plan = empty_plan()
        plan["previous_plan_start_scores"] = {"strict": 70.0}
        plan["create_plan_resolved_this_cycle"] = True
        plan["communicate_score_resolved_this_cycle"] = True
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )

        assert reconcile_mod._seed_plan_start_scores(plan, state) is True
        assert "previous_plan_start_scores" not in plan
        assert "create_plan_resolved_this_cycle" not in plan
        assert "communicate_score_resolved_this_cycle" not in plan

    def test_does_not_reseed_when_scores_exist(self):
        plan = empty_plan()
        plan["plan_start_scores"] = {
            "strict": 70.0, "overall": 75.0,
            "objective": 72.0, "verified": 68.0,
        }
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )
        assert reconcile_mod._seed_plan_start_scores(plan, state) is False
        assert plan["plan_start_scores"]["strict"] == 70.0

    def test_reseeds_when_reset_sentinel(self):
        plan = empty_plan()
        plan["plan_start_scores"] = {"reset": True}
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )
        assert reconcile_mod._seed_plan_start_scores(plan, state) is True
        assert plan["plan_start_scores"]["strict"] == 85.0
        assert "reset" not in plan["plan_start_scores"]

    def test_returns_false_when_strict_score_is_none(self):
        plan = empty_plan()
        state = _make_state()
        assert reconcile_mod._seed_plan_start_scores(plan, state) is False
        # plan_start_scores stays empty
        assert plan["plan_start_scores"] == {}

    def test_returns_false_when_existing_is_non_dict(self):
        """Edge case: plan_start_scores set to a non-dict value."""
        plan = empty_plan()
        plan["plan_start_scores"] = "garbage"
        state = _make_state(strict_score=85.0, overall_score=90.0,
                            objective_score=88.0, verified_strict_score=80.0)
        assert reconcile_mod._seed_plan_start_scores(plan, state) is False


class TestResetCycleForForceRescan:

    def test_force_rescan_clears_workflow_cycle_sentinels(self):
        plan = empty_plan()
        plan["queue_order"] = ["workflow::communicate-score", "workflow::create-plan"]
        plan["plan_start_scores"] = {"strict": 80.0}
        plan["previous_plan_start_scores"] = {"strict": 70.0}
        plan["create_plan_resolved_this_cycle"] = True
        plan["communicate_score_resolved_this_cycle"] = True

        assert reconcile_mod._reset_cycle_for_force_rescan(plan) is True
        assert "previous_plan_start_scores" not in plan
        assert "create_plan_resolved_this_cycle" not in plan
        assert "communicate_score_resolved_this_cycle" not in plan


# ---------------------------------------------------------------------------
# Tests: _apply_plan_reconciliation
# ---------------------------------------------------------------------------

class TestApplyPlanReconciliation:

    def test_supersedes_resolved_issue(self):
        """An issue in queue_order that becomes resolved should be superseded."""
        plan = empty_plan()
        plan["queue_order"] = ["issue-1", "issue-2"]
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        state = _make_state(issues={
            "issue-1": _make_issue(status="resolved"),
            "issue-2": _make_issue(status="open"),
        })
        from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
        result = reconcile_plan_after_scan(plan, state)
        assert "issue-1" in result.superseded
        assert "issue-1" in plan["superseded"]
        assert "issue-1" not in plan["queue_order"]
        assert "issue-2" in plan["queue_order"]

    def test_supersedes_disappeared_issue(self):
        """An issue in queue_order that no longer exists should be superseded."""
        plan = empty_plan()
        plan["queue_order"] = ["gone-id"]
        plan["overrides"] = {"gone-id": {"issue_id": "gone-id"}}
        state = _make_state(issues={})
        from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
        result = reconcile_plan_after_scan(plan, state)
        assert "gone-id" in result.superseded

    def test_no_changes_when_all_alive(self):
        plan = empty_plan()
        plan["queue_order"] = ["issue-1"]
        plan["overrides"] = {"issue-1": {"issue_id": "issue-1"}}
        state = _make_state(issues={
            "issue-1": _make_issue(status="open"),
        })
        changed = reconcile_mod._apply_plan_reconciliation(plan, state)
        assert changed is False

    def test_skips_when_no_user_content(self):
        plan = empty_plan()
        state = _make_state()
        changed = reconcile_mod._apply_plan_reconciliation(plan, state)
        assert changed is False


# ---------------------------------------------------------------------------
# Tests: _display_reconcile_results
# ---------------------------------------------------------------------------

class TestDisplayReconcileResults:

    def test_reports_subjective_injection(self, capsys):
        plan = empty_plan()
        reconcile_mod._display_reconcile_results(
            reconcile_mod.ReconcileResult(
                subjective=QueueSyncResult(injected=["subjective::naming"])
            ),
            plan,
            mid_cycle=False,
        )
        captured = capsys.readouterr()
        assert "1 subjective" in captured.out

    def test_reports_resurfaced(self, capsys):
        plan = empty_plan()
        reconcile_mod._display_reconcile_results(
            reconcile_mod.ReconcileResult(
                subjective=QueueSyncResult(resurfaced=["subjective::naming"])
            ),
            plan,
            mid_cycle=False,
        )
        captured = capsys.readouterr()
        assert "resurfaced" in captured.out.lower()

    def test_reports_pruned(self, capsys):
        plan = empty_plan()
        reconcile_mod._display_reconcile_results(
            reconcile_mod.ReconcileResult(
                subjective=QueueSyncResult(pruned=["subjective::naming"])
            ),
            plan,
            mid_cycle=False,
        )
        captured = capsys.readouterr()
        assert "refreshed" in captured.out.lower() or "removed" in captured.out.lower()

    def test_reports_create_plan(self, capsys):
        plan = empty_plan()
        reconcile_mod._display_reconcile_results(
            reconcile_mod.ReconcileResult(
                create_plan=QueueSyncResult(injected=["workflow::create-plan"])
            ),
            plan,
            mid_cycle=False,
        )
        captured = capsys.readouterr()
        assert "create-plan" in captured.out

    def test_reports_mid_cycle_skip(self, capsys):
        plan = empty_plan()
        reconcile_mod._display_reconcile_results(
            reconcile_mod.ReconcileResult(),
            plan,
            mid_cycle=True,
        )
        captured = capsys.readouterr()
        assert "mid-cycle scan" in captured.out


# ---------------------------------------------------------------------------
# Tests: _is_mid_cycle_scan
# ---------------------------------------------------------------------------

class TestIsMidCycleScan:

    def test_false_when_cycle_not_active(self):
        plan = empty_plan()
        state = _make_state()

        assert reconcile_mod._is_mid_cycle_scan(plan, state) is False

    def test_false_when_only_synthetic_or_skipped_items_remain(self):
        plan = empty_plan()
        plan["plan_start_scores"] = {"strict": 80.0}
        plan["queue_order"] = [
            "workflow::communicate-score",
            "issue-1",
        ]
        plan["skipped"] = {
            "issue-1": {
                "issue_id": "issue-1",
                "kind": "temporary",
                "skipped_at_scan": 1,
            }
        }
        state = _make_state()

        assert reconcile_mod._is_mid_cycle_scan(plan, state) is False

    def test_true_when_substantive_queue_item_remains(self):
        plan = empty_plan()
        plan["plan_start_scores"] = {"strict": 80.0}
        plan["queue_order"] = ["workflow::communicate-score", "issue-1"]
        state = _make_state()

        assert reconcile_mod._is_mid_cycle_scan(plan, state) is True


# ---------------------------------------------------------------------------
# Tests: _sync_plan_start_scores_and_log
# ---------------------------------------------------------------------------

class TestSyncPlanStartScoresAndLog:

    def test_seeds_and_appends_log(self, monkeypatch):
        plan = empty_plan()
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=2, queue_total=2),
        )
        changed = reconcile_mod._sync_plan_start_scores_and_log(plan, state)
        assert changed is True
        assert plan["plan_start_scores"]["strict"] == 85.0
        log_actions = [e["action"] for e in plan["execution_log"]]
        assert "seed_start_scores" in log_actions

    def test_no_change_when_already_seeded(self, monkeypatch):
        plan = empty_plan()
        plan["plan_start_scores"] = {
            "strict": 70.0, "overall": 75.0,
            "objective": 72.0, "verified": 68.0,
        }
        state = _make_state(
            strict_score=85.0, overall_score=90.0,
            objective_score=88.0, verified_strict_score=80.0,
        )
        # Stub out _clear to isolate seeding logic
        monkeypatch.setattr(
            reconcile_mod, "_clear_plan_start_scores_if_queue_empty",
            lambda state, plan: False,
        )
        changed = reconcile_mod._sync_plan_start_scores_and_log(plan, state)
        assert changed is False
        assert plan["execution_log"] == []

    def test_clears_when_queue_empty(self, monkeypatch):
        plan = empty_plan()
        plan["plan_start_scores"] = {
            "strict": 70.0, "overall": 75.0,
            "objective": 72.0, "verified": 68.0,
        }
        state = _make_state()  # no scores so seeding fails

        # Mock the queue breakdown to report empty
        monkeypatch.setattr(
            "desloppify.app.commands.helpers.queue_progress.plan_aware_queue_breakdown",
            lambda s, p: SimpleNamespace(objective_actionable=0, queue_total=0, lifecycle_phase="execution"),
        )
        changed = reconcile_mod._sync_plan_start_scores_and_log(plan, state)
        assert changed is True
        assert plan["plan_start_scores"] == {}
        assert state["_plan_start_scores_for_reveal"]["strict"] == 70.0
        log_actions = [e["action"] for e in plan["execution_log"]]
        assert "clear_start_scores" in log_actions
