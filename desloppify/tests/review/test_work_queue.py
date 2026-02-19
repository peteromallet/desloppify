"""Tests for shared queue selection in desloppify.work_queue."""

from __future__ import annotations

from desloppify.engine.work_queue_internal.core import (
    QueueBuildOptions,
)
from desloppify.engine.work_queue_internal.core import (
    build_work_queue as _build_work_queue,
)


def build_work_queue(state, **kwargs):
    return _build_work_queue(state, options=QueueBuildOptions(**kwargs))


def _finding(
    fid: str,
    *,
    detector: str = "smells",
    file: str = "src/a.py",
    tier: int = 3,
    confidence: str = "medium",
    status: str = "open",
    detail: dict | None = None,
) -> dict:
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": confidence,
        "summary": fid,
        "status": status,
        "detail": detail or {},
    }


def _state(findings: list[dict], *, dimension_scores: dict | None = None) -> dict:
    return {
        "findings": {f["id"]: f for f in findings},
        "dimension_scores": dimension_scores or {},
    }


def test_tier_fallback_selects_nearest_non_empty_tier():
    state = _state(
        [
            _finding("t2_item", tier=2),
            _finding("t4_item", tier=4),
        ]
    )

    queue = build_work_queue(state, tier=1, count=None)
    assert queue["requested_tier"] == 1
    assert queue["selected_tier"] == 2
    assert (
        queue["fallback_reason"]
        == "Requested T1 has 0 open -> showing T2 (nearest non-empty)."
    )
    assert [item["id"] for item in queue["items"]] == ["t2_item"]


def test_no_tier_fallback_returns_empty_with_reason():
    state = _state([_finding("t2_item", tier=2)])

    queue = build_work_queue(state, tier=4, count=None, no_tier_fallback=True)
    assert queue["requested_tier"] == 4
    assert queue["selected_tier"] == 4
    assert queue["items"] == []
    assert queue["fallback_reason"] == "Requested T4 has 0 open."


def test_review_finding_is_forced_to_t1():
    review = _finding(
        "review::src/a.py::naming",
        detector="review",
        tier=2,
        detail={"dimension": "naming_quality"},
    )
    mechanical = _finding("smells::src/a.py::x", detector="smells", tier=3)
    state = _state(
        [review, mechanical],
        dimension_scores={
            "Naming Quality": {"score": 94.0, "strict": 94.0, "issues": 1}
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    by_id = {item["id"]: item for item in queue["items"] if item["kind"] == "finding"}
    assert by_id["review::src/a.py::naming"]["effective_tier"] == 1
    assert by_id["smells::src/a.py::x"]["effective_tier"] == 3


def test_review_items_outrank_mechanical_findings():
    urgent = _finding(
        "security::src/a.py::x", detector="security", tier=1, confidence="high"
    )
    review = _finding(
        "review::src/a.py::naming",
        detector="review",
        tier=2,
        confidence="high",
        detail={"dimension": "naming_quality"},
    )
    state = _state(
        [urgent, review],
        dimension_scores={
            "Naming Quality": {"score": 92.0, "strict": 92.0, "issues": 2}
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    assert queue["items"][0]["id"] == "review::src/a.py::naming"
    assert queue["items"][0]["effective_tier"] == 1
    assert queue["items"][1]["effective_tier"] == 1


def test_review_items_sort_by_issue_weight():
    standard = _finding(
        "review::src/a.py::naming",
        detector="review",
        tier=2,
        confidence="high",
        detail={"dimension": "naming_quality"},
    )
    holistic = _finding(
        "review::src/a.py::logic",
        detector="review",
        tier=2,
        confidence="low",
        detail={"dimension": "logic_clarity", "holistic": True},
    )
    state = _state(
        [standard, holistic],
        dimension_scores={
            "Naming Quality": {"score": 92.0, "strict": 92.0, "issues": 2},
            "Logic Clarity": {"score": 88.0, "strict": 88.0, "issues": 3},
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    assert [item["id"] for item in queue["items"][:2]] == [
        "review::src/a.py::logic",
        "review::src/a.py::naming",
    ]
    assert all(item["effective_tier"] == 1 for item in queue["items"][:2])


def test_tier4_queue_contains_mechanical_and_synthetic_subjective_items():
    mech_t4 = _finding(
        "dupes::src/a.py::pair", detector="dupes", tier=4, confidence="medium"
    )
    state = _state(
        [mech_t4],
        dimension_scores={
            "Naming Quality": {"score": 94.0, "strict": 94.0, "issues": 2},
            "Logic Clarity": {"score": 100.0, "strict": 100.0, "issues": 0},
        },
    )

    queue = build_work_queue(state, tier=4, count=None, include_subjective=True)
    ids = {item["id"] for item in queue["items"]}
    kinds = {item["kind"] for item in queue["items"]}
    assert "dupes::src/a.py::pair" in ids
    assert "subjective::naming_quality" in ids
    assert kinds == {"finding", "subjective_dimension"}


def test_explain_payload_added_when_requested():
    state = _state(
        [
            _finding(
                "smells::src/a.py::x", tier=3, confidence="medium", detail={"count": 7}
            )
        ]
    )

    queue = build_work_queue(state, count=None, explain=True)
    item = queue["items"][0]
    assert "explain" in item
    assert item["explain"]["ranking_factors"] == [
        "tier asc",
        "confidence asc",
        "count desc",
        "id asc",
    ]


def test_subjective_items_respect_target_threshold():
    state = _state(
        [],
        dimension_scores={
            "Naming Quality": {"score": 94.0, "strict": 94.0, "issues": 2},
            "AI Generated Debt": {"score": 96.0, "strict": 96.0, "issues": 1},
        },
    )

    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=95
    )
    ids = {item["id"] for item in queue["items"]}
    assert "subjective::naming_quality" in ids
    assert "subjective::ai_generated_debt" not in ids


def test_subjective_item_uses_issues_action_when_matching_review_findings_exist():
    review = _finding(
        "review::.::holistic::mid_level_elegance::split::abc12345",
        detector="review",
        tier=3,
        detail={"holistic": True, "dimension": "mid_level_elegance"},
    )
    state = _state(
        [review],
        dimension_scores={
            "Mid Elegance": {"score": 70.0, "strict": 70.0, "issues": 1},
        },
    )

    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=95
    )
    subj = next(
        item for item in queue["items"] if item["kind"] == "subjective_dimension"
    )
    assert subj["id"] == "subjective::mid_level_elegance"
    assert subj["primary_command"] == "desloppify issues"
    assert subj["detail"]["open_review_findings"] == 1


def test_unassessed_subjective_item_points_to_holistic_refresh():
    state = _state(
        [],
        dimension_scores={
            "High Elegance": {"score": 0.0, "strict": 0.0, "issues": 0},
        },
    )

    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=95
    )
    subj = next(
        item for item in queue["items"] if item["kind"] == "subjective_dimension"
    )
    assert subj["id"] == "subjective::high_level_elegance"
    assert subj["primary_command"] == "desloppify review --prepare --holistic --refresh"


def test_subjective_review_finding_points_to_review_triage():
    coverage = _finding(
        "subjective_review::src/a.py::changed",
        detector="subjective_review",
        tier=4,
        detail={"reason": "changed"},
    )
    state = _state([coverage])

    queue = build_work_queue(state, count=None, include_subjective=False)
    item = queue["items"][0]
    assert item["primary_command"] == "desloppify show subjective_review --status open"


def test_holistic_subjective_review_finding_points_to_holistic_refresh():
    holistic = _finding(
        "subjective_review::.::holistic_unreviewed",
        detector="subjective_review",
        file=".",
        tier=4,
        detail={"reason": "unreviewed"},
    )
    state = _state([holistic])

    queue = build_work_queue(state, count=None, include_subjective=False)
    item = queue["items"][0]
    assert item["primary_command"] == "desloppify review --prepare --holistic --refresh"
