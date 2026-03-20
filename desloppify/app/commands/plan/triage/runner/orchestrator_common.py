"""Shared helpers for triage runner orchestrators."""

from __future__ import annotations

from datetime import UTC, datetime

STAGES: tuple[str, ...] = (
    "strategize",
    "observe",
    "reflect",
    "organize",
    "enrich",
    "sense-check",
)


def parse_only_stages(raw: str | None) -> list[str]:
    """Parse --only-stages comma-separated string into validated stage list."""
    if not raw:
        return list(STAGES)
    stages = [s.strip().lower() for s in raw.split(",") if s.strip()]
    for stage in stages:
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage!r}. Valid: {', '.join(STAGES)}")
    return stages


def run_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
