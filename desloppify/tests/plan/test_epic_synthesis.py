"""Tests for epic synthesis: schema, sync injection, queue items, parsing, and plan mutation."""

from __future__ import annotations

from desloppify.engine._plan.epic_synthesis import (
    DismissedFinding,
    SynthesisResult,
    apply_synthesis_to_plan,
    collect_synthesis_input,
    parse_synthesis_result,
)
from desloppify.engine._plan.reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    VALID_EPIC_DIRECTIONS,
    VALID_SKIP_KINDS,
    empty_plan,
    ensure_plan_defaults,
    synthesis_clusters,
)
from desloppify.engine._plan.stale_dimensions import (
    SYNTHESIS_ID,
    review_finding_snapshot_hash,
    sync_synthesis_needed,
)
from desloppify.engine._work_queue.helpers import build_synthesis_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_with_review_findings(*ids: str) -> dict:
    """Build minimal state with open review findings."""
    findings = {}
    for fid in ids:
        findings[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review finding {fid}",
            "confidence": "medium",
            "tier": 2,
            "detail": {"dimension": "abstraction_fitness"},
        }
    return {"findings": findings, "scan_count": 5, "dimension_scores": {}}


def _state_empty() -> dict:
    return {"findings": {}, "scan_count": 1, "dimension_scores": {}}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemaDefaults:
    def test_empty_plan_has_synthesis_meta(self):
        plan = empty_plan()
        assert "epics" not in plan
        assert "epic_synthesis_meta" in plan
        assert isinstance(plan["epic_synthesis_meta"], dict)

    def test_plan_version_is_4(self):
        plan = empty_plan()
        assert plan["version"] == 4

    def test_ensure_defaults_adds_meta_to_old_plan(self):
        old = {"version": 2, "created": "x", "updated": "x"}
        ensure_plan_defaults(old)
        assert "epics" not in old
        assert isinstance(old["epic_synthesis_meta"], dict)

    def test_synthesized_out_is_valid_skip_kind(self):
        assert "synthesized_out" in VALID_SKIP_KINDS

    def test_epic_prefix(self):
        assert EPIC_PREFIX == "epic/"

    def test_valid_epic_directions(self):
        assert "delete" in VALID_EPIC_DIRECTIONS
        assert "merge" in VALID_EPIC_DIRECTIONS
        assert len(VALID_EPIC_DIRECTIONS) == 8


# ---------------------------------------------------------------------------
# Snapshot hash tests
# ---------------------------------------------------------------------------

class TestSnapshotHash:
    def test_empty_state_returns_empty_hash(self):
        assert review_finding_snapshot_hash(_state_empty()) == ""

    def test_hash_changes_with_findings(self):
        s1 = _state_with_review_findings("a", "b")
        h1 = review_finding_snapshot_hash(s1)
        assert h1 != ""

        s2 = _state_with_review_findings("a", "b", "c")
        h2 = review_finding_snapshot_hash(s2)
        assert h2 != h1

    def test_hash_stable_for_same_findings(self):
        s = _state_with_review_findings("x", "y")
        assert review_finding_snapshot_hash(s) == review_finding_snapshot_hash(s)

    def test_hash_ignores_non_review(self):
        state = {
            "findings": {
                "unused::a": {"status": "open", "detector": "unused"},
                "review::b": {"status": "open", "detector": "review"},
            }
        }
        h = review_finding_snapshot_hash(state)
        assert h != ""
        # Should only include review::b
        state2 = _state_with_review_findings("review::b")
        assert review_finding_snapshot_hash(state2) == h

    def test_hash_ignores_closed(self):
        state = {
            "findings": {
                "review::a": {"status": "fixed", "detector": "review"},
            }
        }
        assert review_finding_snapshot_hash(state) == ""


# ---------------------------------------------------------------------------
# Sync synthesis needed tests
# ---------------------------------------------------------------------------

class TestSyncSynthesisNeeded:
    def test_injects_on_new_findings(self):
        plan = empty_plan()
        state = _state_with_review_findings("r1", "r2")
        result = sync_synthesis_needed(plan, state)
        assert result.injected
        assert SYNTHESIS_ID in plan["queue_order"]

    def test_never_auto_prunes_when_up_to_date(self):
        """synthesis::pending is never auto-pruned — only explicit completion removes it."""
        state = _state_with_review_findings("r1")
        h = review_finding_snapshot_hash(state)
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        plan["epic_synthesis_meta"] = {"finding_snapshot_hash": h}
        result = sync_synthesis_needed(plan, state)
        assert not result.pruned
        assert SYNTHESIS_ID in plan["queue_order"]

    def test_never_auto_prunes_when_no_review_findings(self):
        """synthesis::pending preserved even if review findings vanish."""
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        state = _state_empty()
        result = sync_synthesis_needed(plan, state)
        assert not result.pruned
        assert SYNTHESIS_ID in plan["queue_order"]

    def test_no_changes_when_already_injected(self):
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        state = _state_with_review_findings("r1")
        result = sync_synthesis_needed(plan, state)
        assert not result.injected  # Already present
        assert not result.pruned

    def test_re_triggers_on_resolved_finding(self):
        state = _state_with_review_findings("r1", "r2")
        h = review_finding_snapshot_hash(state)
        plan = empty_plan()
        plan["epic_synthesis_meta"] = {"finding_snapshot_hash": h}
        # Resolve r2
        state["findings"]["r2"]["status"] = "fixed"
        result = sync_synthesis_needed(plan, state)
        assert result.injected

    def test_injects_at_front(self):
        plan = empty_plan()
        plan["queue_order"] = ["existing_item"]
        state = _state_with_review_findings("r1")
        sync_synthesis_needed(plan, state)
        assert plan["queue_order"][0] == SYNTHESIS_ID

    def test_preserves_when_stages_in_progress_hash_matches(self):
        """synthesis::pending must NOT be pruned when stages are in progress."""
        state = _state_with_review_findings("r1")
        h = review_finding_snapshot_hash(state)
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        plan["epic_synthesis_meta"] = {
            "finding_snapshot_hash": h,
            "synthesis_stages": {"observe": {"report": "analysis..."}},
        }
        result = sync_synthesis_needed(plan, state)
        assert not result.pruned
        assert SYNTHESIS_ID in plan["queue_order"]

    def test_preserves_when_stages_in_progress_no_findings(self):
        """synthesis::pending preserved even if all review findings vanish mid-synthesis."""
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        plan["epic_synthesis_meta"] = {
            "synthesis_stages": {"observe": {"report": "x"}, "reflect": {"report": "y"}},
        }
        state = _state_empty()
        result = sync_synthesis_needed(plan, state)
        assert not result.pruned
        assert SYNTHESIS_ID in plan["queue_order"]

    def test_no_auto_prune_even_after_stages_cleared(self):
        """Even with cleared stages, synthesis::pending is not auto-pruned.

        _apply_completion() removes synthesis::pending explicitly —
        sync_synthesis_needed should never prune it.
        """
        state = _state_with_review_findings("r1")
        h = review_finding_snapshot_hash(state)
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        plan["epic_synthesis_meta"] = {
            "finding_snapshot_hash": h,
            "synthesis_stages": {},  # cleared on completion
        }
        result = sync_synthesis_needed(plan, state)
        assert not result.pruned
        assert SYNTHESIS_ID in plan["queue_order"]


# ---------------------------------------------------------------------------
# Build synthesis item tests
# ---------------------------------------------------------------------------

class TestBuildSynthesisItem:
    def test_returns_none_when_not_in_queue(self):
        plan = empty_plan()
        state = _state_with_review_findings("r1")
        assert build_synthesis_item(plan, state) is None

    def test_returns_t1_item(self):
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        state = _state_with_review_findings("r1", "r2")
        item = build_synthesis_item(plan, state)
        assert item is not None
        assert item["tier"] == 1
        assert item["kind"] == "synthesis_needed"
        assert item["primary_command"] == "desloppify plan synthesize"

    def test_counts_findings(self):
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        state = _state_with_review_findings("r1", "r2", "r3")
        item = build_synthesis_item(plan, state)
        assert item["detail"]["total_review_findings"] == 3

    def test_tracks_new_and_resolved(self):
        plan = empty_plan()
        plan["queue_order"] = [SYNTHESIS_ID]
        plan["epic_synthesis_meta"] = {"synthesized_ids": ["r1", "r2"]}
        state = _state_with_review_findings("r2", "r3")  # r1 resolved, r3 new
        item = build_synthesis_item(plan, state)
        assert item["detail"]["new_since_last"] == 1
        assert item["detail"]["resolved_since_last"] == 1


# ---------------------------------------------------------------------------
# Collect synthesis input tests
# ---------------------------------------------------------------------------

class TestCollectSynthesisInput:
    def test_collects_open_review_findings(self):
        plan = empty_plan()
        state = _state_with_review_findings("r1", "r2")
        state["findings"]["u1"] = {"status": "open", "detector": "unused"}
        si = collect_synthesis_input(plan, state)
        assert len(si.open_findings) == 2
        assert "r1" in si.open_findings
        assert len(si.mechanical_findings) == 1
        assert "u1" in si.mechanical_findings

    def test_includes_existing_epics(self):
        plan = empty_plan()
        plan["clusters"]["epic/test"] = {
            "name": "epic/test", "thesis": "test", "direction": "delete",
            "finding_ids": [], "auto": True, "cluster_key": "epic::epic/test",
        }
        state = _state_with_review_findings("r1")
        si = collect_synthesis_input(plan, state)
        assert "epic/test" in si.existing_epics

    def test_tracks_new_since_last(self):
        plan = empty_plan()
        plan["epic_synthesis_meta"] = {"synthesized_ids": ["r1"]}
        state = _state_with_review_findings("r1", "r2")
        si = collect_synthesis_input(plan, state)
        assert si.new_since_last == {"r2"}
        assert si.resolved_since_last == set()


# ---------------------------------------------------------------------------
# Parse synthesis result tests
# ---------------------------------------------------------------------------

class TestParseSynthesisResult:
    def test_parses_valid_result(self):
        valid_ids = {"r1", "r2", "r3"}
        raw = {
            "strategy_summary": "Test strategy",
            "epics": [
                {
                    "name": "test-epic",
                    "thesis": "Do the thing",
                    "direction": "delete",
                    "root_cause": "legacy code",
                    "finding_ids": ["r1", "r2"],
                    "dismissed": [],
                    "agent_safe": True,
                    "dependency_order": 1,
                    "action_steps": ["step 1"],
                    "status": "pending",
                }
            ],
            "dismissed_findings": [
                {"finding_id": "r3", "reason": "false positive"}
            ],
            "priority_rationale": "because",
        }
        result = parse_synthesis_result(raw, valid_ids)
        assert result.strategy_summary == "Test strategy"
        assert len(result.epics) == 1
        assert result.epics[0]["finding_ids"] == ["r1", "r2"]
        assert len(result.dismissed_findings) == 1

    def test_rejects_invalid_finding_ids(self):
        valid_ids = {"r1"}
        raw = {
            "epics": [
                {
                    "name": "test",
                    "thesis": "x",
                    "direction": "delete",
                    "finding_ids": ["r1", "invalid"],
                }
            ]
        }
        result = parse_synthesis_result(raw, valid_ids)
        assert result.epics[0]["finding_ids"] == ["r1"]

    def test_rejects_invalid_direction(self):
        raw = {
            "epics": [
                {
                    "name": "test",
                    "thesis": "x",
                    "direction": "invalid_direction",
                    "finding_ids": [],
                }
            ]
        }
        result = parse_synthesis_result(raw, set())
        assert result.epics[0]["direction"] == "simplify"  # fallback

    def test_dismissed_finding_requires_valid_id(self):
        raw = {
            "dismissed_findings": [
                {"finding_id": "valid", "reason": "x"},
                {"finding_id": "invalid", "reason": "x"},
            ]
        }
        result = parse_synthesis_result(raw, {"valid"})
        assert len(result.dismissed_findings) == 1


# ---------------------------------------------------------------------------
# Apply synthesis to plan tests
# ---------------------------------------------------------------------------

class TestApplySynthesisToPlan:
    def test_creates_epics(self):
        plan = empty_plan()
        state = _state_with_review_findings("r1", "r2")
        synthesis = SynthesisResult(
            strategy_summary="Test strategy",
            epics=[
                {
                    "name": "test-cleanup",
                    "thesis": "Clean up test code",
                    "direction": "delete",
                    "finding_ids": ["r1", "r2"],
                    "agent_safe": True,
                    "dependency_order": 1,
                    "action_steps": ["step 1"],
                    "status": "pending",
                }
            ],
        )
        result = apply_synthesis_to_plan(plan, state, synthesis)
        assert result.epics_created == 1
        assert "epic/test-cleanup" in plan["clusters"]
        epic = plan["clusters"]["epic/test-cleanup"]
        assert epic["thesis"] == "Clean up test code"
        assert epic["auto"] is True

    def test_updates_existing_epics(self):
        plan = empty_plan()
        plan["clusters"]["epic/test"] = {
            "name": "epic/test",
            "thesis": "old",
            "direction": "delete",
            "finding_ids": ["r1"],
            "status": "pending",
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
            "auto": True,
            "cluster_key": "epic::epic/test",
        }
        state = _state_with_review_findings("r1", "r2")
        synthesis = SynthesisResult(
            strategy_summary="Updated",
            epics=[
                {
                    "name": "epic/test",
                    "thesis": "new thesis",
                    "direction": "merge",
                    "finding_ids": ["r1", "r2"],
                    "dependency_order": 1,
                    "status": "pending",
                }
            ],
        )
        result = apply_synthesis_to_plan(plan, state, synthesis)
        assert result.epics_updated == 1
        assert plan["clusters"]["epic/test"]["thesis"] == "new thesis"

    def test_preserves_in_progress_status(self):
        plan = empty_plan()
        plan["clusters"]["epic/active"] = {
            "name": "epic/active",
            "thesis": "working on it",
            "direction": "delete",
            "finding_ids": ["r1"],
            "status": "in_progress",
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
            "auto": True,
            "cluster_key": "epic::epic/active",
        }
        state = _state_with_review_findings("r1")
        synthesis = SynthesisResult(
            strategy_summary="x",
            epics=[
                {
                    "name": "epic/active",
                    "thesis": "updated",
                    "direction": "delete",
                    "finding_ids": ["r1"],
                    "dependency_order": 1,
                    "status": "pending",  # LLM says pending but we keep in_progress
                }
            ],
        )
        apply_synthesis_to_plan(plan, state, synthesis)
        assert plan["clusters"]["epic/active"]["status"] == "in_progress"

    def test_dismisses_findings(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3"]
        state = _state_with_review_findings("r1", "r2", "r3")
        synthesis = SynthesisResult(
            strategy_summary="x",
            epics=[],
            dismissed_findings=[
                DismissedFinding(finding_id="r3", reason="false positive"),
            ],
        )
        result = apply_synthesis_to_plan(plan, state, synthesis)
        assert result.findings_dismissed == 1
        assert "r3" in plan["skipped"]
        assert plan["skipped"]["r3"]["kind"] == "synthesized_out"
        assert "r3" not in plan["queue_order"]

    def test_updates_snapshot_hash(self):
        plan = empty_plan()
        state = _state_with_review_findings("r1")
        synthesis = SynthesisResult(strategy_summary="x", epics=[])
        apply_synthesis_to_plan(plan, state, synthesis)
        meta = plan["epic_synthesis_meta"]
        assert meta["finding_snapshot_hash"] == review_finding_snapshot_hash(state)
        assert meta["strategy_summary"] == "x"
        assert meta["version"] == 1

    def test_reorders_queue_by_dependency(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3", "other"]
        state = _state_with_review_findings("r1", "r2", "r3")
        synthesis = SynthesisResult(
            strategy_summary="x",
            epics=[
                {
                    "name": "second",
                    "thesis": "second",
                    "direction": "merge",
                    "finding_ids": ["r2"],
                    "dependency_order": 2,
                    "status": "pending",
                },
                {
                    "name": "first",
                    "thesis": "first",
                    "direction": "delete",
                    "finding_ids": ["r1", "r3"],
                    "dependency_order": 1,
                    "status": "pending",
                },
            ],
        )
        apply_synthesis_to_plan(plan, state, synthesis)
        # Epic findings ordered by dependency: r1, r3 (dep 1), r2 (dep 2), then non-epic
        assert plan["queue_order"] == ["r1", "r3", "r2", "other"]


# ---------------------------------------------------------------------------
# Reconciliation tests
# ---------------------------------------------------------------------------

class TestReconcileWithEpics:
    def test_removes_dead_findings_from_epics(self):
        plan = empty_plan()
        plan["clusters"]["epic/test"] = {
            "name": "epic/test",
            "thesis": "x",
            "direction": "delete",
            "finding_ids": ["r1", "r2"],
            "dismissed": [],
            "status": "pending",
            "auto": True,
            "cluster_key": "epic::epic/test",
        }
        # r1 still alive, r2 gone
        state = _state_with_review_findings("r1")
        result = reconcile_plan_after_scan(plan, state)
        assert plan["clusters"]["epic/test"]["finding_ids"] == ["r1"]
        assert result.changes > 0

    def test_deletes_empty_epics(self):
        plan = empty_plan()
        plan["clusters"]["epic/dead"] = {
            "name": "epic/dead",
            "thesis": "x",
            "direction": "delete",
            "finding_ids": ["r1"],
            "dismissed": [],
            "status": "pending",
            "auto": True,
            "cluster_key": "epic::epic/dead",
        }
        state = _state_empty()
        reconcile_plan_after_scan(plan, state)
        assert "epic/dead" not in plan["clusters"]

    def test_marks_completed_epics(self):
        plan = empty_plan()
        plan["clusters"]["epic/done"] = {
            "name": "epic/done",
            "thesis": "x",
            "direction": "delete",
            "finding_ids": ["r1"],
            "dismissed": ["r2"],
            "status": "pending",
            "auto": True,
            "cluster_key": "epic::epic/done",
        }
        # r1 resolved, r2 still alive (dismissed)
        state = {"findings": {
            "r2": {"status": "open", "detector": "review"},
        }}
        reconcile_plan_after_scan(plan, state)
        # r1 is gone → epic has no finding_ids → gets deleted
        assert "epic/done" not in plan["clusters"]


# ---------------------------------------------------------------------------
# Operations compatibility tests
# ---------------------------------------------------------------------------

class TestOperationsCompat:
    def test_create_cluster_rejects_epic_prefix(self):
        from desloppify.engine._plan.operations import create_cluster
        plan = empty_plan()
        try:
            create_cluster(plan, "epic/test")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "epic/" in str(e)

    def test_set_focus_with_epic(self):
        from desloppify.engine._plan.operations import set_focus
        plan = empty_plan()
        plan["clusters"]["epic/test"] = {
            "name": "epic/test",
            "thesis": "x",
            "direction": "delete",
            "finding_ids": ["r1"],
            "auto": True,
            "cluster_key": "epic::epic/test",
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
        }
        set_focus(plan, "epic/test")
        assert plan["active_cluster"] == "epic/test"
        assert "epic/test" in plan["clusters"]


# ---------------------------------------------------------------------------
# Idempotency test
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_reapply_same_synthesis(self):
        plan = empty_plan()
        state = _state_with_review_findings("r1", "r2")
        synthesis = SynthesisResult(
            strategy_summary="test",
            epics=[
                {
                    "name": "test",
                    "thesis": "x",
                    "direction": "delete",
                    "finding_ids": ["r1", "r2"],
                    "dependency_order": 1,
                    "status": "pending",
                }
            ],
        )
        r1 = apply_synthesis_to_plan(plan, state, synthesis)
        assert r1.epics_created == 1

        # Apply same synthesis again
        r2 = apply_synthesis_to_plan(plan, state, synthesis)
        assert r2.epics_updated == 1
        assert r2.epics_created == 0
        # Epic should still exist with same data
        assert "epic/test" in plan["clusters"]


# ---------------------------------------------------------------------------
# Migration test (v3 epics → v4 clusters)
# ---------------------------------------------------------------------------

class TestEpicMigration:
    def test_migrates_epics_to_clusters(self):
        plan = {
            "version": 3,
            "created": "2025-01-01",
            "updated": "2025-01-01",
            "epics": {
                "epic/cleanup": {
                    "name": "epic/cleanup",
                    "thesis": "Clean up dead code",
                    "direction": "delete",
                    "finding_ids": ["r1", "r2"],
                    "status": "pending",
                    "agent_safe": True,
                    "dependency_order": 1,
                    "action_steps": ["step 1"],
                    "dismissed": ["r3"],
                    "supersedes": [],
                    "source_clusters": [],
                    "synthesis_version": 1,
                    "created_at": "2025-01-01",
                    "updated_at": "2025-01-01",
                }
            },
        }
        ensure_plan_defaults(plan)
        # Epics key should be removed entirely
        assert "epics" not in plan
        # Epic should now be in clusters
        assert "epic/cleanup" in plan["clusters"]
        cluster = plan["clusters"]["epic/cleanup"]
        assert cluster["thesis"] == "Clean up dead code"
        assert cluster["direction"] == "delete"
        assert cluster["finding_ids"] == ["r1", "r2"]
        assert cluster["auto"] is True
        assert cluster["cluster_key"] == "epic::epic/cleanup"
        assert cluster["agent_safe"] is True
        assert cluster["status"] == "pending"

    def test_migration_does_not_overwrite_existing_cluster(self):
        plan = {
            "version": 3,
            "created": "2025-01-01",
            "updated": "2025-01-01",
            "clusters": {
                "epic/existing": {
                    "name": "epic/existing",
                    "description": "Already here",
                    "finding_ids": ["r1"],
                    "auto": True,
                    "cluster_key": "epic::epic/existing",
                    "thesis": "Already migrated",
                }
            },
            "epics": {
                "epic/existing": {
                    "name": "epic/existing",
                    "thesis": "Old thesis",
                    "direction": "merge",
                    "finding_ids": ["r1", "r2"],
                    "status": "pending",
                }
            },
        }
        ensure_plan_defaults(plan)
        assert "epics" not in plan
        # Should keep existing cluster, not overwrite
        assert plan["clusters"]["epic/existing"]["thesis"] == "Already migrated"

    def test_synthesis_clusters_helper(self):
        plan = empty_plan()
        plan["clusters"]["epic/a"] = {
            "name": "epic/a", "thesis": "do thing", "finding_ids": [],
            "auto": True, "cluster_key": "epic::epic/a",
        }
        plan["clusters"]["auto/b"] = {
            "name": "auto/b", "finding_ids": [], "auto": True, "cluster_key": "auto::b",
        }
        result = synthesis_clusters(plan)
        assert "epic/a" in result
        assert "auto/b" not in result
