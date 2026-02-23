"""Go detector phase runners.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.languages._framework.base.shared_phases import run_structural_phase
from desloppify.languages._framework.runtime import LangRun
from desloppify.utils import log

GO_COMPLEXITY_SIGNALS = [
    ComplexitySignal(
        "if/else branches",
        r"\b(?:if|else\s+if|else)\b",
        weight=1,
        threshold=25,
    ),
    ComplexitySignal(
        "switch/case",
        r"\b(?:switch|case)\b",
        weight=1,
        threshold=10,
    ),
    ComplexitySignal(
        "select blocks",
        r"\bselect\b",
        weight=2,
        threshold=5,
    ),
    ComplexitySignal(
        "for loops",
        r"\bfor\b",
        weight=1,
        threshold=15,
    ),
    ComplexitySignal(
        "goroutines",
        r"\bgo\s+\w+",
        weight=2,
        threshold=5,
    ),
    ComplexitySignal(
        "defer",
        r"\bdefer\b",
        weight=1,
        threshold=10,
    ),
    ComplexitySignal(
        "TODOs",
        r"(?m)//\s*(?:TODO|FIXME|HACK|XXX)",
        weight=2,
        threshold=0,
    ),
]


def _phase_structural(path: Path, lang: LangRun) -> tuple[list[dict], dict[str, int]]:
    """Run structural detectors (large/complexity/flat directories)."""
    return run_structural_phase(
        path,
        lang,
        complexity_signals=GO_COMPLEXITY_SIGNALS,
        log_fn=log,
    )
