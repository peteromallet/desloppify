"""Tests for strategist data collection helpers."""

from __future__ import annotations

from desloppify.engine._plan.triage.strategist_data import (
    collect_strategist_input,
    commit_history_analysis,
    completed_cluster_summary_from_plan,
    completed_cluster_summary_from_progression,
    dimension_trajectories,
    execution_pattern_analysis,
    file_churn_hotspots,
    lifecycle_inventory,
    rework_loop_detection,
    score_trajectory,
)


def _review_issue(
    issue_id: str,
    *,
    dimension: str,
    status: str = "open",
    file: str = "src/a.py",
    detector: str = "review",
    resolved_at: str | None = None,
    reopen_count: int = 0,
) -> tuple[str, dict]:
    return issue_id, {
        "id": issue_id,
        "status": status,
        "file": file,
        "detector": detector,
        "summary": issue_id,
        "detail": {"dimension": dimension},
        "work_item_kind": "review_defect",
        "issue_kind": "review_defect",
        "origin": "review",
        "resolved_at": resolved_at,
        "reopen_count": reopen_count,
    }


def test_score_trajectory_detects_improving_stable_and_declining() -> None:
    improving = score_trajectory(
        [{"strict_score": 61.0}, {"strict_score": 64.5}, {"strict_score": 68.0}]
    )
    assert improving.trend == "improving"
    assert improving.strict_delta == 7.0

    stable = score_trajectory(
        [{"strict_score": 70.0}, {"strict_score": 70.2}, {"strict_score": 70.1}]
    )
    assert stable.trend == "stable"

    declining = score_trajectory(
        [{"strict_score": 80.0}, {"strict_score": 75.0}, {"strict_score": 72.0}]
    )
    assert declining.trend == "declining"
    assert declining.worst_scan_delta == -5.0


def test_dimension_trajectories_marks_stagnant_and_counts_investment() -> None:
    history = [
        {"dimension_scores": {"naming": {"strict": 60.0}, "architecture": {"strict": 72.0}}},
        {"dimension_scores": {"naming": {"strict": 60.2}, "architecture": {"strict": 76.0}}},
        {"dimension_scores": {"naming": {"strict": 60.1}, "architecture": {"strict": 79.0}}},
    ]
    work_items = dict(
        [
            _review_issue(
                "review::a.py::1",
                dimension="naming",
                status="fixed",
                resolved_at="2026-03-01T00:00:00+00:00",
            ),
            _review_issue(
                "review::b.py::2",
                dimension="architecture",
                status="fixed",
                resolved_at="2026-03-02T00:00:00+00:00",
            ),
        ]
    )
    trajectories = dimension_trajectories(
        history,
        {
            "naming": {"strict": 60.1, "score": 60.1},
            "architecture": {"strict": 79.0, "score": 79.0},
        },
        work_items,
    )
    assert trajectories["naming"].trend == "stagnant"
    assert trajectories["naming"].recent_investment == 1
    assert trajectories["architecture"].trend == "improving"
    assert trajectories["architecture"].headroom == 21.0


def test_churn_and_rework_helpers_surface_expected_entries() -> None:
    work_items = dict(
        [
            _review_issue(
                "review::a.py::1",
                dimension="naming",
                status="fixed",
                resolved_at="2026-03-01T00:00:00+00:00",
                file="src/shared.py",
                detector="review",
            ),
            _review_issue(
                "review::a.py::2",
                dimension="naming",
                status="open",
                file="src/shared.py",
                detector="smells",
                reopen_count=2,
            ),
            _review_issue(
                "review::a.py::3",
                dimension="naming",
                status="open",
                file="src/shared.py",
                detector="dupes",
            ),
            _review_issue(
                "review::b.py::4",
                dimension="architecture",
                status="fixed",
                resolved_at="2026-03-01T00:00:00+00:00",
                file="src/other.py",
            ),
        ]
    )
    hotspots = file_churn_hotspots(work_items)
    assert hotspots[0].file == "src/shared.py"
    assert hotspots[0].resolved_count == 1
    assert hotspots[0].current_open_count == 2

    loops = rework_loop_detection(work_items)
    assert loops[0].dimension == "naming"
    assert loops[0].resolved_count == 1
    assert loops[0].new_open_count == 2
    assert loops[0].reopen_count == 2


def test_completed_cluster_summary_extracts_from_progression_and_plan_fallback() -> None:
    summaries = completed_cluster_summary_from_progression(
        [
            {
                "event_type": "triage_complete",
                "timestamp": "2026-03-20T10:00:00+00:00",
                "payload": {
                    "cluster_summaries": [
                        {"name": "rename-pass", "thesis": "batch renames", "issue_count": 3}
                    ]
                },
            }
        ]
    )
    assert summaries[0].name == "rename-pass"
    assert summaries[0].issue_count == 3

    fallback = completed_cluster_summary_from_plan(
        {
            "completed_clusters": [
                {
                    "name": "cleanup",
                    "description": "remove dead code",
                    "issue_ids": ["a", "b"],
                    "completed_at": "2026-03-21T10:00:00+00:00",
                }
            ]
        },
        {"last_completed_at": "2026-03-20T00:00:00+00:00"},
    )
    assert fallback[0].name == "cleanup"
    assert fallback[0].issue_count == 2


def test_execution_inventory_commit_history_and_collect_strategist_input() -> None:
    state = {
        "scan_count": 3,
        "scan_history": [
            {"strict_score": 61.0, "overall_score": 64.0, "dimension_scores": {"naming": {"strict": 61.0}}},
            {"strict_score": 63.0, "overall_score": 66.5, "dimension_scores": {"naming": {"strict": 63.0}}},
            {"strict_score": 62.5, "overall_score": 66.0, "dimension_scores": {"naming": {"strict": 62.5}}},
        ],
        "dimension_scores": {"naming": {"strict": 62.5, "score": 66.0}},
        "work_items": dict(
            [
                _review_issue("review::src/a.py::1", dimension="naming", status="open", file="src/a.py"),
                _review_issue(
                    "review::src/b.py::2",
                    dimension="naming",
                    status="fixed",
                    resolved_at="2026-03-01T00:00:00+00:00",
                    file="src/b.py",
                ),
            ]
        ),
    }
    plan = {
        "queue_order": ["review::src/a.py::1", "triage::observe"],
        "deferred": ["review::later::1"],
        "skipped": {"review::skip::1": {"kind": "temporary"}},
        "clusters": {"cluster-a": {"issue_ids": ["review::src/a.py::1"]}},
        "promoted_ids": ["review::src/a.py::1"],
        "execution_log": [
            {"timestamp": "3026-03-01T00:00:00+00:00", "action": "resolve", "issue_ids": ["a", "b"]},
            {"timestamp": "3026-03-02T00:00:00+00:00", "action": "skip", "issue_ids": ["c"]},
            {"timestamp": "3026-03-03T00:00:00+00:00", "action": "done", "issue_ids": ["d"]},
        ],
        "commit_log": [
            {
                "sha": "deadbeef",
                "recorded_at": "3026-03-02T00:00:00+00:00",
                "issue_ids": ["review::src/b.py::2"],
                "note": "cleanup naming debt",
                "cluster_name": "cluster-a",
            }
        ],
        "epic_triage_meta": {},
    }
    inventory = lifecycle_inventory(state, plan)
    assert inventory["backlog_by_dimension"] == {}
    assert inventory["skipped_by_reason"] == {"temporary": 1}
    assert inventory["deferred_count"] == 1
    assert inventory["prioritized_ids"] == ["review::src/a.py::1"]

    execution = execution_pattern_analysis(plan["execution_log"])
    assert execution.total_resolved == 2
    assert execution.total_done == 1
    assert execution.total_skipped == 1

    commits = commit_history_analysis(plan["commit_log"])
    assert commits.total_commits == 1
    assert commits.committed_issue_count == 1
    assert commits.latest_note == "cleanup naming debt"

    strategist_input = collect_strategist_input(
        state,
        plan,
        progression_events=[
            {
                "event_type": "triage_complete",
                "timestamp": "2026-03-20T00:00:00+00:00",
                "payload": {"cluster_summaries": [{"name": "cluster-a", "thesis": "cleanup", "issue_count": 1}]},
            }
        ],
    )
    assert strategist_input.score_trajectory.trend in {"stable", "improving", "declining"}
    assert strategist_input.completed_clusters[0].name == "cluster-a"
    assert strategist_input.commit_history.total_commits == 1
    assert strategist_input.prioritized_ids == ["review::src/a.py::1"]
