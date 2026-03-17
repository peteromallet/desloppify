"""Shared advocacy detector phase runners for all language configs.

These phases wrap the advocacy language and security detectors and
normalize their output to desloppify Issues.
"""

from __future__ import annotations

from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import adjust_potential
from desloppify.languages._framework.base.types import (
    DetectorPhase,
    LangRuntimeContract,
)
from desloppify.state_io import Issue


def phase_advocacy_language(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], dict[str, int]]:
    """Detect speciesist language patterns in source files."""
    from desloppify.engine.detectors.advocacy_language import detect_advocacy_language

    lang_extensions = frozenset(lang.extensions) if lang.extensions else None
    entries, potentials = detect_advocacy_language(path, lang_extensions)

    results: list[Issue] = []
    for entry in entries:
        results.append(
            make_issue(
                "advocacy_language",
                entry["file"],
                entry.get("name", ""),
                tier=entry["tier"],
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail=entry.get("detail", {}),
            )
        )

    potential_count = potentials.get("advocacy_language", 0)
    log(f"         {len(entries)} instances → {len(results)} issues")
    return results, {
        "advocacy_language": adjust_potential(lang.zone_map, potential_count),
    }


def phase_advocacy_security(
    path: Path, lang: LangRuntimeContract
) -> tuple[list[Issue], dict[str, int]]:
    """Detect advocacy-specific security antipatterns."""
    from desloppify.engine.detectors.advocacy_security import detect_advocacy_security

    entries, potentials = detect_advocacy_security(path)

    results: list[Issue] = []
    for entry in entries:
        results.append(
            make_issue(
                "advocacy_security",
                entry["file"],
                entry.get("name", ""),
                tier=entry["tier"],
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail=entry.get("detail", {}),
            )
        )

    potential_count = potentials.get("advocacy_security", 0)
    log(f"         {len(entries)} instances → {len(results)} issues")
    return results, {
        "advocacy_security": adjust_potential(lang.zone_map, potential_count),
    }


def detector_phase_advocacy_language() -> DetectorPhase:
    """Return a DetectorPhase for advocacy language detection."""
    return DetectorPhase("Advocacy language", phase_advocacy_language)


def detector_phase_advocacy_security() -> DetectorPhase:
    """Return a DetectorPhase for advocacy security detection."""
    return DetectorPhase("Advocacy security", phase_advocacy_security)


__all__ = [
    "detector_phase_advocacy_language",
    "detector_phase_advocacy_security",
    "phase_advocacy_language",
    "phase_advocacy_security",
]
