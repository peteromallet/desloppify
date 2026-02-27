"""Typed models for narrative action and tooling outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from desloppify.state import StateModel

ActionType = Literal[
    "auto_fix",
    "manual_fix",
    "reorganize",
    "refactor",
    "issue_queue",
    "debt_review",
]


class ActionItem(TypedDict, total=False):
    """Serialized action row emitted in narrative query payloads."""

    priority: int
    type: ActionType
    detector: str | None
    count: int
    description: str
    command: str
    impact: float
    dimension: str
    gap: float
    lane: str | None


class ToolFixer(TypedDict):
    """One available fixer with detector metadata."""

    name: str
    detector: str
    open_count: int
    command: str


class MoveToolInfo(TypedDict):
    available: bool
    relevant: bool
    reason: str | None
    usage: str


class PlanToolInfo(TypedDict):
    command: str
    description: str


class ToolInventory(TypedDict):
    """Tool block emitted in narrative payload."""

    fixers: list[ToolFixer]
    move: MoveToolInfo
    plan: PlanToolInfo
    badge: dict[str, Any]


@dataclass(frozen=True)
class ActionContext:
    """Inputs needed to compute prioritized narrative actions."""

    by_detector: dict[str, int]
    dimension_scores: dict[str, dict[str, Any]]
    state: StateModel
    debt: dict[str, float]
    lang: str | None
    clusters: dict | None = None
