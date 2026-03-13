"""TypeScript framework detection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


FrameworkId = Literal["nextjs", "vite"]


@dataclass(frozen=True)
class FrameworkCandidate:
    id: FrameworkId
    label: str
    score: int
    evidence: dict[str, Any]


@dataclass(frozen=True)
class PrimaryFrameworkDetection:
    """Primary framework detection result for a scan path."""

    package_root: Path
    package_json_relpath: str | None
    primary_id: FrameworkId | None
    primary_score: int
    candidates: tuple[FrameworkCandidate, ...]


__all__ = ["FrameworkCandidate", "FrameworkId", "PrimaryFrameworkDetection"]

