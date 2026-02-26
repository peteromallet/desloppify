"""Dart detector phase runners."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.languages._framework.base.shared_phases import (
    run_coupling_phase,
    run_structural_phase,
)
from desloppify.languages._framework.runtime import LangRun
from desloppify.languages.dart.detectors.deps import build_dep_graph
from desloppify.core.output_api import log

DART_COMPLEXITY_SIGNALS = [
    ComplexitySignal(
        "imports",
        r"(?m)^\s*(?:import|export|part)\s+['\"]",
        weight=1,
        threshold=20,
    ),
    ComplexitySignal(
        "TODOs",
        r"(?m)//\s*(?:TODO|FIXME|HACK|XXX)",
        weight=2,
        threshold=0,
    ),
    ComplexitySignal(
        "control flow",
        r"\b(?:if|else\s+if|switch|for|while|catch)\b",
        weight=1,
        threshold=25,
    ),
    ComplexitySignal(
        "classes",
        r"(?m)^\s*(?:abstract\s+)?class\s+\w+",
        weight=2,
        threshold=5,
    ),
]


def _phase_structural(path: Path, lang: LangRun) -> tuple[list[dict], dict[str, int]]:
    """Run structural detectors (large/complexity/flat directories)."""
    return run_structural_phase(
        path,
        lang,
        complexity_signals=DART_COMPLEXITY_SIGNALS,
        log_fn=log,
    )


def _phase_coupling(path: Path, lang: LangRun) -> tuple[list[dict], dict[str, int]]:
    """Run coupling-oriented detectors against the Dart import graph."""
    return run_coupling_phase(
        path,
        lang,
        build_dep_graph_fn=build_dep_graph,
        log_fn=log,
    )
