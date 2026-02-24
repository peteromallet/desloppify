"""Tests for retrospective review issue-history context helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from desloppify.intelligence.review._prepare.issue_history import (
    ReviewHistoryOptions,
    build_batch_issue_focus,
    build_issue_history_context,
)
from desloppify.intelligence.review.prepare import (
    HolisticReviewPrepareOptions,
    prepare_holistic_review,
)
from desloppify.state import empty_state


def _review_finding(
    *,
    finding_id: str,
    dimension: str,
    status: str,
    summary: str,
    suggestion: str = "consolidate interfaces",
    note: str | None = None,
    resolved_at: str | None = None,
    last_seen: str = "2026-02-24T10:00:00+00:00",
) -> dict:
    return {
        "id": finding_id,
        "detector": "review",
        "file": ".",
        "tier": 3,
        "confidence": "high",
        "summary": summary,
        "detail": {
            "holistic": True,
            "dimension": dimension,
            "related_files": ["src/a.ts", "src/b.ts"],
            "evidence": ["cross-module pattern"],
            "suggestion": suggestion,
        },
        "status": status,
        "note": note,
        "first_seen": "2026-02-20T10:00:00+00:00",
        "last_seen": last_seen,
        "resolved_at": resolved_at,
        "reopen_count": 0,
        "lang": "typescript",
    }


def test_issue_history_returns_flat_recent_issues():
    state = empty_state()
    f_open = _review_finding(
        finding_id="review::.::holistic::abstraction_fitness::task_param_bag::11111111",
        dimension="abstraction_fitness",
        status="open",
        summary="Task builders rely on oversized parameter bags.",
    )
    f_fixed = _review_finding(
        finding_id="review::.::holistic::abstraction_fitness::task_param_bag::22222222",
        dimension="abstraction_fitness",
        status="fixed",
        summary="Task builders rely on oversized parameter bags.",
        resolved_at="2026-02-24T11:00:00+00:00",
    )
    f_wontfix = _review_finding(
        finding_id="review::.::holistic::high_level_elegance::legacy_surface::33333333",
        dimension="high_level_elegance",
        status="wontfix",
        summary="Legacy compatibility surface remains primary.",
        note="blocked by migration dependency",
        resolved_at="2026-02-24T12:00:00+00:00",
    )
    state["findings"] = {
        f_open["id"]: f_open,
        f_fixed["id"]: f_fixed,
        f_wontfix["id"]: f_wontfix,
    }

    history = build_issue_history_context(
        state,
        options=ReviewHistoryOptions(max_issues=10),
    )

    summary = history["summary"]
    assert summary["total_review_findings"] == 3
    assert summary["open_review_findings"] == 1
    assert summary["status_counts"]["open"] == 1
    assert summary["status_counts"]["fixed"] == 1
    assert summary["status_counts"]["wontfix"] == 1
    assert summary["dimension_open_counts"]["abstraction_fitness"] == 1

    issues = history["recent_issues"]
    assert len(issues) == 3
    # Each issue has the expected fields
    for issue in issues:
        assert "dimension" in issue
        assert "status" in issue
        assert "summary" in issue
        assert "suggestion" in issue
        assert "related_files" in issue
        assert "note" in issue

    # The wontfix one should have a real note
    wontfix_issues = [i for i in issues if i["status"] == "wontfix"]
    assert len(wontfix_issues) == 1
    assert wontfix_issues[0]["note"] == "blocked by migration dependency"


def test_issue_history_strips_auto_resolve_notes():
    """Auto-resolve boilerplate notes should be stripped to empty string."""
    state = empty_state()
    f = _review_finding(
        finding_id="review::.::holistic::abstraction_fitness::test::11111111",
        dimension="abstraction_fitness",
        status="auto_resolved",
        summary="Some issue.",
        note="not reported in latest holistic re-import",
        resolved_at="2026-02-24T11:00:00+00:00",
    )
    state["findings"] = {f["id"]: f}

    history = build_issue_history_context(state)
    assert history["recent_issues"][0]["note"] == ""


def test_issue_history_respects_max_issues():
    state = empty_state()
    state["findings"] = {}
    for idx in range(10):
        f = _review_finding(
            finding_id=f"review::.::holistic::abstraction_fitness::issue_{idx}::{idx:08x}",
            dimension="abstraction_fitness",
            status="open",
            summary=f"Issue number {idx}",
            last_seen=f"2026-02-{20 + idx % 5}T10:00:00+00:00",
        )
        state["findings"][f["id"]] = f

    history = build_issue_history_context(
        state, options=ReviewHistoryOptions(max_issues=5)
    )
    assert len(history["recent_issues"]) == 5


def test_issue_history_sorted_by_last_seen():
    state = empty_state()
    f_old = _review_finding(
        finding_id="review::.::holistic::abstraction_fitness::old::11111111",
        dimension="abstraction_fitness",
        status="open",
        summary="Old issue.",
        last_seen="2026-02-01T10:00:00+00:00",
    )
    f_new = _review_finding(
        finding_id="review::.::holistic::abstraction_fitness::new::22222222",
        dimension="abstraction_fitness",
        status="open",
        summary="New issue.",
        last_seen="2026-02-24T10:00:00+00:00",
    )
    state = empty_state()
    state["findings"] = {f_old["id"]: f_old, f_new["id"]: f_new}

    history = build_issue_history_context(state)
    issues = history["recent_issues"]
    assert issues[0]["summary"] == "New issue."
    assert issues[1]["summary"] == "Old issue."


def test_issue_history_empty_state():
    state = empty_state()
    history = build_issue_history_context(state)
    assert history["summary"]["total_review_findings"] == 0
    assert history["recent_issues"] == []


def test_prepare_holistic_review_optional_issue_history_payload():
    state = empty_state()
    state["findings"] = {
        "review::.::holistic::error_consistency::mixed_error_channels_console_vs_pipeline::9a9a9a9a": _review_finding(
            finding_id="review::.::holistic::error_consistency::mixed_error_channels_console_vs_pipeline::9a9a9a9a",
            dimension="error_consistency",
            status="open",
            summary="Mixed error channels produce inconsistent diagnostics.",
        )
    }
    lang = SimpleNamespace(
        name="typescript",
        file_finder=lambda _path: [],
        dep_graph=None,
        zone_map=None,
        migration_mixed_extensions=set(),
        migration_pattern_pairs=[],
    )

    with_history = prepare_holistic_review(
        Path("."),
        lang,
        state,
        options=HolisticReviewPrepareOptions(
            files=[],
            include_issue_history=True,
            issue_history_max_issues=5,
        ),
    )
    without_history = prepare_holistic_review(
        Path("."),
        lang,
        state,
        options=HolisticReviewPrepareOptions(files=[]),
    )

    assert "historical_review_issues" in with_history
    assert with_history["historical_review_issues"]["summary"]["total_review_findings"] == 1
    assert "historical_review_issues" not in without_history


def test_batch_issue_focus_filters_to_batch_dimensions():
    history = {
        "recent_issues": [
            {
                "dimension": "abstraction_fitness",
                "status": "open",
                "summary": f"AF issue {idx}",
                "suggestion": "fix it",
                "related_files": ["src/a.ts"],
                "note": "",
                "confidence": "high",
                "first_seen": "2026-02-20T10:00:00+00:00",
                "last_seen": "2026-02-24T10:00:00+00:00",
            }
            for idx in range(5)
        ]
        + [
            {
                "dimension": "error_consistency",
                "status": "fixed",
                "summary": f"EC issue {idx}",
                "suggestion": "fix it",
                "related_files": ["src/b.ts"],
                "note": "",
                "confidence": "medium",
                "first_seen": "2026-02-20T10:00:00+00:00",
                "last_seen": "2026-02-24T10:00:00+00:00",
            }
            for idx in range(3)
        ],
    }

    focus = build_batch_issue_focus(
        history,
        dimensions=["abstraction_fitness"],
        max_items=20,
    )

    assert focus["dimensions"] == ["abstraction_fitness"]
    assert focus["selected_count"] == 5
    for issue in focus["issues"]:
        assert issue["dimension"] == "abstraction_fitness"


def test_batch_issue_focus_caps_at_max_items():
    history = {
        "recent_issues": [
            {
                "dimension": "abstraction_fitness",
                "status": "open",
                "summary": f"Issue {idx}",
                "suggestion": "fix",
                "related_files": [],
                "note": "",
                "confidence": "high",
                "first_seen": "2026-02-20T10:00:00+00:00",
                "last_seen": "2026-02-24T10:00:00+00:00",
            }
            for idx in range(15)
        ],
    }

    focus = build_batch_issue_focus(
        history,
        dimensions=["abstraction_fitness"],
        max_items=5,
    )

    assert focus["selected_count"] == 5
    assert len(focus["issues"]) == 5
