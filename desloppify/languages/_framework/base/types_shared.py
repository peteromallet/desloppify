"""Shared dataclasses and typed records for language framework configs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict


CoverageStatus = Literal["full", "reduced"]


class DetectorCoverageRecord(TypedDict, total=False):
    """Persisted detector-level coverage confidence metadata."""

    detector: str
    status: CoverageStatus
    confidence: float
    summary: str
    impact: str
    remediation: str
    tool: str
    reason: str


class DetectorEntry(TypedDict):
    """Shared normalized detector-entry shape across framework boundaries."""

    file: str
    tier: int
    confidence: str
    summary: str
    line: NotRequired[int]
    detail: NotRequired[dict[str, Any]]
    name: NotRequired[str]


class ScanCoverageRecord(TypedDict, total=False):
    """Persisted scan-level coverage snapshot for one language run."""

    status: CoverageStatus
    confidence: float
    detectors: dict[str, DetectorCoverageRecord]
    warnings: list[DetectorCoverageRecord]
    updated_at: str


@dataclass(frozen=True)
class DetectorCoverageStatus:
    """Coverage-confidence metadata for a detector in the current scan."""

    detector: str
    status: CoverageStatus
    confidence: float = 1.0
    summary: str = ""
    impact: str = ""
    remediation: str = ""
    tool: str = ""
    reason: str = ""


@dataclass(frozen=True)
class LangSecurityResult:
    """Normalized return shape for language-specific security hooks."""

    entries: list[DetectorEntry]
    files_scanned: int
    coverage: DetectorCoverageStatus | None = None


@dataclass
class FixResult:
    """Return type for fixer wrappers that need to carry metadata."""

    entries: list[dict]
    skip_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class FixerConfig:
    """Configuration for an auto-fixer."""

    label: str
    detect: Callable[[Path], list[dict]]
    fix: Callable[..., FixResult]
    detector: str  # issue detector name (for state resolution)
    verb: str = "Fixed"
    dry_verb: str = "Would fix"
    # Signature: (path, state, prev_score, dry_run, *, lang=None) -> None
    post_fix: Callable[..., None] | None = None
    # True when fix() runs an external tool and needs the scan path as `path=`.
    takes_scan_path: bool = False


@dataclass
class BoundaryRule:
    """A coupling boundary: `protected` dir should not be imported from `forbidden_from`."""

    protected: str  # e.g. "shared/"
    forbidden_from: str  # e.g. "tools/"
    label: str  # e.g. "shared→tools"


@dataclass(frozen=True)
class LangValueSpec:
    """Typed language option/setting schema entry."""

    type: type
    default: object
    description: str = ""


__all__ = [
    "BoundaryRule",
    "CoverageStatus",
    "DetectorEntry",
    "DetectorCoverageRecord",
    "DetectorCoverageStatus",
    "FixerConfig",
    "FixResult",
    "LangSecurityResult",
    "LangValueSpec",
    "ScanCoverageRecord",
]
