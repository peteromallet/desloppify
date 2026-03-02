"""Canonical detector registry — single source of truth.

All detector metadata lives here. Other modules derive their views
(display order, CLI names, narrative tools, scoring validation) from this registry
instead of maintaining their own lists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

DISPLAY_ORDER = [
    "logs",
    "unused",
    "exports",
    "deprecated",
    "structural",
    "props",
    "single_use",
    "coupling",
    "cycles",
    "orphaned",
    "uncalled_functions",
    "facade",
    "patterns",
    "naming",
    "smells",
    "react",
    "dupes",
    "stale_exclude",
    "dict_keys",
    "flat_dirs",
    "signature",
    "global_mutable_config",
    "private_imports",
    "layer_violation",
    "test_coverage",
    "security",
    "concerns",
    "review",
    "subjective_review",
]


@dataclass(frozen=True)
class DetectorMeta:
    name: str
    display: str  # Human-readable for terminal display
    dimension: str  # Scoring dimension name
    action_type: str  # "auto_fix" | "refactor" | "reorganize" | "manual_fix"
    guidance: str  # Narrative coaching text
    fixers: tuple[str, ...] = ()
    tool: str = ""  # "move" or empty
    structural: bool = False  # Merges under "structural" in display
    needs_judgment: bool = False  # Findings need LLM design judgment (vs clear-cut fixes)


DETECTORS: dict[str, DetectorMeta] = {
    # ── Auto-fixable ──────────────────────────────────────
    "unused": DetectorMeta(
        "unused",
        "unused",
        "Code quality",
        "auto_fix",
        "remove unused imports and variables",
        fixers=("unused-imports", "unused-vars", "unused-params"),
    ),
    "logs": DetectorMeta(
        "logs",
        "logs",
        "Code quality",
        "auto_fix",
        "remove debug logs",
        fixers=("debug-logs",),
    ),
    "exports": DetectorMeta(
        "exports",
        "exports",
        "Code quality",
        "manual_fix",
        "run `knip --fix` to remove dead exports",
    ),
    "smells": DetectorMeta(
        "smells",
        "smells",
        "Code quality",
        "auto_fix",
        "fix code smells — dead useEffect, empty if chains",
        fixers=("dead-useeffect", "empty-if-chain"),
        needs_judgment=True,
    ),
    # ── Reorganize (move tool) ────────────────────────────
    "orphaned": DetectorMeta(
        "orphaned",
        "orphaned",
        "Code quality",
        "reorganize",
        "delete dead files or relocate with `desloppify move`",
        tool="move",
        needs_judgment=True,
    ),
    "uncalled_functions": DetectorMeta(
        "uncalled_functions",
        "uncalled functions",
        "Code quality",
        "refactor",
        "remove dead functions or document why they're retained",
        needs_judgment=True,
    ),
    "flat_dirs": DetectorMeta(
        "flat_dirs",
        "flat dirs",
        "Code quality",
        "reorganize",
        "create subdirectories and use `desloppify move`",
        tool="move",
        needs_judgment=True,
    ),
    "naming": DetectorMeta(
        "naming",
        "naming",
        "Code quality",
        "reorganize",
        "rename files with `desloppify move` to fix conventions",
        tool="move",
        needs_judgment=True,
    ),
    "single_use": DetectorMeta(
        "single_use",
        "single_use",
        "Code quality",
        "reorganize",
        "inline or relocate with `desloppify move`",
        tool="move",
        needs_judgment=True,
    ),
    "coupling": DetectorMeta(
        "coupling",
        "coupling",
        "Code quality",
        "reorganize",
        "fix boundary violations with `desloppify move`",
        tool="move",
        needs_judgment=True,
    ),
    "cycles": DetectorMeta(
        "cycles",
        "cycles",
        "Security",
        "reorganize",
        "break cycles by extracting shared code or using `desloppify move`",
        tool="move",
        needs_judgment=True,
    ),
    "facade": DetectorMeta(
        "facade",
        "facade",
        "Code quality",
        "reorganize",
        "flatten re-export facades or consolidate barrel files",
        tool="move",
        needs_judgment=True,
    ),
    # ── Refactor ──────────────────────────────────────────
    "structural": DetectorMeta(
        "structural",
        "structural",
        "File health",
        "refactor",
        "decompose large files — extract logic into focused modules",
        needs_judgment=True,
    ),
    "props": DetectorMeta(
        "props",
        "props",
        "Code quality",
        "refactor",
        "split bloated components, extract sub-components",
        needs_judgment=True,
    ),
    "react": DetectorMeta(
        "react",
        "react",
        "Code quality",
        "refactor",
        "refactor React antipatterns (state sync, provider nesting, hook bloat)",
        needs_judgment=True,
    ),
    "dupes": DetectorMeta(
        "dupes",
        "dupes",
        "Duplication",
        "refactor",
        "extract shared utility or consolidate duplicates",
        needs_judgment=True,
    ),
    "patterns": DetectorMeta(
        "patterns",
        "patterns",
        "Code quality",
        "refactor",
        "align to single pattern across the codebase",
        needs_judgment=True,
    ),
    "dict_keys": DetectorMeta(
        "dict_keys",
        "dict keys",
        "Code quality",
        "refactor",
        "fix dict key mismatches — dead writes are likely dead code, "
        "schema drift suggests a typo or missed rename",
        needs_judgment=True,
    ),
    "test_coverage": DetectorMeta(
        "test_coverage",
        "test coverage",
        "Test health",
        "refactor",
        "add tests for untested production modules — prioritize by import count",
    ),
    "signature": DetectorMeta(
        "signature",
        "signature",
        "Code quality",
        "refactor",
        "consolidate inconsistent function signatures",
        needs_judgment=True,
    ),
    "global_mutable_config": DetectorMeta(
        "global_mutable_config",
        "global mutable config",
        "Code quality",
        "manual_fix",
        "refactor module-level mutable state — use explicit init functions or dependency injection",
        needs_judgment=True,
    ),
    "private_imports": DetectorMeta(
        "private_imports",
        "private imports",
        "Code quality",
        "manual_fix",
        "stop importing private symbols across module boundaries",
        needs_judgment=True,
    ),
    "layer_violation": DetectorMeta(
        "layer_violation",
        "layer violation",
        "Code quality",
        "manual_fix",
        "fix architectural layer violations — move shared code to the correct layer",
        needs_judgment=True,
    ),
    "responsibility_cohesion": DetectorMeta(
        "responsibility_cohesion",
        "responsibility cohesion",
        "Code quality",
        "refactor",
        "split modules with too many responsibilities — extract focused sub-modules",
        needs_judgment=True,
    ),
    "boilerplate_duplication": DetectorMeta(
        "boilerplate_duplication",
        "boilerplate duplication",
        "Duplication",
        "refactor",
        "extract shared boilerplate into reusable helpers or base classes",
        needs_judgment=True,
    ),
    "stale_wontfix": DetectorMeta(
        "stale_wontfix",
        "stale wontfix",
        "Code quality",
        "manual_fix",
        "re-evaluate old wontfix decisions — fix, document, or escalate",
    ),
    "concerns": DetectorMeta(
        "concerns",
        "design concerns",
        "Design coherence",
        "refactor",
        "address design concerns confirmed by subjective evaluation",
    ),
    # ── Manual fix ────────────────────────────────────────
    "deprecated": DetectorMeta(
        "deprecated",
        "deprecated",
        "Code quality",
        "manual_fix",
        "remove deprecated symbols or migrate callers",
    ),
    "stale_exclude": DetectorMeta(
        "stale_exclude",
        "stale exclude",
        "Code quality",
        "manual_fix",
        "remove stale exclusion or verify it's still needed",
    ),
    "security": DetectorMeta(
        "security",
        "security",
        "Security",
        "manual_fix",
        "review and fix security findings — prioritize by severity",
    ),
    # ── Subjective review ────────────────────────────────────
    "review": DetectorMeta(
        "review",
        "design review",
        "Test health",
        "refactor",
        "address design quality findings from AI code review",
    ),
    "subjective_review": DetectorMeta(
        "subjective_review",
        "subjective review",
        "Test health",
        "manual_fix",
        "run `desloppify review --prepare` to evaluate files against quality dimensions",
    ),
}

_DISPLAY_ORDER = list(DISPLAY_ORDER)

JUDGMENT_DETECTORS: frozenset[str] = frozenset(
    name for name, meta in DETECTORS.items() if meta.needs_judgment
)
_BASE_DETECTORS: dict[str, DetectorMeta] = dict(DETECTORS)
_BASE_DISPLAY_ORDER: list[str] = list(_DISPLAY_ORDER)
_BASE_JUDGMENT_DETECTORS: frozenset[str] = frozenset(JUDGMENT_DETECTORS)

_on_register_callbacks: list[Callable[[], None]] = []


def on_detector_registered(callback: Callable[[], None]) -> None:
    """Register a callback invoked after register_detector(). No-arg."""
    _on_register_callbacks.append(callback)


def register_detector(meta: DetectorMeta) -> None:
    """Register a detector at runtime (used by generic plugins)."""
    global JUDGMENT_DETECTORS
    DETECTORS[meta.name] = meta
    if meta.name not in _DISPLAY_ORDER:
        _DISPLAY_ORDER.append(meta.name)
    JUDGMENT_DETECTORS = frozenset(
        name for name, m in DETECTORS.items() if m.needs_judgment
    )
    for cb in _on_register_callbacks:
        cb()


def reset_registered_detectors() -> None:
    """Reset runtime-added detector registrations to built-in defaults."""
    global JUDGMENT_DETECTORS
    DETECTORS.clear()
    DETECTORS.update(_BASE_DETECTORS)
    _DISPLAY_ORDER.clear()
    _DISPLAY_ORDER.extend(_BASE_DISPLAY_ORDER)
    JUDGMENT_DETECTORS = _BASE_JUDGMENT_DETECTORS
    for cb in _on_register_callbacks:
        cb()


def detector_names() -> list[str]:
    """All registered detector names, sorted."""
    return sorted(DETECTORS.keys())


def display_order() -> list[str]:
    """Canonical display order for terminal output."""
    return list(_DISPLAY_ORDER)


_ACTION_PRIORITY = {"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3}
_ACTION_LABELS = {
    "auto_fix": "fix",
    "reorganize": "move",
    "refactor": "refactor",
    "manual_fix": "manual",
}


def dimension_action_type(dim_name: str) -> str:
    """Return a compact action type label for a dimension based on its detectors."""
    best = "manual"
    best_pri = 99
    for d in DETECTORS.values():
        if d.dimension == dim_name:
            pri = _ACTION_PRIORITY.get(d.action_type, 99)
            if pri < best_pri:
                best_pri = pri
                best = d.action_type
    return _ACTION_LABELS.get(best, "manual")


def detector_tools() -> dict[str, dict]:
    """Build detector tool metadata keyed by detector name."""
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
