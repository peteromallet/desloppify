"""Phase runners for language plugin scaffolding."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors import complexity as complexity_detector_mod
from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine.policy.zones import adjust_potential
from desloppify.languages.framework.base.structural import (
    add_structural_signal,
    merge_structural_signals,
)
from desloppify.languages.framework.base.types import LangConfig
from desloppify.state import make_finding
from desloppify.utils import log

GO_COMPLEXITY_SIGNALS = [
    ComplexitySignal("if_branches", r"\bif\s+", weight=2, threshold=5),
    ComplexitySignal("else_branches", r"\belse\b", weight=1, threshold=3),
    ComplexitySignal("switch_cases", r"\bcase\s+", weight=1, threshold=5),
    ComplexitySignal("select_blocks", r"\bselect\s*\{", weight=2, threshold=2),
    ComplexitySignal("for_loops", r"\bfor\s+", weight=2, threshold=3),
    ComplexitySignal("goroutines", r"\bgo\s+", weight=2, threshold=4),
    ComplexitySignal("defers", r"\bdefer\s+", weight=1, threshold=3),
    ComplexitySignal("TODOs", r"//\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
]

def _phase_structural(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    """Detect structural complexity such as branch counts and deep nesting."""
    structural: dict[str, dict] = {}
    
    complexity_entries, file_count = complexity_detector_mod.detect_complexity(
        path,
        signals=GO_COMPLEXITY_SIGNALS,
        file_finder=lang.file_finder,
        threshold=lang.complexity_threshold,
    )
    for e in complexity_entries:
        add_structural_signal(
            structural,
            e["file"],
            f"complexity score {e['score']}",
            {"complexity_score": e["score"], "complexity_signals": e["signals"]},
        )
        lang.complexity_map[e["file"]] = e["score"]

    results = merge_structural_signals(structural, log)
    
    potentials = {
        "structural": adjust_potential(lang.zone_map, file_count),
    }
    return results, potentials
