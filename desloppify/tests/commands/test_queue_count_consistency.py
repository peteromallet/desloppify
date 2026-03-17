"""Tests for queue count disagreement fixes (#194, #195, #196).

Covers:
- Fix 1: verify_disappeared preserves open issues and verifies manual ones
- Fix 2: queue counting functions pass scan_path
- Fix 3: compute_subjective_visibility respects scan_path + plan
- Fix 4a: workflow::run-scan synthetic item
- Fix 6: queue_guard passes scan_path
"""

from __future__ import annotations

from unittest.mock import patch

from desloppify.engine._plan.policy.subjective import compute_subjective_visibility
from desloppify.engine._state.merge_issues import verify_disappeared

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issue(
    fid: str,
    detector: str = "unused",
    status: str = "open",
    file: str = "src/foo.ts",
    suppressed: bool = False,
) -> dict:
    f: dict = {
        "id": fid,
        "detector": detector,
        "status": status,
        "file": file,
    }
    if suppressed:
        f["suppressed"] = True
    return f


def _state_with_issues(*issues: dict) -> dict:
    work_items = {f["id"]: f for f in issues}
    return {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 5,
    }


# ---------------------------------------------------------------------------
# Fix 1: verify_disappeared preserves manual authority
# ---------------------------------------------------------------------------

class TestAutoResolveOutOfScope:
    def test_out_of_scope_open_issues_remain_open(self):
        """Open issues outside scan_path remain open instead of auto-closing."""
        existing = {
            "f1": {
                "id": "f1", "status": "open", "file": "supabase/fn.ts",
                "detector": "unused",
            },
            "f2": {
                "id": "f2", "status": "open", "file": "src/app.ts",
                "detector": "unused",
            },
        }
        resolved, _lang, out_of_scope, detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-01-01T00:00:00+00:00",
            lang=None,
            scan_path="src",
        )
        assert existing["f1"]["status"] == "open"
        assert existing["f2"]["status"] == "open"
        assert out_of_scope == 0
        assert resolved == 0
        assert detectors == set()

    def test_out_of_scope_fixed_issues_get_scan_verification(self):
        """Resolved items can be scan-verified when absent in the current scope."""
        existing = {
            "f1": {
                "id": "f1", "status": "fixed", "file": "supabase/fn.ts",
                "detector": "smells",
                "resolution_attestation": {
                    "kind": "manual",
                    "text": "done",
                    "attested_at": "2026-02-01T00:00:00+00:00",
                    "scan_verified": False,
                },
            },
        }
        resolved, _lang, out_of_scope, detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-03-01T00:00:00+00:00",
            lang=None,
            scan_path="src",
        )
        attestation = existing["f1"]["resolution_attestation"]
        assert existing["f1"]["status"] == "fixed"
        assert attestation["scan_verified"] is True
        assert "Still absent in current scan scope" in existing["f1"]["note"]
        assert out_of_scope == 1
        assert resolved == 0
        assert "smells" in detectors

    def test_no_scan_path_leaves_open_items_unchanged(self):
        """When scan_path is None, open disappeared items still stay open."""
        existing = {
            "f1": {
                "id": "f1", "status": "open", "file": "anywhere/file.ts",
                "detector": "unused",
            },
        }
        resolved, _lang, out_of_scope, _detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-01-01T00:00:00+00:00",
            lang=None,
            scan_path=None,
        )
        assert existing["f1"]["status"] == "open"
        assert resolved == 0
        assert out_of_scope == 0

    def test_dot_scan_path_leaves_open_items_unchanged(self):
        """scan_path='.' still leaves open disappeared items unchanged."""
        existing = {
            "f1": {
                "id": "f1", "status": "open", "file": "anywhere/file.ts",
                "detector": "unused",
            },
        }
        resolved, _lang, out_of_scope, _detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-01-01T00:00:00+00:00",
            lang=None,
            scan_path=".",
        )
        assert existing["f1"]["status"] == "open"
        assert resolved == 0
        assert out_of_scope == 0

    def test_out_of_scope_verification_adds_to_resolved_detectors(self):
        """Out-of-scope verification still records affected detectors."""
        existing = {
            "f1": {
                "id": "f1", "status": "false_positive", "file": "other/file.ts",
                "detector": "smells",
                "resolution_attestation": {
                    "kind": "manual",
                    "text": "false positive",
                    "attested_at": "2026-02-01T00:00:00+00:00",
                    "scan_verified": False,
                },
            },
        }
        _resolved, _lang, _out_of_scope, detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-01-01T00:00:00+00:00",
            lang=None,
            scan_path="src",
        )
        assert "smells" in detectors

    def test_open_test_coverage_issue_auto_resolves_when_file_now_in_test_zone(self):
        """Stale open coverage findings should clear once the file is non-production."""
        existing = {
            "f1": {
                "id": "f1",
                "status": "open",
                "file": "src/foo.test.ts",
                "detector": "test_coverage",
            },
        }
        resolved, _lang, out_of_scope, detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-04-01T00:00:00+00:00",
            lang=None,
            scan_path=".",
            zone_lookup=lambda _file: "test",
        )
        assert existing["f1"]["status"] == "auto_resolved"
        assert "reclassified to test zone" in existing["f1"]["note"]
        assert out_of_scope == 0
        assert resolved == 1
        assert detectors == {"test_coverage"}

    def test_open_non_coverage_issue_does_not_auto_resolve_from_zone_lookup(self):
        """Manual authority remains for non-test_coverage open findings."""
        existing = {
            "f1": {
                "id": "f1",
                "status": "open",
                "file": "src/foo.test.ts",
                "detector": "unused",
            },
        }
        resolved, _lang, out_of_scope, detectors = verify_disappeared(
            existing,
            current_ids=set(),
            suspect_detectors=set(),
            now="2026-04-01T00:00:00+00:00",
            lang=None,
            scan_path=".",
            zone_lookup=lambda _file: "test",
        )
        assert existing["f1"]["status"] == "open"
        assert out_of_scope == 0
        assert resolved == 0
        assert detectors == set()


# ---------------------------------------------------------------------------
# Fix 2: queue counting functions pass scan_path
# ---------------------------------------------------------------------------

class TestQueueCountingScanPath:
    def test_queue_count_respects_scan_path_from_state(self):
        """build_work_queue auto-reads scan_path from state and filters issues."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {
            "issues": {
                "f1": {
                    "id": "f1", "detector": "unused", "status": "open",
                    "file": "src/a.ts", "tier": 1, "confidence": "high",
                    "summary": "in scope", "detail": {},
                },
                "f2": {
                    "id": "f2", "detector": "unused", "status": "open",
                    "file": "other/b.ts", "tier": 1, "confidence": "high",
                    "summary": "out of scope", "detail": {},
                },
            },
            "scan_path": "src",
            "scan_count": 5,
        }
        # No explicit scan_path — auto-reads "src" from state
        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None),
        )
        ids = {item["id"] for item in result["items"]}
        assert "f1" in ids
        assert "f2" not in ids
        assert result["total"] == 1

    def test_queue_count_no_scan_path_returns_all(self):
        """Without scan_path in state, all issues are returned."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {
            "issues": {
                "f1": {
                    "id": "f1", "detector": "unused", "status": "open",
                    "file": "src/a.ts", "tier": 1, "confidence": "high",
                    "summary": "a", "detail": {},
                },
                "f2": {
                    "id": "f2", "detector": "unused", "status": "open",
                    "file": "other/b.ts", "tier": 1, "confidence": "high",
                    "summary": "b", "detail": {},
                },
            },
            "scan_count": 5,
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None),
        )
        assert result["total"] == 2

    def test_explicit_scan_path_overrides_state(self):
        """Explicit scan_path on QueueBuildOptions overrides state value."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {
            "issues": {
                "f1": {
                    "id": "f1", "detector": "unused", "status": "open",
                    "file": "src/a.ts", "tier": 1, "confidence": "high",
                    "summary": "a", "detail": {},
                },
                "f2": {
                    "id": "f2", "detector": "unused", "status": "open",
                    "file": "other/b.ts", "tier": 1, "confidence": "high",
                    "summary": "b", "detail": {},
                },
            },
            "scan_path": "src",  # state says "src"
            "scan_count": 5,
        }
        # Explicit scan_path=None disables filtering despite state having "src"
        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None, scan_path=None),
        )
        assert result["total"] == 2


# ---------------------------------------------------------------------------
# Fix 3: compute_subjective_visibility respects scan_path + plan
# ---------------------------------------------------------------------------

class TestSubjectivePolicyScanPathAndPlan:
    def test_scan_path_excludes_out_of_scope_issues(self):
        """Issues outside scan_path don't count toward objective backlog."""
        state = _state_with_issues(
            _issue("f1", "unused", file="src/app.ts"),
            _issue("f2", "unused", file="supabase/fn.ts"),
            _issue("f3", "unused", file="src/lib.ts"),
        )
        # Without scan_path: all 3 count
        policy_all = compute_subjective_visibility(state)
        assert policy_all.objective_count == 3

        # With scan_path: only 2 in src/ count
        policy_scoped = compute_subjective_visibility(state, scan_path="src")
        assert policy_scoped.objective_count == 2
        assert policy_scoped.has_objective_backlog is True

    def test_scan_path_drains_backlog_correctly(self):
        """When all in-scope issues are resolved, backlog is drained even
        if out-of-scope issues remain open."""
        state = _state_with_issues(
            _issue("f1", "unused", file="supabase/fn.ts"),
            _issue("f2", "unused", file="supabase/other.ts"),
        )
        policy = compute_subjective_visibility(state, scan_path="src")
        assert policy.objective_count == 0
        assert policy.has_objective_backlog is False

    def test_plan_skipped_issues_excluded(self):
        """Issues in plan['skipped'] don't count toward objective backlog."""
        state = _state_with_issues(
            _issue("f1", "unused", file="src/a.ts"),
            _issue("f2", "unused", file="src/b.ts"),
            _issue("f3", "unused", file="src/c.ts"),
        )
        plan = {"skipped": {"f1": {"kind": "temporary"}, "f2": {"kind": "permanent"}}}
        policy = compute_subjective_visibility(state, plan=plan)
        assert policy.objective_count == 1  # only f3

    def test_scan_path_and_plan_combined(self):
        """Both filters applied together: scope + skipped."""
        state = _state_with_issues(
            _issue("f1", "unused", file="src/a.ts"),     # in scope, not skipped → counts
            _issue("f2", "unused", file="src/b.ts"),     # in scope, skipped → excluded
            _issue("f3", "unused", file="other/c.ts"),   # out of scope → excluded
        )
        plan = {"skipped": {"f2": {"kind": "temporary"}}}
        policy = compute_subjective_visibility(state, scan_path="src", plan=plan)
        assert policy.objective_count == 1
        assert policy.has_objective_backlog is True

    def test_no_params_backward_compat(self):
        """Without new params, behavior is unchanged (all issues counted)."""
        state = _state_with_issues(
            _issue("f1", "unused", file="anywhere/a.ts"),
        )
        policy = compute_subjective_visibility(state)
        assert policy.objective_count == 1


# ---------------------------------------------------------------------------
# Fix 4a: workflow::run-scan synthetic item
# ---------------------------------------------------------------------------

class TestWorkflowRunScanItem:
    def test_run_scan_item_injected_when_queue_empty_and_plan_active(self):
        """When queue is empty and no post-flight scan is recorded, workflow::run-scan appears."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": [],
            "skipped": {},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        items = result["items"]
        assert len(items) == 1
        assert items[0]["id"] == "workflow::run-scan"
        assert items[0]["kind"] == "workflow_action"
        assert "scan" in items[0]["primary_command"]

    def test_run_scan_not_injected_when_real_items_exist(self):
        """When queue has real issues, no workflow::run-scan item."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {
            "issues": {
                "f1": {
                    "id": "f1", "detector": "unused", "status": "open",
                    "file": "src/a.ts", "tier": 1, "confidence": "high",
                    "summary": "test", "detail": {},
                },
            },
            "scan_count": 5,
        }
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": ["f1"],
            "skipped": {},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        run_scan_items = [i for i in result["items"] if i.get("id") == "workflow::run-scan"]
        assert len(run_scan_items) == 0

    def test_deferred_disposition_blocks_run_scan_when_temporary_skips_exist(self):
        """Deferred temporary skips must be resolved before post-flight scan begins."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {
            "issues": {
                "f1": {
                    "id": "f1", "detector": "unused", "status": "open",
                    "file": "src/a.ts", "tier": 1, "confidence": "high",
                    "summary": "test", "detail": {},
                },
            },
            "scan_count": 5,
        }
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": [],
            "skipped": {"f1": {"kind": "temporary"}},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        ids = [item["id"] for item in result["items"]]
        assert ids == ["workflow::deferred-disposition"]
        deferred = result["items"][0]
        assert deferred["kind"] == "workflow_action"
        assert "0 clusters + 1 individual item" in deferred["summary"]
        assert deferred["primary_command"] == 'desloppify plan unskip "*"'

    def test_deferred_disposition_not_shown_for_permanent_skips(self):
        """Permanent skips are decisions already; only run-scan should remain."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": [],
            "skipped": {"f1": {"kind": "permanent"}},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        ids = [item["id"] for item in result["items"]]
        assert "workflow::deferred-disposition" not in ids
        assert ids == ["workflow::run-scan"]

    def test_run_scan_injected_without_plan_start_scores(self):
        """Post-flight scan still surfaces when score-cycle metadata is empty."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        plan = {
            "plan_start_scores": {},
            "queue_order": [],
            "skipped": {},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        assert result["items"][0]["id"] == "workflow::run-scan"

    def test_run_scan_not_injected_after_postflight_scan_completed(self):
        """Once the scan stage completes for this boundary, empty queue stays empty."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        plan = {
            "plan_start_scores": {},
            "queue_order": [],
            "skipped": {},
            "refresh_state": {"postflight_scan_completed_at_scan_count": 5},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        assert result["total"] == 0

    def test_deferred_disposition_injected_without_plan_start_scores(self):
        """Deferred temporary skips should still surface even without score-cycle metadata."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        plan = {
            "plan_start_scores": {},
            "queue_order": [],
            "skipped": {"f1": {"kind": "temporary"}},
        }
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=plan,
            ),
        )
        assert result["total"] == 1
        assert result["items"][0]["id"] == "workflow::deferred-disposition"

    def test_run_scan_not_injected_without_plan(self):
        """No workflow::run-scan when no plan is provided."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                status="open",
                count=None,
                plan=None,
            ),
        )
        assert result["total"] == 0

    def test_run_scan_does_not_block_scan_preflight(self):
        """The scan preflight gate uses score_display_mode which sees
        objective_actionable=0, so workflow::run-scan doesn't create a circular block."""
        from desloppify.app.commands.helpers.queue_progress import (
            plan_aware_queue_breakdown,
        )

        state: dict = {"issues": {}, "scan_count": 5}
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": [],
            "skipped": {},
        }
        breakdown = plan_aware_queue_breakdown(state, plan=plan)
        assert breakdown.queue_total == 1
        assert breakdown.workflow == 1
        assert breakdown.objective_actionable == 0  # gate passes


# ---------------------------------------------------------------------------
# Cluster focus must not trigger false-empty queue (workflow::run-scan bug)
# ---------------------------------------------------------------------------

class TestClusterFocusDoesNotTriggerRunScan:
    """Regression tests: active_cluster must not affect lifecycle decisions.

    The root cause was that cluster focus (a view-layer concern) was applied
    inside build_work_queue, making the queue look empty when items existed
    outside the focused cluster.  Now build_work_queue always returns the
    canonical global queue; cluster focus is applied by callers.
    """

    def _make_state_and_plan(self):
        """Two open issues, one in cluster 'auth', one outside."""
        work_items = {
            "f1": {
                "id": "f1", "detector": "unused", "status": "open",
                "file": "src/auth.ts", "tier": 1, "confidence": "high",
                "summary": "in cluster", "detail": {},
            },
            "f2": {
                "id": "f2", "detector": "unused", "status": "open",
                "file": "src/utils.ts", "tier": 1, "confidence": "high",
                "summary": "outside cluster", "detail": {},
            },
        }
        state: dict = {
            "work_items": work_items,
            "issues": work_items,
            "scan_count": 5,
        }
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": ["f1", "f2"],
            "skipped": {},
            "clusters": {
                "auth": {"issue_ids": ["f1"]},
            },
            "active_cluster": "auth",
        }
        return state, plan

    def test_canonical_queue_includes_all_items_despite_active_cluster(self):
        """build_work_queue returns all items regardless of active_cluster."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state, plan = self._make_state_and_plan()
        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None, plan=plan),
        )
        ids = {i["id"] for i in result["items"]}
        assert "f1" in ids and "f2" in ids, (
            "build_work_queue must return all items — cluster focus is a caller concern"
        )

    def test_no_run_scan_when_items_exist_outside_cluster(self):
        """Resolving focused-cluster items doesn't trigger run-scan fallback."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state, plan = self._make_state_and_plan()
        state["work_items"]["f1"]["status"] = "resolved"
        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None, plan=plan),
        )
        run_scan = [i for i in result["items"] if i["id"] == "workflow::run-scan"]
        assert len(run_scan) == 0, (
            "workflow::run-scan must not appear when items exist outside the focused cluster"
        )

    def test_breakdown_not_affected_by_active_cluster(self):
        """plan_aware_queue_breakdown sees the global queue — not the cluster view."""
        from desloppify.app.commands.helpers.queue_progress import (
            ScoreDisplayMode,
            plan_aware_queue_breakdown,
            score_display_mode,
        )

        state, plan = self._make_state_and_plan()
        state["work_items"]["f1"]["status"] = "resolved"
        breakdown = plan_aware_queue_breakdown(state, plan=plan)
        assert breakdown.objective_actionable >= 1, (
            "active_cluster must not hide items from lifecycle breakdown"
        )
        mode = score_display_mode(breakdown, plan["plan_start_scores"]["strict"])
        assert mode is ScoreDisplayMode.FROZEN, (
            "Score should stay FROZEN when objective items exist outside focused cluster"
        )

    def test_run_scan_injected_when_globally_empty(self):
        """When ALL issues are resolved, run-scan appears normally."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state, plan = self._make_state_and_plan()
        state["work_items"]["f1"]["status"] = "resolved"
        state["work_items"]["f2"]["status"] = "resolved"
        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None, plan=plan),
        )
        run_scan = [i for i in result["items"] if i["id"] == "workflow::run-scan"]
        assert len(run_scan) == 1, (
            "workflow::run-scan should appear when the queue is globally empty"
        )


# ---------------------------------------------------------------------------
# Stale tracked IDs must not broaden execution to backlog
# ---------------------------------------------------------------------------

class TestStaleTrackedPlanDoesNotBroadenExecution:
    def test_stale_plan_shows_run_scan_instead_of_backlog_items(self):
        """A stale queue_order should drain into postflight, not generic backlog."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state = {
            "issues": {
                "live-issue": {
                    "id": "live-issue",
                    "detector": "unused",
                    "status": "open",
                    "file": "src/live.ts",
                    "tier": 1,
                    "confidence": "high",
                    "summary": "still open but not tracked by the plan",
                    "detail": {},
                },
            },
            "scan_count": 5,
        }
        plan = {
            "plan_start_scores": {"strict": 75.0},
            "queue_order": ["stale-issue"],
            "skipped": {},
            "clusters": {},
            "overrides": {},
            "refresh_state": {},
        }

        result = build_work_queue(
            state,
            options=QueueBuildOptions(status="open", count=None, plan=plan),
        )

        ids = [item["id"] for item in result["items"]]
        assert ids == ["workflow::run-scan"], (
            "stale tracked IDs should not make all open backlog items execution work"
        )


# ---------------------------------------------------------------------------
# Fix 4a: render_queue_header for workflow-only items
# ---------------------------------------------------------------------------

class TestRenderQueueHeaderWorkflow:
    def test_header_shows_queue_count_for_run_scan(self, capsys):
        from desloppify.app.commands.next.render_support import (
            render_queue_header,
        )
        queue = {
            "total": 1,
            "items": [{"id": "workflow::run-scan", "kind": "workflow_action"}],
        }
        render_queue_header(queue, explain=False)
        output = capsys.readouterr().out
        assert "Queue: 1 item" in output
        assert "Queue cleared" not in output

    def test_header_shows_count_for_real_items(self, capsys):
        from desloppify.app.commands.next.render_support import (
            render_queue_header,
        )
        queue = {
            "total": 5,
            "items": [{"id": "f1", "kind": "issue"}],
        }
        render_queue_header(queue, explain=False)
        output = capsys.readouterr().out
        assert "5 items" in output
        assert "cleared" not in output


# ---------------------------------------------------------------------------
# Fix 6: queue_guard passes scan_path
# ---------------------------------------------------------------------------

class TestQueueGuardScanPath:
    def test_queue_guard_respects_scan_path_from_state(self):
        """_check_queue_order_guard uses build_work_queue which auto-reads
        scan_path from state, so out-of-scope items don't appear in the queue."""
        from desloppify.app.commands.resolve.queue_guard import _check_queue_order_guard
        from desloppify.app.commands.resolve.plan_load import (
            DegradedPlanWarningState,
            ResolvePlanAccess,
        )

        state = {
            "issues": {
                "f1": {"id": "f1", "status": "open", "file": "src/a.ts"},
            },
            "scan_path": "src",
        }
        mock_result = {
            "total": 1,
            "items": [{"id": "f1", "kind": "issue"}],
            "grouped": {},
            "new_ids": set(),
        }
        plan_access = ResolvePlanAccess(
            plan={"queue_order": ["f1"], "skipped": {}},
            degraded=False,
            error_kind=None,
            warning_state=DegradedPlanWarningState(),
        )
        with (
            patch(
                "desloppify.app.commands.resolve.queue_guard.build_work_queue",
                return_value=mock_result,
            ) as mock_build,
        ):
            # Should not raise — f1 is at front of queue
            result = _check_queue_order_guard(state, ["f1"], "fixed", plan_access=plan_access)
            assert result is False
            # Verify build_work_queue was called (scan_path resolved internally)
            mock_build.assert_called_once()
