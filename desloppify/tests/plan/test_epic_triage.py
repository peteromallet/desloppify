"""Tests for epic triage: schema, sync injection, queue items, parsing, and plan mutation."""

from __future__ import annotations

from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS
from desloppify.engine._plan.triage.core import (
    DismissedIssue,
    TriageResult,
    apply_triage_to_plan,
    collect_triage_input,
    parse_triage_result,
)
from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    VALID_EPIC_DIRECTIONS,
    VALID_SKIP_KINDS,
    empty_plan,
    ensure_plan_defaults,
)
from desloppify.engine._plan.policy.stale import review_issue_snapshot_hash
from desloppify.engine._plan.sync.triage import (
    is_triage_stale,
    sync_triage_needed,
)
from desloppify.engine._work_queue.synthetic import build_triage_stage_items

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_with_review_issues(*ids: str) -> dict:
    """Build minimal state with open review issues."""
    work_items = {}
    for fid in ids:
        work_items[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review issue {fid}",
            "confidence": "medium",
            "tier": 2,
            "detail": {"dimension": "abstraction_fitness"},
        }
    return {"work_items": work_items, "issues": work_items, "scan_count": 5, "dimension_scores": {}}


def _state_empty() -> dict:
    work_items: dict[str, dict] = {}
    return {"work_items": work_items, "issues": work_items, "scan_count": 1, "dimension_scores": {}}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemaDefaults:
    def test_empty_plan_has_triage_meta(self):
        plan = empty_plan()
        assert "epics" not in plan
        assert "epic_triage_meta" in plan
        assert isinstance(plan["epic_triage_meta"], dict)

    def test_plan_version_is_current(self):
        plan = empty_plan()
        from desloppify.engine._plan.schema import PLAN_VERSION
        assert plan["version"] == PLAN_VERSION

    def test_ensure_defaults_adds_meta_to_old_plan(self):
        old = {"version": 2, "created": "x", "updated": "x"}
        ensure_plan_defaults(old)
        assert "epics" not in old
        assert isinstance(old["epic_triage_meta"], dict)

    def test_triaged_out_is_valid_skip_kind(self):
        assert "triaged_out" in VALID_SKIP_KINDS

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
        assert review_issue_snapshot_hash(_state_empty()) == ""

    def test_hash_changes_with_issues(self):
        s1 = _state_with_review_issues("a", "b")
        h1 = review_issue_snapshot_hash(s1)
        assert h1 != ""

        s2 = _state_with_review_issues("a", "b", "c")
        h2 = review_issue_snapshot_hash(s2)
        assert h2 != h1

    def test_hash_stable_for_same_issues(self):
        s = _state_with_review_issues("x", "y")
        assert review_issue_snapshot_hash(s) == review_issue_snapshot_hash(s)

    def test_hash_ignores_non_review(self):
        state = {
            "issues": {
                "unused::a": {"status": "open", "detector": "unused"},
                "review::b": {"status": "open", "detector": "review"},
            }
        }
        h = review_issue_snapshot_hash(state)
        assert h != ""
        # Should only include review::b
        state2 = _state_with_review_issues("review::b")
        assert review_issue_snapshot_hash(state2) == h

    def test_hash_ignores_closed(self):
        state = {
            "issues": {
                "review::a": {"status": "fixed", "detector": "review"},
            }
        }
        assert review_issue_snapshot_hash(state) == ""


# ---------------------------------------------------------------------------
# Sync triage needed tests
# ---------------------------------------------------------------------------

class TestSyncTriageNeeded:
    def test_injects_on_new_issues(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")
        result = sync_triage_needed(plan, state)
        assert result.injected
        # All 4 stage IDs injected
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_no_injection_when_hash_up_to_date(self):
        """No injection when snapshot hash matches (review issues unchanged)."""
        state = _state_with_review_issues("r1")
        h = review_issue_snapshot_hash(state)
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {"issue_snapshot_hash": h}
        result = sync_triage_needed(plan, state)
        assert not result.pruned
        # Stage IDs remain untouched
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_stages_preserved_when_no_review_issues(self):
        """Triage stages preserved even if review issues vanish."""
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        state = _state_empty()
        result = sync_triage_needed(plan, state)
        assert not result.pruned
        # Never auto-prunes — stages stay
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_no_changes_when_already_injected(self):
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        state = _state_with_review_issues("r1")
        result = sync_triage_needed(plan, state)
        assert not result.injected  # Already present
        assert not result.pruned

    def test_re_triggers_on_resolved_issue(self):
        state = _state_with_review_issues("r1", "r2")
        h = review_issue_snapshot_hash(state)
        plan = empty_plan()
        plan["epic_triage_meta"] = {"issue_snapshot_hash": h}
        # Resolve r2
        state["work_items"]["r2"]["status"] = "fixed"
        result = sync_triage_needed(plan, state)
        assert result.injected

    def test_injects_at_back(self):
        plan = empty_plan()
        plan["queue_order"] = ["existing_item"]
        state = _state_with_review_issues("r1")
        sync_triage_needed(plan, state)
        assert plan["queue_order"][0] == "existing_item"
        assert plan["queue_order"][1] == "triage::strategize"

    def test_skips_confirmed_stages(self):
        """Stages already confirmed in meta are not injected."""
        plan = empty_plan()
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "older_hash",
            "triage_stages": {
                "observe": {
                    "report": "analysis...",
                    "confirmed_at": "2026-01-01T00:00:00Z",
                }
            },
        }
        state = _state_with_review_issues("r1")
        sync_triage_needed(plan, state)
        assert "triage::observe" not in plan["queue_order"]
        assert "triage::reflect" in plan["queue_order"]
        assert "triage::organize" in plan["queue_order"]
        assert "triage::commit" in plan["queue_order"]

    def test_injection_clears_skipped_overlap_for_new_stages(self):
        """Injected triage stages are removed from skipped to keep plan valid."""
        plan = empty_plan()
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "older_hash",
            "triage_stages": {
                "observe": {
                    "report": "analysis...",
                    "confirmed_at": "2026-01-01T00:00:00Z",
                }
            },
        }
        plan["skipped"] = {
            "triage::reflect": {"kind": "temporary"},
            "triage::sense-check": {"kind": "temporary"},
            "review::x.py::id1": {"kind": "temporary"},
        }
        state = _state_with_review_issues("r1")

        result = sync_triage_needed(plan, state)

        assert "triage::reflect" in result.injected
        assert "triage::sense-check" in result.injected
        assert "triage::reflect" not in plan["skipped"]
        assert "triage::sense-check" not in plan["skipped"]
        assert "review::x.py::id1" in plan["skipped"]

    def test_preserves_when_stages_in_progress_no_issues(self):
        """Triage stages preserved even if all review issues vanish mid-triage."""
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "triage_stages": {"observe": {"report": "x"}, "reflect": {"report": "y"}},
        }
        state = _state_empty()
        result = sync_triage_needed(plan, state)
        assert not result.pruned
        # All IDs remain (sync never prunes)
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_no_auto_prune_when_new_issues_remain(self):
        """Stages not pruned when genuinely new issues still exist."""
        state = _state_with_review_issues("r1")
        h = review_issue_snapshot_hash(state)
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": h,
            "triaged_ids": [],  # r1 not triaged
            "triage_stages": {},
        }
        result = sync_triage_needed(plan, state)
        assert not result.pruned
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_auto_prune_when_new_issues_resolved(self):
        """Stages auto-pruned when all new issues that triggered injection
        have been resolved and triage was completed before (hash exists)."""
        # Start: r1 was triaged, then r2 appeared (triggering injection),
        # then r2 was resolved. Stages should be pruned.
        state = _state_with_review_issues("r1")
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS) + ["item1"]
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "stale_hash",
            "triaged_ids": ["r1"],  # r1 was triaged, r2 was new
            "triage_stages": {},  # no in-progress triage work
        }
        result = sync_triage_needed(plan, state)
        assert result.pruned
        assert not any(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)
        assert "item1" in plan["queue_order"]  # other items preserved

    def test_no_prune_during_initial_triage(self):
        """Stages NOT pruned during initial triage (no prior hash)."""
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        # No issue_snapshot_hash — this is the initial triage
        state = _state_empty()
        result = sync_triage_needed(plan, state)
        assert not result.pruned
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_backfill_triaged_ids_after_partial_triage(self):
        """When triage stages are confirmed but then skipped/removed,
        triaged_ids should be backfilled so the same issues don't
        re-trigger triage on the next cycle."""
        state = _state_with_review_issues("r1", "r2")
        plan = empty_plan()
        # Simulate: observe+reflect confirmed, rest skipped, no stages in queue
        plan["queue_order"] = ["some-objective-item"]
        plan["epic_triage_meta"] = {
            "triage_stages": {
                "observe": {"report": "analysis", "confirmed_at": "2026-01-01T00:00:00Z"},
                "reflect": {"report": "strategy", "confirmed_at": "2026-01-01T00:01:00Z"},
            },
            # triaged_ids and issue_snapshot_hash NOT set (never completed)
        }
        result = sync_triage_needed(plan, state)
        meta = plan["epic_triage_meta"]
        # triaged_ids should be backfilled with current open review IDs
        assert sorted(meta["triaged_ids"]) == ["r1", "r2"]
        assert meta["issue_snapshot_hash"]
        # Should not inject or defer — backfill handles it
        assert not result.injected
        assert not result.deferred

    def test_no_backfill_when_triage_completed(self):
        """No backfill needed when triaged_ids already populated."""
        state = _state_with_review_issues("r1")
        h = review_issue_snapshot_hash(state)
        plan = empty_plan()
        plan["epic_triage_meta"] = {
            "triage_stages": {"observe": {"confirmed_at": "2026-01-01"}},
            "triaged_ids": ["r1"],
            "issue_snapshot_hash": h,
        }
        result = sync_triage_needed(plan, state)
        assert not result.injected
        assert not result.deferred

    def test_no_prune_when_triage_in_progress(self):
        """Stages NOT pruned when user has started triage work."""
        state = _state_with_review_issues("r1")
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "prev_hash",
            "triaged_ids": ["r1"],
            "triage_stages": {"observe": {"report": "analysis..."}},
        }
        result = sync_triage_needed(plan, state)
        assert not result.pruned
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_deferred_triage_escalates_after_repeated_defers(self):
        """Repeated deferred triage should escalate instead of starving indefinitely."""
        plan = empty_plan()
        plan["plan_start_scores"] = {"strict": 75.0}
        plan["queue_order"] = ["unused::obj"]
        state = {
            "issues": {
                "review::r1": {
                    "status": "open",
                    "detector": "review",
                    "file": "review.py",
                    "summary": "review issue",
                    "confidence": "medium",
                    "tier": 2,
                    "detail": {"dimension": "abstraction_fitness"},
                },
                "unused::obj": {
                    "status": "open",
                    "detector": "unused",
                    "file": "obj.py",
                    "summary": "objective issue",
                    "confidence": "high",
                    "tier": 2,
                    "detail": {},
                },
            },
            "scan_count": 10,
            "last_scan": "2026-03-01T00:00:00+00:00",
            "dimension_scores": {},
        }

        first = sync_triage_needed(plan, state)
        assert first.deferred is True
        assert first.injected == []
        defer_meta = plan["epic_triage_meta"]["triage_defer_state"]
        assert defer_meta["defer_count"] == 1
        assert defer_meta["first_deferred_scan"] == 10
        assert defer_meta["deferred_review_ids"] == ["review::r1"]

        state["scan_count"] = 11
        state["last_scan"] = "2026-03-02T00:00:00+00:00"
        second = sync_triage_needed(plan, state)
        assert second.deferred is True
        assert second.injected == []
        assert plan["epic_triage_meta"]["triage_defer_state"]["defer_count"] == 2

        state["scan_count"] = 12
        state["last_scan"] = "2026-03-03T00:00:00+00:00"
        third = sync_triage_needed(plan, state)
        assert third.deferred is False
        assert "triage::observe" in third.injected
        assert bool(plan["epic_triage_meta"].get("triage_force_visible")) is True
        assert plan["queue_order"][0] == "triage::strategize"
        assert "unused::obj" in plan["queue_order"]


# ---------------------------------------------------------------------------
# is_triage_stale tests
# ---------------------------------------------------------------------------

class TestIsTriageStale:
    def test_not_stale_when_no_issues_and_no_stages(self):
        plan = empty_plan()
        state = _state_empty()
        assert not is_triage_stale(plan, state)

    def test_stale_when_new_issues_exist(self):
        state = _state_with_review_issues("r1")
        plan = empty_plan()
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "prev_hash",
            "triaged_ids": [],
        }
        assert is_triage_stale(plan, state)

    def test_not_stale_when_stages_present_but_no_new_issues(self):
        """Stages in queue alone should NOT make triage stale if all
        new issues that triggered injection have been resolved."""
        state = _state_with_review_issues("r1")
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "prev_hash",
            "triaged_ids": ["r1"],
            "triage_stages": {},
        }
        assert not is_triage_stale(plan, state)

    def test_not_stale_when_triage_in_progress(self):
        """In-progress triage (stages in queue + confirmed work) is NOT stale.

        The lifecycle filter already forces triage stages to the front.
        """
        state = _state_with_review_issues("r1")
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "triaged_ids": ["r1"],
            "triage_stages": {"observe": {"report": "analysis"}},
        }
        assert not is_triage_stale(plan, state)

    def test_not_stale_when_only_resolutions(self):
        """Resolving triaged issues should not trigger staleness."""
        state = _state_with_review_issues("r1")
        # Add r2 to triaged_ids but r2 has been resolved (not in current state)
        plan = empty_plan()
        plan["epic_triage_meta"] = {
            "issue_snapshot_hash": "different_hash",
            "triaged_ids": ["r1", "r2"],
        }
        assert not is_triage_stale(plan, state)


# ---------------------------------------------------------------------------
# Build triage item tests
# ---------------------------------------------------------------------------

class TestBuildTriageStageItems:
    def test_returns_empty_when_not_in_queue(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        assert build_triage_stage_items(plan, state) == []

    def test_returns_items_for_each_stage(self):
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        state = _state_with_review_issues("r1", "r2")
        items = build_triage_stage_items(plan, state)
        assert len(items) == 7
        assert all(it["tier"] == 1 for it in items)
        assert all(it["kind"] == "workflow_stage" for it in items)
        assert items[0]["id"] == "triage::strategize"
        assert (
            items[0]["primary_command"]
            == "desloppify plan triage --run-stages --runner codex --only-stages strategize"
        )

    def test_counts_issues(self):
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        state = _state_with_review_issues("r1", "r2", "r3")
        items = build_triage_stage_items(plan, state)
        assert items[0]["detail"]["total_review_issues"] == 3

    def test_blocked_by_chain(self):
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        state = _state_with_review_issues("r1")
        items = build_triage_stage_items(plan, state)
        # strategize has no dependencies
        assert items[0]["blocked_by"] == []
        assert not items[0]["is_blocked"]
        # observe depends on strategize
        assert "triage::strategize" in items[1]["blocked_by"]
        assert items[1]["is_blocked"]

    def test_skips_confirmed_stages(self):
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "triage_stages": {
                "observe": {
                    "report": "done",
                    "confirmed_at": "2026-01-01T00:00:00Z",
                }
            },
        }
        state = _state_with_review_issues("r1")
        items = build_triage_stage_items(plan, state)
        ids = [it["id"] for it in items]
        assert "triage::observe" not in ids
        assert "triage::reflect" in ids

    def test_unconfirmed_recorded_stage_remains_pending(self):
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "triage_stages": {"observe": {"report": "done"}},
        }
        state = _state_with_review_issues("r1")
        items = build_triage_stage_items(plan, state)
        ids = [it["id"] for it in items]
        assert "triage::observe" in ids
        reflect = next(it for it in items if it["id"] == "triage::reflect")
        assert reflect["blocked_by"] == ["triage::observe"]

    def test_missing_queue_id_for_unconfirmed_stage_is_still_rendered(self):
        plan = empty_plan()
        plan["queue_order"] = [
            "triage::enrich",
            "triage::sense-check",
            "triage::commit",
        ]
        plan["epic_triage_meta"] = {
            "triage_stages": {"organize": {"report": "cluster plan"}},
        }
        state = _state_with_review_issues("r1")
        items = build_triage_stage_items(plan, state)
        ids = [it["id"] for it in items]
        assert ids == [
            "triage::organize",
            "triage::enrich",
            "triage::sense-check",
            "triage::commit",
        ]
        enrich = next(it for it in items if it["id"] == "triage::enrich")
        assert enrich["blocked_by"] == ["triage::organize"]


# ---------------------------------------------------------------------------
# Collect triage input tests
# ---------------------------------------------------------------------------

class TestCollectTriageInput:
    def test_collects_open_review_issues(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")
        state["work_items"]["u1"] = {"status": "open", "detector": "unused"}
        si = collect_triage_input(plan, state)
        assert len(si.review_issues) == 2
        assert "r1" in si.review_issues
        assert len(si.objective_backlog_issues) == 1
        assert "u1" in si.objective_backlog_issues

    def test_includes_existing_clusters(self):
        plan = empty_plan()
        plan["clusters"]["epic/test"] = {
            "name": "epic/test", "thesis": "test", "direction": "delete",
            "issue_ids": [], "auto": True, "cluster_key": "epic::epic/test",
        }
        state = _state_with_review_issues("r1")
        si = collect_triage_input(plan, state)
        assert "epic/test" in si.existing_clusters

    def test_collects_non_epic_auto_clusters_separately(self):
        plan = empty_plan()
        plan["clusters"]["epic/test"] = {
            "name": "epic/test",
            "thesis": "test",
            "direction": "delete",
            "issue_ids": [],
            "auto": True,
            "cluster_key": "epic::epic/test",
        }
        plan["clusters"]["auto/unused-imports"] = {
            "name": "auto/unused-imports",
            "issue_ids": ["u1"],
            "auto": True,
            "description": "Remove unused imports",
            "action": "desloppify autofix import-cleanup --dry-run",
        }
        state = _state_with_review_issues("r1")
        state["work_items"]["u1"] = {"status": "open", "detector": "unused"}

        si = collect_triage_input(plan, state)

        assert "epic/test" in si.existing_clusters
        assert "auto/unused-imports" not in si.existing_clusters
        assert "auto/unused-imports" in si.auto_clusters
        assert si.auto_clusters["auto/unused-imports"]["action"] == (
            "desloppify autofix import-cleanup --dry-run"
        )

    def test_tracks_new_since_last(self):
        plan = empty_plan()
        plan["epic_triage_meta"] = {"triaged_ids": ["r1"]}
        state = _state_with_review_issues("r1", "r2")
        si = collect_triage_input(plan, state)
        assert si.new_since_last == {"r2"}
        assert si.resolved_since_last == set()


# ---------------------------------------------------------------------------
# Parse triage result tests
# ---------------------------------------------------------------------------

class TestParseTriageResult:
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
                    "issue_ids": ["r1", "r2"],
                    "dismissed": [],
                    "agent_safe": True,
                    "dependency_order": 1,
                    "action_steps": ["step 1"],
                    "status": "pending",
                }
            ],
            "dismissed_issues": [
                {"issue_id": "r3", "reason": "false positive"}
            ],
            "priority_rationale": "because",
        }
        result = parse_triage_result(raw, valid_ids)
        assert result.strategy_summary == "Test strategy"
        assert len(result.epics) == 1
        assert result.epics[0]["issue_ids"] == ["r1", "r2"]
        assert len(result.dismissed_issues) == 1

    def test_rejects_invalid_issue_ids(self):
        valid_ids = {"r1"}
        raw = {
            "epics": [
                {
                    "name": "test",
                    "thesis": "x",
                    "direction": "delete",
                    "issue_ids": ["r1", "invalid"],
                }
            ]
        }
        result = parse_triage_result(raw, valid_ids)
        assert result.epics[0]["issue_ids"] == ["r1"]

    def test_rejects_invalid_direction(self):
        raw = {
            "epics": [
                {
                    "name": "test",
                    "thesis": "x",
                    "direction": "invalid_direction",
                    "issue_ids": [],
                }
            ]
        }
        result = parse_triage_result(raw, set())
        assert result.epics[0]["direction"] == "simplify"  # fallback

    def test_dismissed_issue_requires_valid_id(self):
        raw = {
            "dismissed_issues": [
                {"issue_id": "valid", "reason": "x"},
                {"issue_id": "invalid", "reason": "x"},
            ]
        }
        result = parse_triage_result(raw, {"valid"})
        assert len(result.dismissed_issues) == 1


# ---------------------------------------------------------------------------
# Apply triage to plan tests
# ---------------------------------------------------------------------------

class TestApplyTriageToPlan:
    def test_creates_epics(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")
        triage_result = TriageResult(
            strategy_summary="Test strategy",
            epics=[
                {
                    "name": "test-cleanup",
                    "thesis": "Clean up test code",
                    "direction": "delete",
                    "issue_ids": ["r1", "r2"],
                    "agent_safe": True,
                    "dependency_order": 1,
                    "action_steps": ["step 1"],
                    "status": "pending",
                }
            ],
        )
        result = apply_triage_to_plan(plan, state, triage_result)
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
            "issue_ids": ["r1"],
            "status": "pending",
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
            "auto": True,
            "cluster_key": "epic::epic/test",
        }
        state = _state_with_review_issues("r1", "r2")
        triage_result = TriageResult(
            strategy_summary="Updated",
            epics=[
                {
                    "name": "epic/test",
                    "thesis": "new thesis",
                    "direction": "merge",
                    "issue_ids": ["r1", "r2"],
                    "dependency_order": 1,
                    "status": "pending",
                }
            ],
        )
        result = apply_triage_to_plan(plan, state, triage_result)
        assert result.epics_updated == 1
        assert plan["clusters"]["epic/test"]["thesis"] == "new thesis"

    def test_preserves_in_progress_status(self):
        plan = empty_plan()
        plan["clusters"]["epic/active"] = {
            "name": "epic/active",
            "thesis": "working on it",
            "direction": "delete",
            "issue_ids": ["r1"],
            "status": "in_progress",
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
            "auto": True,
            "cluster_key": "epic::epic/active",
        }
        state = _state_with_review_issues("r1")
        triage_result = TriageResult(
            strategy_summary="x",
            epics=[
                {
                    "name": "epic/active",
                    "thesis": "updated",
                    "direction": "delete",
                    "issue_ids": ["r1"],
                    "dependency_order": 1,
                    "status": "pending",  # LLM says pending but we keep in_progress
                }
            ],
        )
        apply_triage_to_plan(plan, state, triage_result)
        assert plan["clusters"]["epic/active"]["status"] == "in_progress"

    def test_dismisses_issues(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage_result = TriageResult(
            strategy_summary="x",
            epics=[],
            dismissed_issues=[
                DismissedIssue(issue_id="r3", reason="false positive"),
            ],
        )
        result = apply_triage_to_plan(plan, state, triage_result)
        assert result.issues_dismissed == 1
        assert "r3" in plan["skipped"]
        assert plan["skipped"]["r3"]["kind"] == "triaged_out"
        assert "r3" not in plan["queue_order"]

    def test_updates_snapshot_hash(self):
        plan = empty_plan()
        state = _state_with_review_issues("r1")
        triage_result = TriageResult(strategy_summary="x", epics=[])
        apply_triage_to_plan(plan, state, triage_result)
        meta = plan["epic_triage_meta"]
        assert meta["issue_snapshot_hash"] == review_issue_snapshot_hash(state)
        assert meta["strategy_summary"] == "x"
        assert meta["version"] == 1

    def test_reorders_queue_by_dependency(self):
        plan = empty_plan()
        plan["queue_order"] = ["r1", "r2", "r3", "other"]
        state = _state_with_review_issues("r1", "r2", "r3")
        triage_result = TriageResult(
            strategy_summary="x",
            epics=[
                {
                    "name": "second",
                    "thesis": "second",
                    "direction": "merge",
                    "issue_ids": ["r2"],
                    "dependency_order": 2,
                    "status": "pending",
                },
                {
                    "name": "first",
                    "thesis": "first",
                    "direction": "delete",
                    "issue_ids": ["r1", "r3"],
                    "dependency_order": 1,
                    "status": "pending",
                },
            ],
        )
        apply_triage_to_plan(plan, state, triage_result)
        # Epic issues ordered by dependency: r1, r3 (dep 1), r2 (dep 2), then non-epic
        assert plan["queue_order"] == ["r1", "r3", "r2", "other"]


# ---------------------------------------------------------------------------
# Reconciliation tests
# ---------------------------------------------------------------------------
