"""C/C++ language configuration for Desloppify."""

from __future__ import annotations

from desloppify.base.discovery.paths import get_area
from desloppify.engine.hook_registry import register_lang_hooks
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_signature,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.types import (
    DetectorPhase,
    LangConfig,
    LangSecurityResult,
)
from desloppify.languages._framework.generic_parts.tool_factories import make_tool_phase
from desloppify.languages._framework.registry.registration import register_full_plugin
from desloppify.languages._framework.treesitter.phases import all_treesitter_phases
from desloppify.languages.cxx import test_coverage as cxx_test_coverage_hooks
from desloppify.languages.cxx._helpers import build_cxx_dep_graph
from desloppify.languages.cxx._zones import CXX_ENTRY_PATTERNS, CXX_ZONE_RULES
from desloppify.languages.cxx.commands import get_detect_commands
from desloppify.languages.cxx.detectors.security import detect_cxx_security
from desloppify.languages.cxx.extractors import (
    CXX_EXTENSIONS,
    CXX_FILE_EXCLUSIONS,
    CXX_SOURCE_EXTENSIONS,
    extract_all_cxx_functions,
    find_cxx_files,
)
from desloppify.languages.cxx.phases import phase_coupling, phase_cppcheck_issue, phase_structural
from desloppify.languages.cxx.review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)


class CxxConfig(LangConfig):
    """C/C++ language configuration."""

    def detect_lang_security_detailed(self, files, zone_map) -> LangSecurityResult:
        return detect_cxx_security(files, zone_map)

    def __init__(self):
        tree_sitter_phases = [
            phase for phase in all_treesitter_phases("cpp")
            if phase.label != "Unused imports"
        ]

        super().__init__(
            name="cxx",
            extensions=CXX_EXTENSIONS,
            exclusions=CXX_FILE_EXCLUSIONS,
            default_src=".",
            build_dep_graph=build_cxx_dep_graph,
            entry_patterns=CXX_ENTRY_PATTERNS,
            barrel_names=set(),
            phases=[
                DetectorPhase("Structural analysis", phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", phase_coupling),
                DetectorPhase("cppcheck", phase_cppcheck_issue),
                *tree_sitter_phases,
                detector_phase_signature(),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=get_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="cppcheck --enable=all --quiet .",
            file_finder=find_cxx_files,
            large_threshold=500,
            complexity_threshold=15,
            default_scan_profile="objective",
            detect_markers=["CMakeLists.txt", "Makefile"],
            external_test_dirs=["tests", "test"],
            test_file_extensions=list(CXX_SOURCE_EXTENSIONS),
            review_module_patterns_fn=module_patterns,
            review_api_surface_fn=api_surface,
            review_guidance=REVIEW_GUIDANCE,
            review_low_value_pattern=LOW_VALUE_PATTERN,
            holistic_review_dimensions=HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=MIGRATION_MIXED_EXTENSIONS,
            extract_functions=extract_all_cxx_functions,
            zone_rules=CXX_ZONE_RULES,
        )


def register() -> None:
    """Register the C/C++ language config and hook modules."""
    register_full_plugin(
        "cxx",
        CxxConfig,
        test_coverage=cxx_test_coverage_hooks,
    )


def register_hooks() -> None:
    """Register C/C++ hook modules without language-config bootstrap."""
    register_lang_hooks("cxx", test_coverage=cxx_test_coverage_hooks)


Config = CxxConfig


__all__ = [
    "Config",
    "CXX_ENTRY_PATTERNS",
    "CXX_ZONE_RULES",
    "CxxConfig",
    "HOLISTIC_REVIEW_DIMENSIONS",
    "LOW_VALUE_PATTERN",
    "MIGRATION_MIXED_EXTENSIONS",
    "MIGRATION_PATTERN_PAIRS",
    "REVIEW_GUIDANCE",
    "register",
    "register_hooks",
]
