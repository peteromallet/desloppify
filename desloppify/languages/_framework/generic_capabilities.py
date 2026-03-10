"""Capability and stub helpers for generic language plugins."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.base.discovery.source import SourceDiscoveryOptions, find_source_files
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.languages._framework.base.types import LangConfig

# Shared phase labels — used by capability_report and langs command.
SHARED_PHASE_LABELS = frozenset(
    {
        "Security",
        "Subjective review",
        "Boilerplate duplication",
        "Duplicates",
        "Structural analysis",
        "Coupling + cycles + orphaned",
        "Test coverage",
        "AST smells",
        "Responsibility cohesion",
        "Unused imports",
        "Signature analysis",
    }
)


def make_file_finder(
    extensions: list[str], exclusions: list[str] | None = None
) -> Callable:
    """Return a file finder function for the given extensions."""
    excl = exclusions or []

    def finder(path: str | Path) -> list[str]:
        return find_source_files(
            path,
            extensions,
            SourceDiscoveryOptions(exclusions=tuple(excl or [])),
        )

    return finder


def empty_dep_graph(path: Path) -> dict[str, dict[str, Any]]:
    """Stub dep graph builder — generic plugins have no import parsing."""
    del path
    return {}


def noop_extract_functions(path: Path) -> list[FunctionInfo]:
    """Stub function extractor — generic plugins don't extract functions."""
    del path
    return []


def generic_zone_rules(extensions: list[str]) -> list[ZoneRule]:
    """Minimal zone rules: test dirs -> test, vendor/node_modules -> vendor, plus common."""
    del extensions
    return [
        ZoneRule(Zone.VENDOR, ["/node_modules/"]),
    ] + COMMON_ZONE_RULES


def capability_report(cfg: LangConfig) -> tuple[list[str], list[str]] | None:
    """Return (present, missing) capability lists. None for full plugins."""
    if cfg.integration_depth == "full":
        return None

    phase_labels = {p.label for p in cfg.phases}
    present: list[str] = []
    missing: list[str] = []

    def check(condition: bool, label: str) -> None:
        (present if condition else missing).append(label)

    tool_phases = [p.label for p in cfg.phases if p.label not in SHARED_PHASE_LABELS]
    check(
        bool(tool_phases),
        f"linting ({', '.join(tool_phases)})" if tool_phases else "linting",
    )
    check(bool(cfg.fixers), "auto-fix")
    check(cfg.build_dep_graph is not empty_dep_graph, "import analysis")
    check(cfg.extract_functions is not noop_extract_functions, "function extraction")
    check("Security" in phase_labels, "security scan")
    check("Boilerplate duplication" in phase_labels, "boilerplate detection")
    check("Subjective review" in phase_labels, "design review")

    return present, missing


__all__ = [
    "SHARED_PHASE_LABELS",
    "capability_report",
    "empty_dep_graph",
    "generic_zone_rules",
    "make_file_finder",
    "noop_extract_functions",
]
