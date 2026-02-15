"""Canonical detector registry — single source of truth.

All detector metadata lives here. Other modules derive their views
(display order, CLI names, narrative tools, scoring validation) from this registry
instead of maintaining their own lists.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectorMeta:
    name: str
    display: str                    # Human-readable for terminal display
    dimension: str                  # Scoring dimension name
    action_type: str                # "auto_fix" | "refactor" | "reorganize" | "manual_fix"
    guidance: str                   # Narrative coaching text
    fixers: tuple[str, ...] = ()
    tool: str = ""                  # "move" or empty
    structural: bool = False        # Merges under "structural" in display


DETECTORS: dict[str, DetectorMeta] = {
    # ── Auto-fixable ──────────────────────────────────────
    "unused": DetectorMeta(
        "unused", "unused", "Code quality", "auto_fix",
        "remove unused imports and variables",
        fixers=("unused-imports", "unused-vars", "unused-params")),
    "logs": DetectorMeta(
        "logs", "logs", "Code quality", "auto_fix",
        "remove debug logs",
        fixers=("debug-logs",)),
    "exports": DetectorMeta(
        "exports", "exports", "Code quality", "auto_fix",
        "remove dead exports",
        fixers=("dead-exports",)),
    "smells": DetectorMeta(
        "smells", "smells", "Code quality", "auto_fix",
        "fix code smells — dead useEffect, empty if chains",
        fixers=("dead-useeffect", "empty-if-chain")),
    # ── Reorganize (move tool) ────────────────────────────
    "orphaned": DetectorMeta(
        "orphaned", "orphaned", "Code quality", "reorganize",
        "delete dead files or relocate with `desloppify move`",
        tool="move"),
    "flat_dirs": DetectorMeta(
        "flat_dirs", "flat dirs", "Code quality", "reorganize",
        "create subdirectories and use `desloppify move`",
        tool="move"),
    "naming": DetectorMeta(
        "naming", "naming", "Code quality", "reorganize",
        "rename files with `desloppify move` to fix conventions",
        tool="move"),
    "single_use": DetectorMeta(
        "single_use", "single_use", "Code quality", "reorganize",
        "inline or relocate with `desloppify move`",
        tool="move"),
    "coupling": DetectorMeta(
        "coupling", "coupling", "Code quality", "reorganize",
        "fix boundary violations with `desloppify move`",
        tool="move"),
    "cycles": DetectorMeta(
        "cycles", "cycles", "Security", "reorganize",
        "break cycles by extracting shared code or using `desloppify move`",
        tool="move"),
    "facade": DetectorMeta(
        "facade", "facade", "Code quality", "reorganize",
        "flatten re-export facades or consolidate barrel files",
        tool="move"),
    # ── Refactor ──────────────────────────────────────────
    "structural": DetectorMeta(
        "structural", "structural", "File health", "refactor",
        "decompose large files — extract logic into focused modules"),
    "props": DetectorMeta(
        "props", "props", "Code quality", "refactor",
        "split bloated components, extract sub-components"),
    "react": DetectorMeta(
        "react", "react", "Code quality", "refactor",
        "refactor React antipatterns (state sync, provider nesting, hook bloat)"),
    "dupes": DetectorMeta(
        "dupes", "dupes", "Duplication", "refactor",
        "extract shared utility or consolidate duplicates"),
    "patterns": DetectorMeta(
        "patterns", "patterns", "Code quality", "refactor",
        "align to single pattern across the codebase"),
    "dict_keys": DetectorMeta(
        "dict_keys", "dict keys", "Code quality", "refactor",
        "fix dict key mismatches — dead writes are likely dead code, "
        "schema drift suggests a typo or missed rename"),
    "test_coverage": DetectorMeta(
        "test_coverage", "test coverage", "Test health", "refactor",
        "add tests for untested production modules — prioritize by import count"),
    "signature": DetectorMeta(
        "signature", "signature", "Code quality", "refactor",
        "consolidate inconsistent function signatures"),
    "global_mutable_config": DetectorMeta(
        "global_mutable_config", "global mutable config", "Code quality", "manual_fix",
        "refactor module-level mutable state — use explicit init functions or dependency injection"),
    "private_imports": DetectorMeta(
        "private_imports", "private imports", "Code quality", "manual_fix",
        "stop importing private symbols across module boundaries"),
    "layer_violation": DetectorMeta(
        "layer_violation", "layer violation", "Code quality", "manual_fix",
        "fix architectural layer violations — move shared code to the correct layer"),
    # ── Manual fix ────────────────────────────────────────
    "deprecated": DetectorMeta(
        "deprecated", "deprecated", "Code quality", "manual_fix",
        "remove deprecated symbols or migrate callers"),
    "stale_exclude": DetectorMeta(
        "stale_exclude", "stale exclude", "Code quality", "manual_fix",
        "remove stale exclusion or verify it's still needed"),
    "security": DetectorMeta(
        "security", "security", "Security", "manual_fix",
        "review and fix security findings — prioritize by severity"),
    # ── Subjective review ────────────────────────────────────
    "review": DetectorMeta(
        "review", "design review", "Test health", "refactor",
        "address design quality findings from AI code review"),
    "subjective_review": DetectorMeta(
        "subjective_review", "subjective review", "Test health", "manual_fix",
        "run `desloppify fix review` to evaluate files against quality dimensions"),
}

# ── Canonical display order for terminal output ──────────────

_DISPLAY_ORDER = [
    "logs", "unused", "exports", "deprecated", "structural", "props",
    "single_use", "coupling", "cycles", "orphaned", "facade", "patterns",
    "naming", "smells", "react", "dupes", "stale_exclude",
    "dict_keys", "flat_dirs", "signature", "global_mutable_config",
    "private_imports", "layer_violation",
    "test_coverage", "security", "review", "subjective_review",
]


def detector_names() -> list[str]:
    """All registered detector names, sorted."""
    return sorted(DETECTORS.keys())


def display_order() -> list[str]:
    """Canonical display order for terminal output."""
    return list(_DISPLAY_ORDER)


def dimension_action_type(dim_name: str) -> str:
    """Return a compact action type label for a dimension based on its detectors.

    Priority: auto_fix > reorganize > refactor > manual_fix.
    Returns the most actionable type present.
    """
    _PRIORITY = {"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3}
    best = "manual"
    best_pri = 99
    for d in DETECTORS.values():
        if d.dimension == dim_name:
            pri = _PRIORITY.get(d.action_type, 99)
            if pri < best_pri:
                best_pri = pri
                best = d.action_type
    _LABELS = {"auto_fix": "fix", "reorganize": "move", "refactor": "refactor", "manual_fix": "manual"}
    return _LABELS.get(best, "manual")


def detector_tools() -> dict[str, dict]:
    """DETECTOR_TOOLS-shaped dict for narrative.py backward compat."""
    result = {}
    for name, d in DETECTORS.items():
        entry: dict = {
            "fixers": list(d.fixers),
            "action_type": d.action_type,
        }
        if d.tool:
            entry["tool"] = d.tool
        if d.guidance:
            entry["guidance"] = d.guidance
        result[name] = entry
    return result
