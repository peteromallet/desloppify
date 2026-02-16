"""TypeScript/React language configuration for desloppify."""

from __future__ import annotations

from pathlib import Path

from .. import register_lang
from ..base import (BoundaryRule, DetectorPhase, FixerConfig, LangConfig,
                    detector_phase_security, detector_phase_test_coverage,
                    shared_subjective_duplicates_tail)
from ...utils import find_ts_files, get_area
from ...zones import ZoneRule, Zone, COMMON_ZONE_RULES
from .phases import (TS_COMPLEXITY_SIGNALS, TS_GOD_RULES,  # noqa: F401 — re-exported for commands.py
                     TS_SKIP_NAMES, TS_SKIP_DIRS,
                     _phase_logs, _phase_unused, _phase_exports,
                     _phase_deprecated, _phase_structural,
                     _phase_coupling, _phase_smells)
from .review import (
    REVIEW_GUIDANCE as TS_REVIEW_GUIDANCE,
    MIGRATION_PATTERN_PAIRS as TS_MIGRATION_PATTERN_PAIRS,
    MIGRATION_MIXED_EXTENSIONS as TS_MIGRATION_MIXED_EXTENSIONS,
    LOW_VALUE_PATTERN as TS_LOW_VALUE_PATTERN,
    module_patterns as ts_review_module_patterns,
    api_surface as ts_review_api_surface,
)


# ── Zone classification rules (order matters — first match wins) ──

TS_ZONE_RULES = [
    ZoneRule(Zone.GENERATED, [".d.ts", "/migrations/"]),
    ZoneRule(Zone.TEST, ["/__tests__/", ".test.", ".spec.", ".stories.",
                         "/__mocks__/", "setupTests."]),
    ZoneRule(Zone.CONFIG, ["vite.config", "tailwind.config", "postcss.config",
                           "tsconfig", "eslint", "prettier", "jest.config",
                           "vitest.config", "next.config", "webpack.config"]),
] + COMMON_ZONE_RULES


def _get_ts_fixers() -> dict[str, FixerConfig]:
    """Build the TypeScript fixer registry (lazy-loaded).

    Detection and fix functions use lazy imports so detector modules
    aren't loaded until the fix command actually runs.
    """
    from ..base import FixResult

    def _det_unused(cat):
        def f(path):
            from .detectors.unused import detect_unused
            return detect_unused(path, category=cat)[0]
        return f

    def _det_logs(path):
        from .detectors.logs import detect_logs
        return detect_logs(path)[0]

    def _det_exports(path):
        from .detectors.exports import detect_dead_exports
        return detect_dead_exports(path)[0]

    def _det_smell(smell_id):
        def f(path):
            from .detectors.smells import detect_smells
            return next((e.get("matches", []) for e in detect_smells(path)[0]
                         if e["id"] == smell_id), [])
        return f

    def _fix_vars(entries, *, dry_run=False):
        from .fixers import fix_unused_vars
        results, skip_reasons = fix_unused_vars(entries, dry_run=dry_run)
        return FixResult(entries=results, skip_reasons=skip_reasons)

    def _fix_logs(entries, *, dry_run=False):
        from .fixers import fix_debug_logs
        results = fix_debug_logs(entries, dry_run=dry_run)
        for r in results:
            r["removed"] = r.get("tags", r.get("removed", []))
        return results

    def _lazy_fix(name):
        def f(entries, **kw):
            from . import fixers as F
            return getattr(F, name)(entries, **kw)
        return f

    R, DV = "Removed", "Would remove"
    return {
        "unused-imports": FixerConfig(
            "unused imports", _det_unused("imports"),
            _lazy_fix("fix_unused_imports"), "unused", R, DV),
        "debug-logs": FixerConfig(
            "tagged debug logs", _det_logs, _fix_logs, "logs", R, DV),
        "dead-exports": FixerConfig(
            "dead exports", _det_exports,
            _lazy_fix("fix_dead_exports"), "exports",
            "De-exported", "Would de-export"),
        "unused-vars": FixerConfig(
            "unused vars", _det_unused("vars"), _fix_vars, "unused", R, DV),
        "unused-params": FixerConfig(
            "unused params", _det_unused("vars"),
            _lazy_fix("fix_unused_params"), "unused",
            "Prefixed", "Would prefix"),
        "dead-useeffect": FixerConfig(
            "dead useEffect calls", _det_smell("dead_useeffect"),
            _lazy_fix("fix_dead_useeffect"), "smells", R, DV),
        "empty-if-chain": FixerConfig(
            "empty if/else chains", _det_smell("empty_if_chain"),
            _lazy_fix("fix_empty_if_chain"), "smells", R, DV),
    }


# ── Build the config ──────────────────────────────────────


def _ts_build_dep_graph(path: Path) -> dict:
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _ts_extract_functions(path: Path) -> list:
    """Extract all TS functions for duplicate detection."""
    from .extractors import extract_ts_functions
    functions = []
    for filepath in find_ts_files(path):
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        functions.extend(extract_ts_functions(filepath))
    return functions


@register_lang("typescript")
class TypeScriptConfig(LangConfig):
    def detect_lang_security(self, files, zone_map):
        from .detectors.security import detect_ts_security
        return detect_ts_security(files, zone_map)

    def __init__(self):
        from .commands import get_detect_commands
        super().__init__(
            name="typescript",
            extensions=[".ts", ".tsx"],
            exclusions=["node_modules", ".d.ts"],
            default_src="src",
            build_dep_graph=_ts_build_dep_graph,
            entry_patterns=[
                "/pages/", "/main.tsx", "/main.ts", "/App.tsx",
                "vite.config", "tailwind.config", "postcss.config",
                ".d.ts", "/settings.ts", "/__tests__/", ".test.", ".spec.", ".stories.",
            ],
            barrel_names={"index.ts", "index.tsx"},
            phases=[
                DetectorPhase("Logs", _phase_logs),
                DetectorPhase("Unused (tsc)", _phase_unused),
                DetectorPhase("Dead exports", _phase_exports),
                DetectorPhase("Deprecated", _phase_deprecated),
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Coupling + single-use + patterns + naming", _phase_coupling),
                detector_phase_test_coverage(),
                DetectorPhase("Code smells", _phase_smells),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers=_get_ts_fixers(),
            get_area=get_area,
            detect_commands=get_detect_commands(),
            boundaries=[
                BoundaryRule("shared/", "tools/", "shared\u2192tools"),
            ],
            typecheck_cmd="npx tsc --noEmit",
            file_finder=find_ts_files,
            large_threshold=500,
            complexity_threshold=15,
            default_scan_profile="full",
            detect_markers=["package.json"],
            external_test_dirs=["tests", "test", "__tests__"],
            test_file_extensions=[".ts", ".tsx"],
            review_module_patterns_fn=ts_review_module_patterns,
            review_api_surface_fn=ts_review_api_surface,
            review_guidance=TS_REVIEW_GUIDANCE,
            review_low_value_pattern=TS_LOW_VALUE_PATTERN,
            holistic_review_dimensions=[
                "cross_module_architecture", "convention_outlier",
                "error_consistency", "abstraction_fitness",
                "api_surface_coherence", "authorization_consistency",
                "ai_generated_debt", "incomplete_migration",
            ],
            migration_pattern_pairs=TS_MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=TS_MIGRATION_MIXED_EXTENSIONS,
            extract_functions=_ts_extract_functions,
            zone_rules=TS_ZONE_RULES,
        )
