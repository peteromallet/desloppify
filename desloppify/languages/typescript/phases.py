"""TypeScript detector phase runners."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages.typescript.phases_basic import (
    phase_deprecated,
    phase_exports,
    phase_logs,
    phase_unused,
)
from desloppify.languages.typescript.phases_config import (
    TS_COMPLEXITY_SIGNALS,
    TS_GOD_RULES,
    TS_SKIP_DIRS,
    TS_SKIP_NAMES,
)
from desloppify.languages.typescript.phases_coupling import (
    detect_coupling_violations,
    detect_cross_tool_imports,
    detect_cycles_and_orphans,
    detect_facades,
    detect_naming_inconsistencies,
    detect_pattern_anomalies,
    detect_single_use,
    make_boundary_issues,
    orphaned_detector_mod,
    phase_coupling,
)
from desloppify.languages.typescript.phases_smells import phase_smells
from desloppify.languages.typescript.phases_structural import (
    _detect_flat_dirs,
    _detect_passthrough,
    _detect_props_bloat,
    _detect_structural_signals,
    phase_structural,
)
from desloppify.state import Issue


__all__ = [
    "TS_COMPLEXITY_SIGNALS",
    "TS_GOD_RULES",
    "TS_SKIP_DIRS",
    "TS_SKIP_NAMES",
    "detect_coupling_violations",
    "detect_cross_tool_imports",
    "detect_cycles_and_orphans",
    "detect_facades",
    "detect_naming_inconsistencies",
    "detect_pattern_anomalies",
    "detect_single_use",
    "_detect_flat_dirs",
    "_detect_passthrough",
    "_detect_props_bloat",
    "_detect_structural_signals",
    "make_boundary_issues",
    "orphaned_detector_mod",
    "phase_coupling",
    "phase_deprecated",
    "phase_exports",
    "phase_logs",
    "phase_smells",
    "phase_structural",
    "phase_unused",
]
