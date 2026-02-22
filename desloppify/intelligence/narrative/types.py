"""TypedDict definitions for narrative computation outputs."""

from __future__ import annotations

from typing import Literal, TypedDict

from desloppify.intelligence.narrative.action_models import ActionItem, ToolInventory

__all__ = [
    "BadgeStatus",
    "DebtAnalysis",
    "DimensionAnalysis",
    "DimensionEntry",
    "FixerLeverage",
    "LaneInfo",
    "NarrativeResult",
    "PrimaryAction",
    "ReminderItem",
    "RiskFlag",
    "StrictTarget",
    "StrategyResult",
    "VerificationStep",
]


class BadgeStatus(TypedDict):
    """Scorecard badge metadata."""

    generated: bool
    in_readme: bool
    path: str
    recommendation: str | None


class PrimaryAction(TypedDict):
    """Top-priority user action."""

    command: str
    description: str


class VerificationStep(TypedDict):
    """A verification step with command and reason."""

    command: str
    reason: str


class DimensionEntry(TypedDict, total=False):
    """A single dimension summary entry (lowest, biggest gap, or stagnant)."""

    name: str
    strict: float
    issues: int
    impact: float
    subjective: bool
    impact_description: str
    lenient: float
    gap: float
    wontfix_count: int
    stuck_scans: int


class DimensionAnalysis(TypedDict, total=False):
    """Structured per-dimension analysis returned by _analyze_dimensions."""

    lowest_dimensions: list[DimensionEntry]
    biggest_gap_dimensions: list[DimensionEntry]
    stagnant_dimensions: list[DimensionEntry]


class FixerLeverage(TypedDict):
    """Fixer automation coverage estimate."""

    auto_fixable_count: int
    total_count: int
    coverage: float
    impact_ratio: float
    recommendation: str


class LaneInfo(TypedDict):
    """A single strategy work lane."""

    actions: list[int]
    file_count: int
    total_impact: float
    automation: str
    run_first: bool


class StrategyResult(TypedDict):
    """Structured strategy output from compute_strategy."""

    fixer_leverage: FixerLeverage
    lanes: dict[str, LaneInfo]
    can_parallelize: bool
    hint: str


class DebtAnalysis(TypedDict):
    """Wontfix debt analysis returned by _analyze_debt."""

    overall_gap: float
    wontfix_count: int
    worst_dimension: str | None
    worst_gap: float
    trend: Literal["stable", "growing", "shrinking"]


class RiskFlag(TypedDict):
    """A single risk flag entry."""

    type: str
    severity: str
    message: str


class StrictTarget(TypedDict):
    """Strict-score target context."""

    target: float
    current: float | None
    gap: float | None
    state: Literal["below", "above", "at", "unavailable"]
    warning: str | None


class ReminderItem(TypedDict, total=False):
    """A single contextual reminder."""

    type: str
    message: str
    command: str | None
    priority: int
    severity: str
    no_decay: bool


class NarrativeResult(TypedDict):
    """Structured result from compute_narrative()."""

    phase: str
    headline: str | None
    dimensions: DimensionAnalysis
    actions: list[ActionItem]
    strategy: StrategyResult
    tools: ToolInventory
    debt: DebtAnalysis
    milestone: str | None
    primary_action: dict[str, str] | None
    why_now: str | None
    verification_step: VerificationStep
    risk_flags: list[RiskFlag]
    strict_target: StrictTarget
    reminders: list[ReminderItem]
    reminder_history: dict[str, int]
