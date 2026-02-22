"""Computed narrative context for LLM coaching and terminal headlines.

Pure functions that derive structured observations from state data.
No print statements — returns dicts that flow into command query payload writers.
"""

from __future__ import annotations

from desloppify.intelligence.narrative._constants import (
    DETECTOR_TOOLS,
    STRUCTURAL_MERGE,
)
from desloppify.intelligence.narrative.core import (
    NarrativeContext,
    NarrativeResult,
    compute_narrative,
)

__all__ = [
    "compute_narrative",
    "NarrativeContext",
    "NarrativeResult",
    "STRUCTURAL_MERGE",
    "DETECTOR_TOOLS",
]
