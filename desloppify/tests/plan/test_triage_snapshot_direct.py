"""Direct coverage for triage snapshot helper functions."""

from __future__ import annotations

import desloppify.engine._plan.triage.snapshot as snapshot_mod


def test_normalized_issue_id_list_filters_invalid_values() -> None:
    result = snapshot_mod._normalized_issue_id_list(
        [" review::a ", "", None, "review::a", "review::b", 17]
    )

    assert result == ["review::a", "review::b"]


def test_cluster_issue_ids_uses_issue_ids_only() -> None:
    cluster = {
        "issue_ids": ["review::a", "review::b", "review::a", ""],
        "action_steps": [
            {"issue_refs": ["review::c", "review::b", None]},
            {"issue_refs": "not-a-list"},
            "bad-step",
        ],
    }

    # action_steps issue_refs are traceability metadata, not membership
    assert snapshot_mod._cluster_issue_ids(cluster) == [
        "review::a",
        "review::b",
    ]


def test_coverage_open_ids_falls_back_to_queue_order_before_first_scan() -> None:
    plan = {
        "queue_order": [
            "review::src/foo.py::naming",
            "concerns::src/bar.py::auth",
            "triage::observe",
            "workflow::run-scan",
        ]
    }
    state = {"issues": {}}

    assert snapshot_mod.coverage_open_ids(plan, state) == {
        "review::src/foo.py::naming",
        "concerns::src/bar.py::auth",
    }


def test_manual_clusters_with_issues_and_find_cluster_for_ignore_auto_clusters() -> None:
    plan = {
        "clusters": {
            "manual": {"issue_ids": ["review::a"], "auto": False},
            "auto-empty": {"issue_ids": [], "auto": True},
            "auto-filled": {"issue_ids": ["review::b"], "auto": True},
        }
    }

    assert snapshot_mod.manual_clusters_with_issues(plan) == ["manual"]
    assert snapshot_mod.find_cluster_for("review::a", plan["clusters"]) == "manual"
    assert snapshot_mod.find_cluster_for("review::missing", plan["clusters"]) is None
