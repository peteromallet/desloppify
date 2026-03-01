"""Tests for shared queue selection in desloppify.work_queue."""

from __future__ import annotations

from desloppify.engine.work_queue import (
    QueueBuildOptions,
)
from desloppify.engine.work_queue import (
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


def test_review_finding_uses_natural_tier():
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
            "Naming quality": {"score": 94.0, "strict": 94.0, "issues": 1}
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    by_id = {item["id"]: item for item in queue["items"] if item["kind"] == "finding"}
    assert by_id["review::src/a.py::naming"]["effective_tier"] == 2
    assert by_id["smells::src/a.py::x"]["effective_tier"] == 3


def test_review_items_ranked_by_tier_like_mechanical():
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
            "Naming quality": {"score": 92.0, "strict": 92.0, "issues": 2}
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    # T1 security outranks T2 review
    assert queue["items"][0]["id"] == "security::src/a.py::x"
    assert queue["items"][0]["effective_tier"] == 1
    assert queue["items"][1]["effective_tier"] == 2


def test_review_items_sort_by_issue_weight_within_tier():
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
        confidence="high",
        detail={"dimension": "logic_clarity", "holistic": True},
    )
    state = _state(
        [standard, holistic],
        dimension_scores={
            "Naming quality": {"score": 92.0, "strict": 92.0, "issues": 2},
            "Logic clarity": {"score": 88.0, "strict": 88.0, "issues": 3},
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    # Within same tier and confidence, holistic (higher review_weight) sorts first
    assert [item["id"] for item in queue["items"][:2]] == [
        "review::src/a.py::logic",
        "review::src/a.py::naming",
    ]
    assert all(item["effective_tier"] == 2 for item in queue["items"][:2])


def test_tier4_queue_contains_mechanical_and_synthetic_subjective_items():
    mech_t4 = _finding(
        "dupes::src/a.py::pair", detector="dupes", tier=4, confidence="medium"
    )
    state = _state(
        [mech_t4],
        dimension_scores={
            "Naming quality": {"score": 94.0, "strict": 94.0, "issues": 2},
            "Logic clarity": {"score": 100.0, "strict": 100.0, "issues": 0},
        },
    )

    queue = build_work_queue(state, tier=4, count=None, include_subjective=True)
    ids = {item["id"] for item in queue["items"]}
    kinds = {item["kind"] for item in queue["items"]}
    assert "dupes::src/a.py::pair" in ids
    assert "subjective::naming_quality" in ids
    assert kinds == {"finding", "subjective_dimension"}


def test_subjective_items_do_not_starve_objective_queue_head():
    state = _state(
        [
            _finding("security::src/a.py::x", detector="security", tier=1, confidence="high"),
            _finding("smells::src/a.py::y", detector="smells", tier=2, confidence="medium"),
        ],
        dimension_scores={
            "Naming quality": {"score": 92.0, "strict": 92.0, "issues": 3},
            "Logic clarity": {"score": 90.0, "strict": 90.0, "issues": 2},
        },
    )

    queue = build_work_queue(state, count=None, include_subjective=True)
    ids = [item["id"] for item in queue["items"]]
    assert ids[:2] == ["security::src/a.py::x", "smells::src/a.py::y"]
    assert any(item_id.startswith("subjective::") for item_id in ids)


def test_subjective_interleave_guardrail_applies_with_default_count_limit():
    state = _state(
        [
            _finding("security::src/a.py::x", detector="security", tier=1, confidence="high"),
        ],
        dimension_scores={
            "Naming quality": {"score": 80.0, "strict": 80.0, "issues": 5},
        },
    )

    queue = build_work_queue(state, count=1, include_subjective=True)
    assert queue["items"][0]["id"] == "security::src/a.py::x"


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
            "Naming quality": {"score": 94.0, "strict": 94.0, "issues": 2},
            "AI generated debt": {"score": 96.0, "strict": 96.0, "issues": 1},
        },
    )

    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=95
    )
    ids = {item["id"] for item in queue["items"]}
    assert "subjective::naming_quality" in ids
    assert "subjective::ai_generated_debt" not in ids


def test_subjective_item_uses_show_review_when_matching_review_findings_exist():
    review = _finding(
        "review::.::holistic::mid_level_elegance::split::abc12345",
        detector="review",
        tier=3,
        detail={"holistic": True, "dimension": "mid_level_elegance"},
    )
    state = _state(
        [review],
        dimension_scores={
            "Mid elegance": {"score": 70.0, "strict": 70.0, "issues": 1},
        },
    )

    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=95
    )
    subj = next(
        item for item in queue["items"] if item["kind"] == "subjective_dimension"
    )
    assert subj["id"] == "subjective::mid_level_elegance"
    assert subj["primary_command"] == "desloppify show review --status open"
    assert subj["detail"]["open_review_findings"] == 1


def test_unassessed_subjective_item_points_to_holistic_refresh():
    state = _state(
        [],
        dimension_scores={
            "High elegance": {"score": 0.0, "strict": 0.0, "issues": 0},
        },
    )

    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=95
    )
    subj = next(
        item for item in queue["items"] if item["kind"] == "subjective_dimension"
    )
    assert subj["id"] == "subjective::high_level_elegance"
    assert subj["primary_command"] == "desloppify review --prepare"


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
    assert item["primary_command"] == "desloppify show subjective"


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
    assert item["primary_command"] == "desloppify review --prepare"


# ── QueueBuildOptions defaults ────────────────────────────


def test_queue_build_options_defaults():
    opts = QueueBuildOptions()
    assert opts.tier is None
    assert opts.count == 1
    assert opts.scan_path is None
    assert opts.scope is None
    assert opts.status == "open"
    assert opts.include_subjective is True
    assert opts.subjective_threshold == 100.0
    assert opts.chronic is False
    assert opts.no_tier_fallback is False
    assert opts.explain is False


# ── Invalid status raises ValueError ─────────────────────


def test_invalid_status_raises_value_error():
    import pytest

    state = _state([_finding("a")])
    with pytest.raises(ValueError, match="Unsupported status filter"):
        build_work_queue(state, status="bogus")


def test_legacy_string_detail_does_not_crash_queue_build():
    """Queue building should tolerate findings whose detail is a plain string."""
    review = _finding(
        "review::src/a.py::legacy",
        detector="review",
        detail={"dimension": "naming_quality"},
    )
    weird = _finding("responsibility_cohesion::src/a.py::legacy", detector="smells")
    weird["detail"] = "Clusters: alpha, beta"

    state = _state(
        [review, weird],
        dimension_scores={
            "Naming quality": {"score": 92.0, "strict": 92.0, "issues": 1}
        },
    )
    queue = build_work_queue(state, count=None, include_subjective=False)
    ids = [item["id"] for item in queue["items"]]
    assert "review::src/a.py::legacy" in ids
    assert "responsibility_cohesion::src/a.py::legacy" in ids


# ── Subjective threshold clamping ─────────────────────────


def test_subjective_threshold_clamped_to_valid_range():
    """Threshold values outside [0, 100] are clamped, not rejected."""
    state = _state(
        [],
        dimension_scores={
            "Naming quality": {"score": 50.0, "strict": 50.0, "issues": 1},
        },
    )
    # threshold=-10 clamps to 0.0 -> score 50 >= 0 -> item excluded
    queue = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=-10
    )
    subj_items = [item for item in queue["items"] if item["kind"] == "subjective_dimension"]
    assert subj_items == []

    # threshold=200 clamps to 100.0 -> score 50 < 100 -> item included
    queue2 = build_work_queue(
        state, tier=4, count=None, include_subjective=True, subjective_threshold=200
    )
    subj_items2 = [item for item in queue2["items"] if item["kind"] == "subjective_dimension"]
    assert len(subj_items2) >= 1


# ── Count limiting ────────────────────────────────────────


def test_count_limits_returned_items():
    state = _state(
        [
            _finding("a", tier=2, confidence="high"),
            _finding("b", tier=2, confidence="medium"),
            _finding("c", tier=2, confidence="low"),
        ]
    )

    queue = build_work_queue(state, count=2, include_subjective=False)
    assert len(queue["items"]) == 2
    assert queue["total"] == 3


def test_count_none_returns_all_items():
    state = _state(
        [_finding("a", tier=2), _finding("b", tier=3), _finding("c", tier=4)]
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    assert len(queue["items"]) == 3
    assert queue["total"] == 3


def test_default_count_is_1():
    state = _state(
        [_finding("a", tier=2), _finding("b", tier=3)]
    )

    queue = build_work_queue(state, include_subjective=False)
    assert len(queue["items"]) == 1


# ── Empty state ───────────────────────────────────────────


def test_empty_state_returns_empty_queue():
    queue = build_work_queue({}, count=None, include_subjective=False)
    assert queue["items"] == []
    assert queue["total"] == 0
    assert queue["tier_counts"] == {1: 0, 2: 0, 3: 0, 4: 0}
    assert queue["available_tiers"] == []
    assert queue["requested_tier"] is None
    assert queue["selected_tier"] is None
    assert queue["fallback_reason"] is None


# ── Available tiers ───────────────────────────────────────


def test_available_tiers_reflects_populated_tiers():
    state = _state(
        [
            _finding("a", tier=2),
            _finding("b", tier=4),
        ]
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    assert 2 in queue["available_tiers"]
    assert 4 in queue["available_tiers"]
    assert 1 not in queue["available_tiers"]
    assert 3 not in queue["available_tiers"]


# ── Grouped output ────────────────────────────────────────


def test_grouped_output_groups_by_item():
    state = _state(
        [
            _finding("a", file="src/a.py"),
            _finding("b", file="src/b.py"),
        ]
    )

    queue = build_work_queue(state, count=None, include_subjective=False)
    grouped = queue["grouped"]
    # Default grouping is "item", which groups by file
    assert isinstance(grouped, dict)


# ── Status filter ─────────────────────────────────────────


def test_status_filter_fixed():
    state = _state(
        [
            _finding("open_one", status="open"),
            _finding("fixed_one", status="fixed"),
        ]
    )

    queue = build_work_queue(state, status="fixed", count=None, include_subjective=False)
    assert all(item["status"] == "fixed" for item in queue["items"])
    assert len(queue["items"]) == 1


def test_status_filter_all():
    state = _state(
        [
            _finding("open_one", status="open"),
            _finding("fixed_one", status="fixed"),
        ]
    )

    queue = build_work_queue(state, status="all", count=None, include_subjective=False)
    assert len(queue["items"]) == 2


# ── Chronic mode ──────────────────────────────────────────


def test_chronic_mode_filters_reopened_findings():
    findings = [
        {**_finding("chronic_one"), "reopen_count": 3},
        {**_finding("normal_one"), "reopen_count": 0},
        {**_finding("once_reopened"), "reopen_count": 1},
    ]
    state = _state(findings)

    queue = build_work_queue(state, chronic=True, count=None, include_subjective=False)
    ids = {item["id"] for item in queue["items"]}
    assert "chronic_one" in ids
    assert "normal_one" not in ids
    assert "once_reopened" not in ids


# ── Subjective exclusion from chronic mode ────────────────


def test_chronic_mode_excludes_subjective_items():
    state = _state(
        [],
        dimension_scores={
            "Naming quality": {"score": 50.0, "strict": 50.0, "issues": 1},
        },
    )

    queue = build_work_queue(
        state, chronic=True, count=None, include_subjective=True
    )
    subj_items = [item for item in queue["items"] if item["kind"] == "subjective_dimension"]
    assert subj_items == []
