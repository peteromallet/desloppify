"""Passthrough/forwarding detection: shared classification algorithm.

Language-specific detection functions live in lang/typescript/extractors.py
and lang/python/extractors.py. This module provides the shared core that
classifies parameters as passthrough vs direct-use.
"""

import re
from typing import Callable


def classify_passthrough_tier(
    passthrough_count: int,
    ratio: float,
    *,
    has_spread: bool = False,
) -> tuple[int, str] | None:
    """Classify passthrough severity into (tier, confidence) or None to skip."""
    if passthrough_count >= 20 or ratio >= 0.8:
        return 4, "high"
    if passthrough_count >= 8 and ratio >= 0.5:
        return 3, "high" if ratio >= 0.7 else "medium"
    if has_spread and passthrough_count >= 4:
        return 3, "medium"
    return None


def classify_params(
    params: list[str],
    body: str,
    make_pattern: Callable[[str], str],
    occurrences_per_match: int = 2,
) -> tuple[list[str], list[str]]:
    """Classify params as passthrough vs direct-use.

    For each param, count total word-boundary occurrences vs passthrough
    pattern matches. If ALL occurrences are accounted for by passthrough
    patterns, it's passthrough.

    Args:
        params: Parameter names to classify.
        body: Function/component body text.
        make_pattern: Returns a regex that matches passthrough usage of a param name.
        occurrences_per_match: How many \\bname\\b occurrences each passthrough match accounts for.

    Returns:
        (passthrough_params, direct_params)
    """
    passthrough = []
    direct = []
    for name in params:
        total = len(re.findall(rf"\b{re.escape(name)}\b", body))
        if total == 0:
            # Unused param — not passthrough, not direct-use either.
            # Count as direct (it's destructured, just unused).
            direct.append(name)
            continue
        pt_matches = len(re.findall(make_pattern(name), body))
        pt_occurrences = pt_matches * occurrences_per_match
        if pt_occurrences >= total:
            passthrough.append(name)
        else:
            direct.append(name)
    return passthrough, direct
