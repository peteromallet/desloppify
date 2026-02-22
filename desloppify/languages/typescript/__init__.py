"""TypeScript/React language configuration for desloppify."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages._framework.treesitter.phases import make_cohesion_phase
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_signature,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.types import (
    BoundaryRule,
    DetectorPhase,
    FixerConfig,
    FixResult,
    LangConfig,
)
from desloppify.languages.typescript import commands as ts_commands_mod
from desloppify.languages.typescript import fixers as ts_fixers_mod
from desloppify.languages.typescript import test_coverage as ts_test_coverage_hooks
from desloppify.languages.typescript.detectors import deps as deps_detector_mod
from desloppify.languages.typescript.detectors import logs as logs_detector_mod
from desloppify.languages.typescript.detectors import smells as smells_detector_mod
from desloppify.languages.typescript.detectors import unused as unused_detector_mod
from desloppify.languages.typescript.detectors.security import detect_ts_security
from desloppify.languages.typescript.extractors import extract_ts_functions
from desloppify.languages.typescript.phases import (
    TS_COMPLEXITY_SIGNALS as TS_COMPLEXITY_SIGNALS,
)
from desloppify.languages.typescript.phases import TS_GOD_RULES as TS_GOD_RULES
from desloppify.languages.typescript.phases import TS_SKIP_DIRS as TS_SKIP_DIRS
from desloppify.languages.typescript.phases import TS_SKIP_NAMES as TS_SKIP_NAMES
from desloppify.languages.typescript.phases import (
    _phase_coupling,
    _phase_deprecated,
    _phase_exports,
    _phase_logs,
    _phase_smells,
    _phase_structural,
    _phase_unused,
)
from desloppify.languages.typescript.review import (
    HOLISTIC_REVIEW_DIMENSIONS as TS_HOLISTIC_REVIEW_DIMENSIONS,
)
from desloppify.languages.typescript.review import (
    LOW_VALUE_PATTERN as TS_LOW_VALUE_PATTERN,
)
from desloppify.languages.typescript.review import (
    MIGRATION_MIXED_EXTENSIONS as TS_MIGRATION_MIXED_EXTENSIONS,
)
from desloppify.languages.typescript.review import (
    MIGRATION_PATTERN_PAIRS as TS_MIGRATION_PATTERN_PAIRS,
)
from desloppify.languages.typescript.review import REVIEW_GUIDANCE as TS_REVIEW_GUIDANCE
from desloppify.languages.typescript.review import api_surface as ts_review_api_surface
from desloppify.languages.typescript.review import (
    module_patterns as ts_review_module_patterns,
)
from desloppify.core._internal.text_utils import get_area
from desloppify.file_discovery import find_ts_files

def _ts_treesitter_phases() -> list[DetectorPhase]:
    """Cherry-pick tree-sitter phases that complement TS's own detectors.

    TS already has its own smells and unused detection — only add cohesion
    which TS lacks.  (Signature analysis is added separately since it's
    backend-agnostic and doesn't require tree-sitter.)
    """
    from desloppify.languages._framework.treesitter import is_available

    if not is_available():
        return []

    from desloppify.languages._framework.treesitter._specs import TREESITTER_SPECS

    spec = TREESITTER_SPECS.get("typescript")
    if spec is None:
        return []

    return [
        make_cohesion_phase(spec),
    ]


_TS_TEST_COVERAGE_HOOKS = (
    ts_test_coverage_hooks.has_testable_logic,
    ts_test_coverage_hooks.resolve_import_spec,
    ts_test_coverage_hooks.map_test_to_source,
)


register_lang_hooks("typescript", test_coverage=ts_test_coverage_hooks)


# ── Zone classification rules (order matters — first match wins) ──

TS_ZONE_RULES = [
    ZoneRule(Zone.GENERATED, [".d.ts", "/migrations/"]),
    ZoneRule(
        Zone.TEST,
        ["/__tests__/", ".test.", ".spec.", ".stories.", "/__mocks__/", "setupTests."],
    ),
    ZoneRule(
        Zone.CONFIG,
        [
            "vite.config",
            "tailwind.config",
            "postcss.config",
            "tsconfig",
            "eslint",
            "prettier",
            "jest.config",
            "vitest.config",
            "next.config",
            "webpack.config",
        ],
    ),
] + COMMON_ZONE_RULES


def _get_ts_fixers() -> dict[str, FixerConfig]:
    """Build the TypeScript fixer registry (lazy-loaded).

    Detection and fix functions use lazy imports so detector modules
    aren't loaded until the fix command actually runs.
    """

    def _det_unused(cat):
        def f(path):
            return unused_detector_mod.detect_unused(path, category=cat)[0]

        return f

    def _det_logs(path):
        return logs_detector_mod.detect_logs(path)[0]

    def _det_smell(smell_id):
        def f(path):
            return next(
                (
                    e.get("matches", [])
                    for e in smells_detector_mod.detect_smells(path)[0]
                    if e["id"] == smell_id
                ),
                [],
            )

        return f

    def _fix_vars(entries, *, dry_run=False):
        results, skip_reasons = ts_fixers_mod.fix_unused_vars(entries, dry_run=dry_run)
        return FixResult(entries=results, skip_reasons=skip_reasons)

    def _fix_logs(entries, *, dry_run=False):
        results = ts_fixers_mod.fix_debug_logs(entries, dry_run=dry_run)
        for r in results:
            r["removed"] = r.get("tags", r.get("removed", []))
        return results

    def _lazy_fix(name):
        def f(entries, **kw):
            return getattr(ts_fixers_mod, name)(entries, **kw)

        return f

    R, DV = "Removed", "Would remove"
    return {
        "unused-imports": FixerConfig(
            "unused imports",
            _det_unused("imports"),
            _lazy_fix("fix_unused_imports"),
            "unused",
            R,
            DV,
        ),
        "debug-logs": FixerConfig(
            "tagged debug logs", _det_logs, _fix_logs, "logs", R, DV
        ),
        "unused-vars": FixerConfig(
            "unused vars", _det_unused("vars"), _fix_vars, "unused", R, DV
        ),
        "unused-params": FixerConfig(
            "unused params",
            _det_unused("vars"),
            _lazy_fix("fix_unused_params"),
            "unused",
            "Prefixed",
            "Would prefix",
        ),
        "dead-useeffect": FixerConfig(
            "dead useEffect calls",
            _det_smell("dead_useeffect"),
            _lazy_fix("fix_dead_useeffect"),
            "smells",
            R,
            DV,
        ),
        "empty-if-chain": FixerConfig(
            "empty if/else chains",
            _det_smell("empty_if_chain"),
            _lazy_fix("fix_empty_if_chain"),
            "smells",
            R,
            DV,
        ),
    }


# ── Build the config ──────────────────────────────────────



def _ts_extract_functions(path: Path) -> list[FunctionInfo]:
    """Extract all TS functions for duplicate detection."""
    functions = []
    for filepath in find_ts_files(path):
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        functions.extend(extract_ts_functions(filepath))
    return functions


@register_lang("typescript")
class TypeScriptConfig(LangConfig):
    def detect_lang_security(self, files, zone_map):
        return detect_ts_security(files, zone_map)

    def __init__(self):
        super().__init__(
            name="typescript",
            extensions=[".ts", ".tsx"],
            exclusions=["node_modules", ".d.ts"],
            default_src="src",
            build_dep_graph=deps_detector_mod.build_dep_graph,
            entry_patterns=[
                "/pages/",
                "/main.tsx",
                "/main.ts",
                "/App.tsx",
                "vite.config",
                "tailwind.config",
                "postcss.config",
                ".d.ts",
                "/settings.ts",
                "/__tests__/",
                ".test.",
                ".spec.",
                ".stories.",
            ],
            barrel_names={"index.ts", "index.tsx"},
            phases=[
                DetectorPhase("Logs", _phase_logs),
                DetectorPhase("Unused (tsc)", _phase_unused),
                DetectorPhase("Dead exports", _phase_exports),
                DetectorPhase("Deprecated", _phase_deprecated),
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase(
                    "Coupling + single-use + patterns + naming", _phase_coupling
                ),
                *_ts_treesitter_phases(),
                detector_phase_signature(),
                detector_phase_test_coverage(),
                DetectorPhase("Code smells", _phase_smells),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers=_get_ts_fixers(),
            get_area=get_area,
            detect_commands=ts_commands_mod.get_detect_commands(),
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
            holistic_review_dimensions=TS_HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=TS_MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=TS_MIGRATION_MIXED_EXTENSIONS,
            extract_functions=_ts_extract_functions,
            zone_rules=TS_ZONE_RULES,
        )
