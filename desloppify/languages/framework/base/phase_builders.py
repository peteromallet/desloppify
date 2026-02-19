"""DetectorPhase builder helpers for shared framework phases."""

from __future__ import annotations

from .shared_phases import (
    phase_boilerplate_duplication,
    phase_dupes,
    phase_security,
    phase_subjective_review,
    phase_test_coverage,
)
from .types import DetectorPhase


def detector_phase_test_coverage() -> DetectorPhase:
    """Canonical shared detector phase entry for test coverage."""
    return DetectorPhase("Test coverage", phase_test_coverage)


def detector_phase_security() -> DetectorPhase:
    """Canonical shared detector phase entry for security."""
    return DetectorPhase("Security", phase_security)


def detector_phase_subjective_review() -> DetectorPhase:
    """Canonical shared detector phase entry for subjective review coverage."""
    return DetectorPhase("Subjective review", phase_subjective_review)


def detector_phase_duplicates() -> DetectorPhase:
    """Canonical shared detector phase entry for duplicate detection."""
    return DetectorPhase("Duplicates", phase_dupes, slow=True)


def detector_phase_boilerplate_duplication() -> DetectorPhase:
    """Canonical shared detector phase entry for boilerplate duplication."""
    return DetectorPhase(
        "Boilerplate duplication",
        phase_boilerplate_duplication,
        slow=True,
    )


def shared_subjective_duplicates_tail(
    *,
    pre_duplicates: list[DetectorPhase] | None = None,
) -> list[DetectorPhase]:
    """Shared review tail: subjective review, optional custom phases, then duplicates."""
    phases = [detector_phase_subjective_review()]
    if pre_duplicates:
        phases.extend(pre_duplicates)
    phases.append(detector_phase_boilerplate_duplication())
    phases.append(detector_phase_duplicates())
    return phases


__all__ = [
    "detector_phase_boilerplate_duplication",
    "detector_phase_duplicates",
    "detector_phase_security",
    "detector_phase_subjective_review",
    "detector_phase_test_coverage",
    "shared_subjective_duplicates_tail",
]
