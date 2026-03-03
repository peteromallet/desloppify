"""Go detector phase runners.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.languages._framework.base.shared_phases import (
    run_coupling_phase,
    run_structural_phase,
)
from desloppify.languages._framework.finding_factories import (
    make_smell_findings,
    make_unused_findings,
)
from desloppify.languages._framework.runtime import LangRun
from desloppify.languages.go.detectors.deps import build_dep_graph
from desloppify.languages.go.detectors.gods import GO_GOD_RULES, extract_go_structs
from desloppify.languages.go.detectors.smells import detect_smells
from desloppify.languages.go.detectors.unused import detect_unused
from desloppify.core.output_api import log
from desloppify.engine.policy.zones import adjust_potential
from desloppify.state import Finding

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
    """Run structural detectors (large/complexity/flat directories/god structs)."""
    return run_structural_phase(
        path,
        lang,
        complexity_signals=GO_COMPLEXITY_SIGNALS,
        log_fn=log,
        god_rules=GO_GOD_RULES,
        god_extractor_fn=extract_go_structs,
    )


def _phase_smells(path: Path, lang: LangRun) -> tuple[list[Finding], dict[str, int]]:
    """Run Go code smell detection."""
    entries, total_files = detect_smells(path)
    return make_smell_findings(entries, log), {
        "smells": adjust_potential(lang.zone_map, total_files),
    }


def _phase_unused(path: Path, lang: LangRun) -> tuple[list[Finding], dict[str, int]]:
    """Run Go unused symbol detection via staticcheck."""
    entries, total_files, _available = detect_unused(path)
    return make_unused_findings(entries, log), {
        "unused": adjust_potential(lang.zone_map, total_files),
    }


def _phase_coupling(path: Path, lang: LangRun) -> tuple[list[dict], dict[str, int]]:
    """Run coupling/cycles/orphaned detectors against the Go dep graph."""
    return run_coupling_phase(
        path,
        lang,
        build_dep_graph_fn=build_dep_graph,
        log_fn=log,
    )
