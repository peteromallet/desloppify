"""Direct coverage tests for synthetic workflow work-queue item builders."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.engine._work_queue.synthetic_workflow as workflow_mod


def test_build_score_checkpoint_item_returns_none_when_not_queued() -> None:
    assert workflow_mod.build_score_checkpoint_item({"queue_order": []}, {}) is None


def test_build_score_checkpoint_item_includes_strict_delta(monkeypatch) -> None:
    from desloppify.engine._plan.constants import WORKFLOW_SCORE_CHECKPOINT_ID

    monkeypatch.setattr(
        "desloppify.state.score_snapshot",
        lambda _state: SimpleNamespace(strict=76.4),
    )
    plan = {
        "queue_order": [WORKFLOW_SCORE_CHECKPOINT_ID],
        "plan_start_scores": {"strict": 75.0},
    }

    item = workflow_mod.build_score_checkpoint_item(plan, {})

    assert item is not None
    assert item["id"] == WORKFLOW_SCORE_CHECKPOINT_ID
    assert item["kind"] == "workflow_action"
    assert item["summary"].endswith("76.4/100 (+1.4)")
    assert item["detail"]["delta"] == 1.4


def test_build_create_plan_and_import_scores_items() -> None:
    from desloppify.engine._plan.constants import (
        WORKFLOW_CREATE_PLAN_ID,
        WORKFLOW_IMPORT_SCORES_ID,
    )

    create_item = workflow_mod.build_create_plan_item(
        {"queue_order": [WORKFLOW_CREATE_PLAN_ID]}
    )
    assert create_item is not None
    assert create_item["id"] == WORKFLOW_CREATE_PLAN_ID
    assert "Create prioritized plan" in create_item["summary"]

    import_item = workflow_mod.build_import_scores_item(
        {
            "queue_order": [WORKFLOW_IMPORT_SCORES_ID],
            "refresh_state": {
                "pending_import_scores": {
                    "import_file": "/tmp/review/issues.json",
                    "packet_sha256": "abc123",
                }
            },
        },
        {"assessment_import_audit": []},
    )
    assert import_item is not None
    assert import_item["id"] == WORKFLOW_IMPORT_SCORES_ID
    assert "untrusted source" in import_item["detail"]["explanation"]
    assert "/tmp/review/issues.json" in import_item["primary_command"]
    assert import_item["detail"]["packet_sha256"] == "abc123"


def test_build_create_plan_item_uses_confirm_for_unconfirmed_recorded_stage() -> None:
    from desloppify.engine._plan.constants import WORKFLOW_CREATE_PLAN_ID

    create_item = workflow_mod.build_create_plan_item(
        {
            "queue_order": [WORKFLOW_CREATE_PLAN_ID, "triage::reflect"],
            "epic_triage_meta": {
                "triage_stages": {
                    "observe": {
                        "report": "done",
                        "timestamp": "2026-03-09T00:00:00Z",
                    },
                },
            },
        }
    )
    assert create_item is not None
    assert create_item["id"] == WORKFLOW_CREATE_PLAN_ID
    assert create_item["primary_command"].startswith(
        "desloppify plan triage --confirm observe"
    )


def test_build_create_plan_item_advances_to_next_pending_stage() -> None:
    from desloppify.engine._plan.constants import WORKFLOW_CREATE_PLAN_ID

    create_item = workflow_mod.build_create_plan_item(
        {
            "queue_order": [WORKFLOW_CREATE_PLAN_ID, "triage::reflect"],
            "epic_triage_meta": {
                "triage_stages": {
                    "observe": {
                        "report": "done",
                        "timestamp": "2026-03-09T00:00:00Z",
                        "confirmed_at": "2026-03-09T00:01:00Z",
                    },
                },
            },
        }
    )
    assert create_item is not None
    assert create_item["id"] == WORKFLOW_CREATE_PLAN_ID
    assert (
        create_item["primary_command"]
        == "desloppify plan triage --run-stages --runner codex --only-stages reflect"
    )
    tools = create_item["detail"]["planning_tools"]
    assert tools[0]["command"] == (
        "desloppify plan triage --run-stages --runner codex --only-stages reflect"
    )
    assert tools[1]["command"] == (
        "desloppify plan triage --run-stages --runner claude --only-stages reflect"
    )


def test_build_communicate_score_item_formats_command_and_delta(monkeypatch) -> None:
    from desloppify.engine._plan.constants import WORKFLOW_COMMUNICATE_SCORE_ID

    monkeypatch.setattr(
        "desloppify.state.score_snapshot",
        lambda _state: SimpleNamespace(strict=80.0),
    )
    plan = {
        "queue_order": [WORKFLOW_COMMUNICATE_SCORE_ID],
        "plan_start_scores": {"strict": 80.0},
    }

    item = workflow_mod.build_communicate_score_item(plan, {})

    assert item is not None
    assert item["id"] == WORKFLOW_COMMUNICATE_SCORE_ID
    assert item["summary"].endswith("80.0/100")
    assert item["detail"]["delta"] == 0.0
    assert WORKFLOW_COMMUNICATE_SCORE_ID in item["primary_command"]


def test_build_deferred_disposition_item_returns_none_without_temporary_skips() -> None:
    assert workflow_mod.build_deferred_disposition_item({"skipped": {}}) is None
    assert workflow_mod.build_deferred_disposition_item(
        {"skipped": {"i1": {"kind": "permanent"}}}
    ) is None


def test_build_deferred_disposition_item_with_temporary_skips() -> None:
    from desloppify.engine._plan.constants import WORKFLOW_DEFERRED_DISPOSITION_ID

    item = workflow_mod.build_deferred_disposition_item(
        {
            "skipped": {
                "i1": {"kind": "temporary"},
                "i2": {"kind": "temporary"},
                "i3": {"kind": "permanent"},
            }
        }
    )

    assert item is not None
    assert item["id"] == WORKFLOW_DEFERRED_DISPOSITION_ID
    assert item["kind"] == "workflow_action"
    assert "0 clusters + 2 individual items" in item["summary"]
    assert item["primary_command"] == 'desloppify plan unskip "*"'
    assert item["detail"]["deferred_cluster_count"] == 0
    assert item["detail"]["deferred_individual_count"] == 2
    tools = item["detail"]["planning_tools"]
    assert len(tools) == 4
    assert tools[0]["command"] == "desloppify plan queue --include-skipped"
    assert "cluster-or-id" in tools[2]["command"]
    assert "decision_options" in item["detail"]
    assert len(item["detail"]["decision_options"]) == 2


def test_build_deferred_disposition_item_counts_clusters_and_individuals() -> None:
    item = workflow_mod.build_deferred_disposition_item(
        {
            "skipped": {
                "i1": {"kind": "temporary"},
                "i2": {"kind": "temporary"},
                "i3": {"kind": "temporary"},
            },
            "clusters": {
                "auto/a": {"issue_ids": ["i1", "i2"]},
                "auto/b": {"issue_ids": ["i2"]},
            },
        }
    )

    assert item is not None
    assert "2 clusters + 1 individual item" in item["summary"]
    assert item["detail"]["deferred_cluster_count"] == 2
    assert item["detail"]["deferred_individual_count"] == 1
