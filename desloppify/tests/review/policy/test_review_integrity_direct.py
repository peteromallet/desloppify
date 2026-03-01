"""Direct tests for subjective review integrity helpers."""

from __future__ import annotations

from desloppify.intelligence.integrity import (
    is_holistic_subjective_finding,
    is_subjective_review_open,
    subjective_review_open_breakdown,
    unassessed_subjective_dimensions,
)


def test_is_subjective_review_open_checks_detector_and_status():
    assert is_subjective_review_open(
        {"detector": "subjective_review", "status": "open"}
    )
    assert not is_subjective_review_open(
        {"detector": "subjective_review", "status": "fixed"}
    )
    assert not is_subjective_review_open({"detector": "review", "status": "open"})


def test_is_holistic_subjective_finding_accepts_id_summary_or_detail_markers():
    assert is_holistic_subjective_finding(
        {"id": "subjective_review::.::holistic_stale"}
    )
    assert is_holistic_subjective_finding(
        {"summary": "No holistic codebase review on record"}
    )
    assert is_holistic_subjective_finding({"detail": {"holistic": True}})
    assert not is_holistic_subjective_finding(
        {"id": "subjective_review::src/a.py::changed"}
    )


def test_subjective_review_open_breakdown_counts_reasons_and_holistic_reasons():
    findings = {
        "subjective_review::.::holistic_unreviewed": {
            "detector": "subjective_review",
            "status": "open",
            "detail": {"reason": "unreviewed"},
        },
        "subjective_review::src/a.py::changed": {
            "detector": "subjective_review",
            "status": "open",
            "detail": {"reason": "changed"},
        },
        "subjective_review::src/b.py::stale": {
            "detector": "subjective_review",
            "status": "fixed",
            "detail": {"reason": "stale"},
        },
    }

    total, reasons, holistic_reasons = subjective_review_open_breakdown(findings)
    assert total == 2
    assert reasons == {"unreviewed": 1, "changed": 1}
    assert holistic_reasons == {"unreviewed": 1}


def test_unassessed_subjective_dimensions_finds_zero_placeholder_dimensions():
    dim_scores = {
        "High elegance": {
            "score": 0.0,
            "strict": 0.0,
            "issues": 0,
            "detectors": {"subjective_assessment": {}},
        },
        "Mid elegance": {
            "score": 70.0,
            "strict": 70.0,
            "issues": 1,
            "detectors": {"subjective_assessment": {}},
        },
        "File health": {
            "score": 99.0,
            "strict": 99.0,
            "issues": 0,
            "detectors": {},
        },
    }

    assert unassessed_subjective_dimensions(dim_scores) == ["High elegance"]
