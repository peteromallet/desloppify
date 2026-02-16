"""Phase detection and milestone computation."""

from __future__ import annotations


def _history_strict(entry: dict) -> float | None:
    """Strict score from history entry (supports old/new keys)."""
    return entry.get("strict_score", entry.get("objective_strict"))


def _detect_phase(history: list[dict], strict_score: float | None) -> str:
    """Detect project phase from scan history trajectory."""
    if not history:
        return "first_scan"

    if len(history) == 1:
        return "first_scan"

    strict = strict_score
    if strict is None and history:
        strict = _history_strict(history[-1])

    # Check regression: strict dropped from previous scan
    if len(history) >= 2:
        prev = _history_strict(history[-2])
        curr = _history_strict(history[-1])
        if prev is not None and curr is not None and curr < prev - 0.5:
            return "regression"

    # Check stagnation: strict unchanged ±0.5 for 3+ scans
    if len(history) >= 3:
        recent = [_history_strict(h) for h in history[-3:]]
        if all(r is not None for r in recent):
            spread = max(recent) - min(recent)
            if spread <= 0.5:
                return "stagnation"

    # Early momentum: scans 2-5 with score rising — check BEFORE score thresholds
    # so early projects get motivational framing even if score is already high
    if len(history) <= 5 and len(history) >= 2:
        first = _history_strict(history[0])
        last = _history_strict(history[-1])
        if first is not None and last is not None and last > first:
            return "early_momentum"

    if strict is not None:
        if strict > 93:
            return "maintenance"
        if strict > 80:
            return "refinement"

    return "middle_grind"


def _detect_milestone(state: dict, diff: dict | None,
                      history: list[dict]) -> str | None:
    """Detect notable milestones worth celebrating."""
    from ..state import get_strict_score
    strict_score = get_strict_score(state)
    stats = state.get("stats", {})

    # Check T1 clear
    by_tier = stats.get("by_tier", {})
    t1_open = by_tier.get("1", {}).get("open", 0)
    t2_open = by_tier.get("2", {}).get("open", 0)

    if len(history) >= 2:
        prev_strict = _history_strict(history[-2])
        if prev_strict is not None and strict_score is not None:
            # Crossed 90
            if prev_strict < 90 and strict_score >= 90:
                return "Crossed 90% strict!"
            # Crossed 80
            if prev_strict < 80 and strict_score >= 80:
                return "Crossed 80% strict!"

    if t1_open == 0 and t2_open == 0:
        # Check if there were T1/T2 items before
        total_t1 = sum(by_tier.get("1", {}).values())
        total_t2 = sum(by_tier.get("2", {}).values())
        if total_t1 + total_t2 > 0:
            return "All T1 and T2 items cleared!"

    if t1_open == 0:
        total_t1 = sum(by_tier.get("1", {}).values())
        if total_t1 > 0:
            return "All T1 items cleared!"

    if stats.get("open", 0) == 0 and stats.get("total", 0) > 0:
        return "Zero open findings!"

    return None
