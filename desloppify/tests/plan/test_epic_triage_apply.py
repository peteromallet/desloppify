"""Tests for epic_triage_apply: plan mutation during triage."""

from __future__ import annotations

from desloppify.engine._plan.policy.stale import review_issue_snapshot_hash
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.triage.apply import (
    TriageMutationResult,
    apply_triage_to_plan,
)
from desloppify.engine._plan.triage.prompt import DismissedIssue, TriageResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_with_review_issues(*ids: str) -> dict:
    """Build minimal state with open review issues."""
    issues = {}
    for fid in ids:
        issues[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review issue {fid}",
            "confidence": "medium",
            "tier": 2,
            "detail": {"dimension": "abstraction_fitness"},
        }
    return {"issues": issues, "scan_count": 5, "dimension_scores": {}}


def _state_empty() -> dict:
    return {"issues": {}, "scan_count": 1, "dimension_scores": {}}


def _triage_with_epics(*epics: dict) -> TriageResult:
    """Build a TriageResult with the given epics and no dismissals."""
    return TriageResult(
        strategy_summary="Test strategy",
        epics=list(epics),
    )


def _epic(
    name: str,
    issue_ids: list[str],
    dependency_order: int = 1,
    *,
    direction: str = "delete",
    dismissed: list[str] | None = None,
    agent_safe: bool = False,
    status: str = "pending",
    action_steps: list[str] | None = None,
) -> dict:
    """Build a minimal epic dict for TriageResult."""
    return {
        "name": name,
        "thesis": f"Thesis for {name}",
        "direction": direction,
        "root_cause": f"Root cause for {name}",
        "issue_ids": issue_ids,
        "dismissed": dismissed or [],
        "agent_safe": agent_safe,
        "dependency_order": dependency_order,
        "action_steps": action_steps or [],
        "status": status,
    }


# ---------------------------------------------------------------------------
# TriageMutationResult dataclass
# ---------------------------------------------------------------------------


class TestTriageMutationResult:
    def test_defaults(self):
        r = TriageMutationResult()
        assert r.epics_created == 0
        assert r.epics_updated == 0
        assert r.epics_completed == 0
        assert r.issues_dismissed == 0
        assert r.issues_reassigned == 0
        assert r.strategy_summary == ""
        assert r.triage_version == 0
        assert r.dry_run is False


# ---------------------------------------------------------------------------
# Cluster creation
# ---------------------------------------------------------------------------


class TestClusterCreation:
    def test_creates_single_epic(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")
        triage = _triage_with_epics(_epic("cleanup", ["r1", "r2"]))

        result = apply_triage_to_plan(plan, state, triage)

        assert result.epics_created == 1
        assert result.epics_updated == 0
        assert "epic/cleanup" in plan["clusters"]
        cluster = plan["clusters"]["epic/cleanup"]
        assert cluster["name"] == "epic/cleanup"
        assert cluster["thesis"] == "Thesis for cleanup"
        assert cluster["direction"] == "delete"
        assert cluster["root_cause"] == "Root cause for cleanup"
        assert cluster["issue_ids"] == ["r1", "r2"]
        assert cluster["auto"] is True
        assert cluster["cluster_key"] == "epic::epic/cleanup"
        assert cluster["action"] == "desloppify plan focus epic/cleanup"
        assert cluster["user_modified"] is False
        assert cluster["status"] == "pending"

    def test_creates_multiple_epics(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2", "r3")
        triage = _triage_with_epics(
            _epic("first", ["r1"], dependency_order=1),
            _epic("second", ["r2", "r3"], dependency_order=2),
        )

        result = apply_triage_to_plan(plan, state, triage)

        assert result.epics_created == 2
        assert "epic/first" in plan["clusters"]
        assert "epic/second" in plan["clusters"]

    def test_epic_prefix_not_doubled(self):
        """If the name already starts with epic/, don't double-prefix."""
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(_epic("epic/already-prefixed", ["r1"]))

        apply_triage_to_plan(plan, state, triage)

        assert "epic/already-prefixed" in plan["clusters"]
        # Should NOT have "epic/epic/already-prefixed"
        assert "epic/epic/already-prefixed" not in plan["clusters"]

    def test_cluster_has_timestamps(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(_epic("ts-test", ["r1"]))

        apply_triage_to_plan(plan, state, triage)

        cluster = plan["clusters"]["epic/ts-test"]
        assert "created_at" in cluster
        assert "updated_at" in cluster
        assert cluster["created_at"] == cluster["updated_at"]

    def test_cluster_agent_safe_flag(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(
            _epic("safe", ["r1"], agent_safe=True),
        )

        apply_triage_to_plan(plan, state, triage)

        assert plan["clusters"]["epic/safe"]["agent_safe"] is True

    def test_cluster_action_steps(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(
            _epic("steps", ["r1"], action_steps=["step 1", "step 2"]),
        )

        apply_triage_to_plan(plan, state, triage)

        assert plan["clusters"]["epic/steps"]["action_steps"] == ["step 1", "step 2"]


# ---------------------------------------------------------------------------
# Cluster update (existing epic)
# ---------------------------------------------------------------------------


class TestClusterUpdate:
    def _existing_epic_plan(self) -> dict:
        plan = empty_plan()
        plan["clusters"]["epic/existing"] = {
            "name": "epic/existing",
            "thesis": "Old thesis",
            "direction": "merge",
            "root_cause": "old cause",
            "issue_ids": ["r1"],
            "dismissed": [],
            "agent_safe": False,
            "dependency_order": 1,
            "action_steps": ["old step"],
            "status": "pending",
            "auto": True,
            "cluster_key": "epic::epic/existing",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "triage_version": 1,
        }
        return plan

    def test_updates_existing_epic(self):
        plan = self._existing_epic_plan()
        state = _state_with_review_issues("r1", "r2")
        triage = _triage_with_epics(
            _epic("existing", ["r1", "r2"], direction="simplify"),
        )

        result = apply_triage_to_plan(plan, state, triage)

        assert result.epics_updated == 1
        assert result.epics_created == 0
        cluster = plan["clusters"]["epic/existing"]
        assert cluster["thesis"] == "Thesis for existing"
        assert cluster["direction"] == "simplify"
        assert cluster["issue_ids"] == ["r1", "r2"]
        assert cluster["description"] == "Thesis for existing"

    def test_update_bumps_timestamp(self):
        plan = self._existing_epic_plan()
        old_updated = plan["clusters"]["epic/existing"]["updated_at"]
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(_epic("existing", ["r1"]))

        apply_triage_to_plan(plan, state, triage)

        assert plan["clusters"]["epic/existing"]["updated_at"] != old_updated

    def test_update_preserves_in_progress_status(self):
        plan = self._existing_epic_plan()
        plan["clusters"]["epic/existing"]["status"] = "in_progress"
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(
            _epic("existing", ["r1"], status="pending"),
        )

        apply_triage_to_plan(plan, state, triage)

        # in_progress must not be overwritten by triage
        assert plan["clusters"]["epic/existing"]["status"] == "in_progress"

    def test_update_sets_pending_when_not_in_progress(self):
        plan = self._existing_epic_plan()
        plan["clusters"]["epic/existing"]["status"] = "pending"
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(
            _epic("existing", ["r1"], status="pending"),
        )

        apply_triage_to_plan(plan, state, triage)

        assert plan["clusters"]["epic/existing"]["status"] == "pending"

    def test_update_sets_triage_version(self):
        plan = self._existing_epic_plan()
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(_epic("existing", ["r1"]))

        result = apply_triage_to_plan(plan, state, triage)

        assert plan["clusters"]["epic/existing"]["triage_version"] == result.triage_version


# ---------------------------------------------------------------------------
# Dismissed issues
# ---------------------------------------------------------------------------


class TestDismissedIssues:
    def test_dismissed_removed_from_queue(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage = TriageResult(
            strategy_summary="x",
            epics=[],
            dismissed_issues=[
                DismissedIssue(issue_id="r2", reason="false positive"),
            ],
        )

        result = apply_triage_to_plan(plan, state, triage)

        assert result.issues_dismissed == 1
        assert "r2" not in plan["queue_order"]
        assert plan["queue_order"] == ["r1", "r3"]

    def test_dismissed_added_to_skipped(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1"]
        state = _state_with_review_issues("r1")
        triage = TriageResult(
            strategy_summary="x",
            epics=[],
            dismissed_issues=[
                DismissedIssue(issue_id="r1", reason="not actionable"),
            ],
        )

        apply_triage_to_plan(plan, state, triage)

        assert "r1" in plan["skipped"]
        entry = plan["skipped"]["r1"]
        assert entry["kind"] == "triaged_out"
        assert entry["reason"] == "not actionable"
        assert "Dismissed by epic triage v1" in entry["note"]
        assert entry["skipped_at_scan"] == 5  # from state scan_count

    def test_multiple_dismissals(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage = TriageResult(
            strategy_summary="x",
            epics=[],
            dismissed_issues=[
                DismissedIssue(issue_id="r1", reason="reason 1"),
                DismissedIssue(issue_id="r3", reason="reason 3"),
            ],
        )

        result = apply_triage_to_plan(plan, state, triage)

        assert result.issues_dismissed == 2
        assert plan["queue_order"] == ["r2"]
        assert "r1" in plan["skipped"]
        assert "r3" in plan["skipped"]

    def test_dismissed_not_in_queue_still_skipped(self):
        """Dismissing an ID not in queue_order should still add to skipped."""
        plan = empty_plan()
        plan["queue_order"] = ["r1"]
        state = _state_with_review_issues("r1", "r2")
        triage = TriageResult(
            strategy_summary="x",
            epics=[],
            dismissed_issues=[
                DismissedIssue(issue_id="r2", reason="not in queue"),
            ],
        )

        result = apply_triage_to_plan(plan, state, triage)

        assert result.issues_dismissed == 1
        assert "r2" in plan["skipped"]

    def test_per_epic_dismissals(self):
        """Issues listed in an epic's 'dismissed' list should be removed from queue."""
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage = _triage_with_epics(
            _epic("test", ["r1"], dismissed=["r2"]),
        )

        result = apply_triage_to_plan(plan, state, triage)

        assert result.issues_dismissed == 1
        assert "r2" not in plan["queue_order"]
        assert "r2" in plan["skipped"]

    def test_per_epic_dismissals_not_double_counted(self):
        """If an issue is in both dismissed_issues and epic dismissed, count once."""
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2"]
        state = _state_with_review_issues("r1", "r2")
        triage = TriageResult(
            strategy_summary="x",
            epics=[_epic("test", ["r1"], dismissed=["r2"])],
            dismissed_issues=[
                DismissedIssue(issue_id="r2", reason="global dismissal"),
            ],
        )

        result = apply_triage_to_plan(plan, state, triage)

        # r2 dismissed once by dismissed_issues, then skipped in per-epic loop
        # because it's already in dismissed_ids
        assert result.issues_dismissed == 1
        assert "r2" in plan["skipped"]
        assert plan["skipped"]["r2"]["reason"] == "global dismissal"


# ---------------------------------------------------------------------------
# Queue reordering
# ---------------------------------------------------------------------------


class TestQueueReordering:
    def test_epic_issues_ordered_by_dependency(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3", "other"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage = _triage_with_epics(
            _epic("second", ["r2"], dependency_order=2),
            _epic("first", ["r1", "r3"], dependency_order=1),
        )

        apply_triage_to_plan(plan, state, triage)

        # dep 1 issues first (r1, r3), then dep 2 (r2), then non-epic (other)
        assert plan["queue_order"] == ["r1", "r3", "r2", "other"]

    def test_non_epic_items_preserved_at_end(self):
        plan = empty_plan()
        plan["queue_order"] = ["x", "y", "r1"]
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(
            _epic("only", ["r1"], dependency_order=1),
        )

        apply_triage_to_plan(plan, state, triage)

        assert plan["queue_order"] == ["r1", "x", "y"]

    def test_dismissed_issues_excluded_from_reorder(self):
        """Dismissed issues should not appear in the reordered queue."""
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage = TriageResult(
            strategy_summary="x",
            epics=[_epic("test", ["r1", "r2"], dependency_order=1)],
            dismissed_issues=[
                DismissedIssue(issue_id="r2", reason="dismissed"),
            ],
        )

        apply_triage_to_plan(plan, state, triage)

        assert "r2" not in plan["queue_order"]
        # r1 is epic issue (dep 1), r3 is non-epic
        assert plan["queue_order"] == ["r1", "r3"]

    def test_no_epics_preserves_queue_order(self):
        """When there are no epics, queue order should remain unchanged."""
        plan = empty_plan()
        plan["queue_order"] = ["a", "b", "c"]
        state = _state_with_review_issues("a", "b", "c")
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage)

        assert plan["queue_order"] == ["a", "b", "c"]

    def test_dedup_across_epics(self):
        """An issue in multiple epics only appears once in the queue."""
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2"]
        state = _state_with_review_issues("r1", "r2")
        triage = _triage_with_epics(
            _epic("alpha", ["r1", "r2"], dependency_order=1),
            _epic("beta", ["r2"], dependency_order=2),
        )

        apply_triage_to_plan(plan, state, triage)

        # r2 should only appear once (from alpha, dep 1)
        assert plan["queue_order"].count("r1") == 1
        assert plan["queue_order"].count("r2") == 1
        assert plan["queue_order"] == ["r1", "r2"]

    def test_single_epic_reorders_to_front(self):
        plan = empty_plan()
        plan["queue_order"] = ["other1", "other2", "r1"]
        state = _state_with_review_issues("r1")
        triage = _triage_with_epics(_epic("front", ["r1"], dependency_order=1))

        apply_triage_to_plan(plan, state, triage)

        assert plan["queue_order"][0] == "r1"
        assert plan["queue_order"] == ["r1", "other1", "other2"]


# ---------------------------------------------------------------------------
# Triage metadata
# ---------------------------------------------------------------------------


class TestTriageMeta:
    def test_version_increments(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = TriageResult(strategy_summary="v1", epics=[])

        r1 = apply_triage_to_plan(plan, state, triage)
        assert r1.triage_version == 1
        assert plan["epic_triage_meta"]["version"] == 1

        r2 = apply_triage_to_plan(plan, state, triage)
        assert r2.triage_version == 2
        assert plan["epic_triage_meta"]["version"] == 2

    def test_snapshot_hash_recorded(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")
        expected_hash = review_issue_snapshot_hash(state)
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage)

        assert plan["epic_triage_meta"]["issue_snapshot_hash"] == expected_hash

    def test_triaged_ids_recorded(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage)

        assert sorted(plan["epic_triage_meta"]["triaged_ids"]) == ["r1", "r2"]

    def test_apply_reopens_and_removes_all_automated_protected_artifacts(self):
        """A protected hold cleans old automation before direct triage apply."""
        plan = empty_plan()
        plan["queue_order"] = ["held", "live"]
        plan["promoted_ids"] = ["held"]
        plan["overrides"]["held"] = {"issue_id": "held", "cluster": "auto/review"}
        plan["skipped"]["held"] = {
            "issue_id": "held",
            "kind": "triage_observe_auto",
        }
        plan["issue_dispositions"] = {
            "held": {"decision_source": "observe_auto", "decision": "skip"},
        }
        plan["clusters"] = {
            "auto/review": {
                "name": "auto/review",
                "auto": True,
                "issue_ids": ["held", "live"],
            },
            "source-verified-review-dispositions": {
                "name": "source-verified-review-dispositions",
                "auto": False,
                "issue_ids": ["held"],
            },
        }
        plan["epic_triage_meta"] = {
            "protected_review_issue_ids": ["held"],
            "active_triage_issue_ids": ["held", "live"],
            "issue_dispositions": {
                "held": {"decision_source": "observe_auto", "decision": "skip"},
            },
        }
        state = _state_with_review_issues("held", "live")
        state["issues"]["held"]["status"] = "false_positive"

        apply_triage_to_plan(
            plan,
            state,
            _triage_with_epics(_epic("live-work", ["held", "live"])),
        )

        assert state["issues"]["held"]["status"] == "open"
        assert "held" not in plan["skipped"]
        assert "held" not in plan["issue_dispositions"]
        assert "held" not in plan["queue_order"]
        assert "held" not in plan["promoted_ids"]
        assert "held" not in plan["overrides"]
        assert "held" not in plan["clusters"]["auto/review"]["issue_ids"]
        assert plan["clusters"]["source-verified-review-dispositions"]["issue_ids"] == [
            "held"
        ]
        assert plan["clusters"]["epic/live-work"]["issue_ids"] == ["live"]
        assert "held" not in plan["epic_triage_meta"].get("issue_dispositions", {})

    def test_dismissed_ids_recorded(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2"]
        state = _state_with_review_issues("r1", "r2")
        triage = TriageResult(
            strategy_summary="x",
            epics=[],
            dismissed_issues=[DismissedIssue(issue_id="r1", reason="nope")],
        )

        apply_triage_to_plan(plan, state, triage)

        assert "r1" in plan["epic_triage_meta"]["dismissed_ids"]

    def test_strategy_summary_in_meta(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = TriageResult(strategy_summary="Big picture plan", epics=[])

        apply_triage_to_plan(plan, state, triage)

        assert plan["epic_triage_meta"]["strategy_summary"] == "Big picture plan"

    def test_trigger_recorded(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage, trigger="auto")

        assert plan["epic_triage_meta"]["trigger"] == "auto"

    def test_trigger_defaults_to_manual(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage)

        assert plan["epic_triage_meta"]["trigger"] == "manual"

    def test_plan_updated_timestamp_set(self):
        plan = empty_plan()
        # Set a clearly old timestamp to avoid same-second race
        plan["updated"] = "2020-01-01T00:00:00+00:00"
        state = _state_with_review_issues("r1")
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage)

        assert plan["updated"] != "2020-01-01T00:00:00+00:00"

    def test_strategy_summary_in_result(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage = TriageResult(strategy_summary="My strategy", epics=[])

        result = apply_triage_to_plan(plan, state, triage)

        assert result.strategy_summary == "My strategy"

    def test_only_open_defect_issues_in_triaged_ids(self):
        """triaged_ids should contain IDs of all open defect issues (unified pipeline)."""
        state: dict = {
            "issues": {
                "r1": {"status": "open", "detector": "review"},
                "r2": {"status": "fixed", "detector": "review"},
                "u1": {"status": "open", "detector": "unused"},
                "c1": {"status": "open", "detector": "concerns"},
                "a1": {"status": "open", "detector": "subjective_review"},
            },
            "scan_count": 1,
            "dimension_scores": {},
        }
        plan = empty_plan()
        triage = TriageResult(strategy_summary="x", epics=[])

        apply_triage_to_plan(plan, state, triage)

        triaged = plan["epic_triage_meta"]["triaged_ids"]
        assert "r1" in triaged
        assert "c1" in triaged
        assert "u1" in triaged  # mechanical defects are now triage findings
        # Fixed issues and assessment requests should not appear
        assert "r2" not in triaged
        assert "a1" not in triaged


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
