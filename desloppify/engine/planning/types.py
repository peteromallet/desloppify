"""Typed contracts for plan generation and selection."""

from __future__ import annotations

from typing import TypedDict

from desloppify.state_io import (
    DimensionScore,
    Issue,
    StateModel,
    StateStats,
)


class PlanState(TypedDict, total=False):
    issues: dict[str, Issue]
    stats: StateStats
    dimension_scores: dict[str, DimensionScore]
    codebase_metrics: dict[str, dict]


class PlanItem(TypedDict, total=False):
    id: str
    detector: str
    file: str
    tier: int
    confidence: str
    summary: str
    detail: dict


PlanOutput = str

__all__ = ["PlanItem", "PlanOutput", "PlanState", "StateModel"]
