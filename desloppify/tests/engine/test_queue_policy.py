"""Execution queue defaults must agree with the resolved strict target."""

from __future__ import annotations

import pytest

from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine.planning.queue_policy import build_execution_queue


def _state(target: float = 85.0) -> dict:
    return {
        "issues": {
            "unused::src/a.py::x": {
                "id": "unused::src/a.py::x",
                "detector": "unused",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "unused import",
                "detail": {},
            }
        },
        "scan_count": 5,
        "config": {"target_strict_score": target},
        "dimension_scores": {
            "Naming quality": {
                "score": 90.0,
                "strict": 90.0,
                "checks": 10,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            }
        },
        "subjective_assessments": {
            "naming_quality": {"score": 90.0, "needs_review_refresh": True}
        },
    }


def _ids(state: dict, options: QueueBuildOptions) -> list[str]:
    return [item["id"] for item in build_execution_queue(state, options=options)["items"]]


@pytest.mark.parametrize("target", [85.0, 88.0, 95.0])
def test_plan_and_next_queue_heads_agree_at_the_resolved_target(target: float):
    state = _state(target)
    plan = {"queue_order": [], "skipped": {}}
    context = queue_context(state, plan=plan, target_strict=target)
    next_options = QueueBuildOptions(
        count=None,
        status="open",
        include_subjective=True,
        subjective_threshold=target,
        context=context,
    )
    plan_options = QueueBuildOptions(
        count=None, status="open", include_subjective=True, plan=plan
    )

    assert _ids(state, plan_options) == _ids(state, next_options)
    assert plan_options.subjective_threshold == 100.0


def test_default_subjective_threshold_uses_explicit_context_target():
    state = _state(95.0)
    context = queue_context(
        state, plan={"queue_order": [], "skipped": {}}, target_strict=85.0
    )
    options = QueueBuildOptions(count=None, include_subjective=True, context=context)

    assert _ids(state, options) == ["unused::src/a.py::x"]


def test_explicit_subjective_threshold_is_preserved():
    state = _state(85.0)
    options = QueueBuildOptions(
        count=None,
        include_subjective=True,
        plan={"queue_order": [], "skipped": {}},
        subjective_threshold=95.0,
    )

    assert _ids(state, options) == ["subjective::naming_quality"]
