"""TypeScript/React language configuration for desloppify."""

from __future__ import annotations

from desloppify.base.discovery.paths import get_area
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_signature,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.phases_advocacy import (
    detector_phase_advocacy_language,
    detector_phase_advocacy_security,
)
from desloppify.languages._framework.base.types import (
    BoundaryRule,
    DetectorPhase,
    LangConfig,
    LangSecurityResult,
)
from desloppify.languages._framework.frameworks.phases import framework_phases
from desloppify.languages._framework.registry.registration import register_full_plugin
from desloppify.languages._framework.registry.state import register_lang_hooks
from desloppify.languages.typescript import test_coverage as ts_test_coverage_hooks
from desloppify.languages.typescript._fixers import get_ts_fixers
import desloppify.languages.typescript.commands as ts_commands_mod
import desloppify.languages.typescript.detectors.deps as deps_detector_mod
from desloppify.languages.typescript.detectors.security.detector import detect_ts_security
from desloppify.languages.typescript.extractors_functions import extract_ts_functions
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
from desloppify.languages.typescript.phases_coupling import phase_coupling
from desloppify.languages.typescript.phases_smells import phase_smells
from desloppify.languages.typescript.phases_structural import phase_structural
from desloppify.languages.typescript.detectors.io import iter_typescript_sources
from desloppify.languages.typescript.review import (
    HOLISTIC_REVIEW_DIMENSIONS as TS_HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN as TS_LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS as TS_MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS as TS_MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE as TS_REVIEW_GUIDANCE,
    api_surface as ts_review_api_surface,
    module_patterns as ts_review_module_patterns,
)
from desloppify.languages.typescript._zones import TS_ZONE_RULES
from desloppify.languages.typescript.plugin_contract import (
    TS_BARREL_NAMES,
    TS_COMPLEXITY_THRESHOLD,
    TS_DEFAULT_SRC,
    TS_ENTRY_PATTERNS,
    TS_EXCLUSIONS,
    TS_EXTENSIONS,
    TS_LARGE_THRESHOLD,
)


def _ts_treesitter_phases() -> list[DetectorPhase]:
    """Cherry-pick tree-sitter phases that complement TS's own detectors."""
    from desloppify.languages._framework.treesitter import get_spec, is_available
    from desloppify.languages._framework.treesitter.phases import make_cohesion_phase

    if not is_available():
        return []

    spec = get_spec("typescript")
    if spec is None:
        return []

    return [make_cohesion_phase(spec)]


def _ts_extract_functions(path):
    """Extract all TS functions for duplicate detection."""
    from desloppify.base.discovery.source import find_ts_and_tsx_files

    functions = []
    for filepath in find_ts_and_tsx_files(path):
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        functions.extend(extract_ts_functions(filepath))
    return functions


class TypeScriptConfig(LangConfig):
    def detect_lang_security_detailed(self, files, zone_map):
        result = detect_ts_security(files, zone_map)
        return LangSecurityResult(
            entries=result.entries,
            files_scanned=result.population_size,
        )

    def __init__(self):
        super().__init__(
            name="typescript",
            extensions=TS_EXTENSIONS,
            exclusions=TS_EXCLUSIONS,
            default_src=TS_DEFAULT_SRC,
            build_dep_graph=deps_detector_mod.build_dep_graph,
            entry_patterns=TS_ENTRY_PATTERNS,
            barrel_names=TS_BARREL_NAMES,
            phases=[
                DetectorPhase("Logs", phase_logs),
                DetectorPhase("Unused (tsc)", phase_unused),
                DetectorPhase("Dead exports", phase_exports),
                DetectorPhase("Deprecated", phase_deprecated),
                DetectorPhase("Structural analysis", phase_structural),
                DetectorPhase(
                    "Coupling + single-use + patterns + naming",
                    phase_coupling,
                ),
                *_ts_treesitter_phases(),
                detector_phase_signature(),
                detector_phase_test_coverage(),
                DetectorPhase("Code smells", phase_smells),
                *framework_phases("typescript"),
                detector_phase_security(),
                detector_phase_advocacy_language(),
                detector_phase_advocacy_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers=get_ts_fixers(),
            get_area=get_area,
            detect_commands=ts_commands_mod.get_detect_commands(),
            boundaries=[
                BoundaryRule("shared/", "tools/", "shared→tools"),
            ],
            typecheck_cmd="npx tsc --noEmit",
            file_finder=iter_typescript_sources,
            large_threshold=TS_LARGE_THRESHOLD,
            complexity_threshold=TS_COMPLEXITY_THRESHOLD,
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


def register() -> None:
    """Register TypeScript language config + hooks through an explicit entrypoint."""
    register_full_plugin(
        "typescript",
        TypeScriptConfig,
        test_coverage=ts_test_coverage_hooks,
    )


def register_hooks() -> None:
    """Register TypeScript hook modules without language-config bootstrap."""
    register_lang_hooks("typescript", test_coverage=ts_test_coverage_hooks)


Config = TypeScriptConfig


__all__ = [
    "Config",
    "TS_HOLISTIC_REVIEW_DIMENSIONS",
    "TS_LOW_VALUE_PATTERN",
    "TS_MIGRATION_MIXED_EXTENSIONS",
    "TS_MIGRATION_PATTERN_PAIRS",
    "TS_REVIEW_GUIDANCE",
    "TS_ZONE_RULES",
    "TypeScriptConfig",
    "register",
    "register_hooks",
]
