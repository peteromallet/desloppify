"""Per-detector scoring calculations."""

from __future__ import annotations

from dataclasses import dataclass, field

from desloppify.engine._scoring.policy.core import (
    CONFIDENCE_WEIGHTS,
    FAILURE_STATUSES_BY_MODE,
    HOLISTIC_MULTIPLIER,
    SCORING_MODES,
    ScoreMode,
    detector_policy,
)
from desloppify.engine._state.schema import Finding

# Tiered file-count cap thresholds for non-LOC file-based detectors.
# Controls how many findings per file contribute to the weighted failure sum.
_FILE_CAP_HIGH_THRESHOLD = 6     # findings in file for high cap
_FILE_CAP_MID_THRESHOLD = 3      # findings in file for mid cap
_FILE_CAP_HIGH = 2.0             # cap value at high concentration
_FILE_CAP_MID = 1.5              # cap value at mid concentration
_FILE_CAP_LOW = 1.0              # cap value at low concentration (1-2 findings)


def merge_potentials(potentials_by_lang: dict[str, dict[str, int]]) -> dict[str, int]:
    """Sum potentials across languages per detector."""
    merged: dict[str, int] = {}
    for lang_potentials in potentials_by_lang.values():
        for detector, count in lang_potentials.items():
            merged[detector] = merged.get(detector, 0) + count
    return merged


def _iter_scoring_candidates(
    detector: str,
    findings: dict[str, Finding],
    excluded_zones: frozenset[str],
):
    """Yield in-scope findings for a detector (zone-filtered)."""
    for finding in findings.values():
        if finding.get("suppressed"):
            continue
        if finding.get("detector") != detector:
            continue
        if finding.get("zone", "production") in excluded_zones:
            continue
        yield finding


def _finding_weight(finding: Finding, *, use_loc_weight: bool) -> float:
    """Compute the scoring weight for a single finding."""
    if use_loc_weight:
        return finding.get("detail", {}).get("loc_weight", 1.0)
    return CONFIDENCE_WEIGHTS.get(finding.get("confidence", "medium"), 0.7)


def _file_count_cap(findings_in_file: int) -> float:
    """Tiered cap for non-LOC file-based detectors.

    Keeps file-count denominator semantics while preserving concentration signal:
    1-2 findings => _FILE_CAP_LOW, 3-5 => _FILE_CAP_MID, 6+ => _FILE_CAP_HIGH.
    """
    if findings_in_file >= _FILE_CAP_HIGH_THRESHOLD:
        return _FILE_CAP_HIGH
    if findings_in_file >= _FILE_CAP_MID_THRESHOLD:
        return _FILE_CAP_MID
    return _FILE_CAP_LOW


@dataclass
class _ModeAccum:
    """Per-mode accumulator for file-based detector scoring."""

    by_file: dict[str, float] = field(default_factory=dict)
    by_file_count: dict[str, int] = field(default_factory=dict)
    file_cap: dict[str, float] = field(default_factory=dict)
    holistic_sum: float = 0.0
    issue_count: int = 0


def _file_based_failures_by_mode(
    detector: str,
    findings: dict[str, Finding],
    policy,
) -> dict[ScoreMode, tuple[int, float]]:
    """Accumulate weighted failures by score mode for file-based detectors."""
    accum: dict[ScoreMode, _ModeAccum] = {mode: _ModeAccum() for mode in SCORING_MODES}

    for finding in _iter_scoring_candidates(detector, findings, policy.excluded_zones):
        status = finding.get("status", "open")
        holistic = finding.get("file") == "." and finding.get("detail", {}).get(
            "holistic"
        )

        for mode in SCORING_MODES:
            if status not in FAILURE_STATUSES_BY_MODE[mode]:
                continue

            if holistic:
                accum[mode].holistic_sum += (
                    _finding_weight(finding, use_loc_weight=False) * HOLISTIC_MULTIPLIER
                )
                accum[mode].issue_count += 1
                continue

            weight = _finding_weight(finding, use_loc_weight=policy.use_loc_weight)
            file_key = finding.get("file", "")
            a = accum[mode]
            a.by_file[file_key] = a.by_file.get(file_key, 0.0) + weight
            a.by_file_count[file_key] = a.by_file_count.get(file_key, 0) + 1
            if policy.use_loc_weight and file_key not in a.file_cap:
                a.file_cap[file_key] = weight
            a.issue_count += 1

    out: dict[ScoreMode, tuple[int, float]] = {}
    for mode in SCORING_MODES:
        a = accum[mode]
        if policy.use_loc_weight:
            weighted = sum(
                min(weighted_sum, a.file_cap.get(file_key, weighted_sum))
                for file_key, weighted_sum in a.by_file.items()
            )
        else:
            weighted = sum(
                min(weighted_sum, _file_count_cap(a.by_file_count.get(file_key, 0)))
                for file_key, weighted_sum in a.by_file.items()
            )
        out[mode] = (a.issue_count, weighted + a.holistic_sum)
    return out


def detector_stats_by_mode(
    detector: str,
    findings: dict[str, Finding],
    potential: int,
) -> dict[ScoreMode, tuple[float, int, float]]:
    """Compute (pass_rate, issue_count, weighted_failures) for each score mode."""
    if potential <= 0:
        return {mode: (1.0, 0, 0.0) for mode in SCORING_MODES}

    # Review and concern findings are scored via subjective assessments only —
    # exclude them from the detection-side scoring pipeline so resolving these
    # findings never changes the score directly.
    if detector in ("review", "concerns"):
        return {mode: (1.0, 0, 0.0) for mode in SCORING_MODES}

    policy = detector_policy(detector)

    if policy.file_based:
        mode_failures = _file_based_failures_by_mode(detector, findings, policy)
    else:
        issue_count: dict[ScoreMode, int] = {mode: 0 for mode in SCORING_MODES}
        weighted_failures: dict[ScoreMode, float] = {
            mode: 0.0 for mode in SCORING_MODES
        }

        for finding in _iter_scoring_candidates(
            detector, findings, policy.excluded_zones
        ):
            status = finding.get("status", "open")
            weight = _finding_weight(finding, use_loc_weight=False)
            for mode in SCORING_MODES:
                if status not in FAILURE_STATUSES_BY_MODE[mode]:
                    continue
                issue_count[mode] += 1
                weighted_failures[mode] += weight

        mode_failures = {
            mode: (issue_count[mode], weighted_failures[mode]) for mode in SCORING_MODES
        }

    out: dict[ScoreMode, tuple[float, int, float]] = {}
    for mode in SCORING_MODES:
        issues, weighted = mode_failures[mode]
        pass_rate = max(0.0, (potential - weighted) / potential)
        out[mode] = (pass_rate, issues, weighted)
    return out


def detector_pass_rate(
    detector: str,
    findings: dict[str, Finding],
    potential: int,
    *,
    strict: bool = False,
) -> tuple[float, int, float]:
    """Pass rate for one detector.

    Returns (pass_rate, issue_count, weighted_failures).
    Zero potential -> (1.0, 0, 0.0).
    """
    mode: ScoreMode = "strict" if strict else "lenient"
    return detector_stats_by_mode(detector, findings, potential)[mode]


__all__ = [
    "detector_pass_rate",
    "detector_stats_by_mode",
    "merge_potentials",
]
