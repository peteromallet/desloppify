"""Per-detector scoring calculations."""

from __future__ import annotations

from desloppify.engine.scoring_internal.policy.core import (
    CONFIDENCE_WEIGHTS,
    FAILURE_STATUSES_BY_MODE,
    HOLISTIC_MULTIPLIER,
    SCORING_MODES,
    ScoreMode,
    detector_policy,
)


def merge_potentials(potentials_by_lang: dict) -> dict[str, int]:
    """Sum potentials across languages per detector."""
    merged: dict[str, int] = {}
    for lang_potentials in potentials_by_lang.values():
        for detector, count in lang_potentials.items():
            merged[detector] = merged.get(detector, 0) + count
    return merged


def _iter_scoring_candidates(
    detector: str,
    findings: dict,
    excluded_zones: frozenset[str],
):
    """Yield in-scope findings for a detector (zone-filtered)."""
    for finding in findings.values():
        if finding.get("detector") != detector:
            continue
        if finding.get("zone", "production") in excluded_zones:
            continue
        yield finding


def _finding_weight(finding: dict, *, use_loc_weight: bool) -> float:
    """Compute the scoring weight for a single finding."""
    if use_loc_weight:
        return finding.get("detail", {}).get("loc_weight", 1.0)
    return CONFIDENCE_WEIGHTS.get(finding.get("confidence", "medium"), 0.7)


def _file_count_cap(findings_in_file: int) -> float:
    """Tiered cap for non-LOC file-based detectors.

    Keeps file-count denominator semantics while preserving concentration signal:
    1-2 findings => 1.0, 3-5 findings => 1.5, 6+ findings => 2.0.
    """
    if findings_in_file >= 6:
        return 2.0
    if findings_in_file >= 3:
        return 1.5
    return 1.0


def _file_based_failures_by_mode(
    detector: str,
    findings: dict,
    policy,
) -> dict[ScoreMode, tuple[int, float]]:
    """Accumulate weighted failures by score mode for file-based detectors."""
    by_file: dict[ScoreMode, dict[str, float]] = {mode: {} for mode in SCORING_MODES}
    by_file_count: dict[ScoreMode, dict[str, int]] = {mode: {} for mode in SCORING_MODES}
    file_cap: dict[ScoreMode, dict[str, float]] = {mode: {} for mode in SCORING_MODES}
    holistic_sum: dict[ScoreMode, float] = {mode: 0.0 for mode in SCORING_MODES}
    issue_count: dict[ScoreMode, int] = {mode: 0 for mode in SCORING_MODES}

    for finding in _iter_scoring_candidates(detector, findings, policy.excluded_zones):
        status = finding.get("status", "open")
        holistic = finding.get("file") == "." and finding.get("detail", {}).get(
            "holistic"
        )

        for mode in SCORING_MODES:
            if status not in FAILURE_STATUSES_BY_MODE[mode]:
                continue

            if holistic:
                holistic_sum[mode] += (
                    _finding_weight(finding, use_loc_weight=False) * HOLISTIC_MULTIPLIER
                )
                issue_count[mode] += 1
                continue

            weight = _finding_weight(finding, use_loc_weight=policy.use_loc_weight)
            file_key = finding.get("file", "")
            by_file[mode][file_key] = by_file[mode].get(file_key, 0.0) + weight
            by_file_count[mode][file_key] = by_file_count[mode].get(file_key, 0) + 1
            if policy.use_loc_weight and file_key not in file_cap[mode]:
                file_cap[mode][file_key] = weight
            issue_count[mode] += 1

    out: dict[ScoreMode, tuple[int, float]] = {}
    for mode in SCORING_MODES:
        if policy.use_loc_weight:
            weighted = sum(
                min(weighted_sum, file_cap[mode].get(file_key, weighted_sum))
                for file_key, weighted_sum in by_file[mode].items()
            )
        else:
            weighted = sum(
                min(weighted_sum, _file_count_cap(by_file_count[mode].get(file_key, 0)))
                for file_key, weighted_sum in by_file[mode].items()
            )
        out[mode] = (issue_count[mode], weighted + holistic_sum[mode])
    return out


def detector_stats_by_mode(
    detector: str,
    findings: dict,
    potential: int,
) -> dict[ScoreMode, tuple[float, int, float]]:
    """Compute (pass_rate, issue_count, weighted_failures) for each score mode."""
    if potential <= 0:
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
    findings: dict,
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
