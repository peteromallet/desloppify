"""Rust language configuration for Desloppify."""

from __future__ import annotations

from desloppify.base.discovery.paths import get_area
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.types import DetectorPhase, LangConfig
from desloppify.languages._framework.registry.registration import register_full_plugin
from desloppify.languages._framework.registry.state import register_lang_hooks
from desloppify.languages._framework.treesitter.phases import all_treesitter_phases
from desloppify.languages.rust import test_coverage as rust_test_coverage_hooks
from desloppify.languages.rust._fixers import get_rust_fixers
from desloppify.languages.rust.commands import get_detect_commands
from desloppify.languages.rust.detectors.deps import (
    build_dep_graph as build_rust_dep_graph,
)
from desloppify.languages.rust.extractors import (
    RUST_FILE_EXCLUSIONS,
    extract_functions,
    find_rust_files,
)
from desloppify.languages.rust.phases import (
    RUST_CHECK_LABEL,
    RUST_CLIPPY_LABEL,
    RUST_POLICY_LABEL,
    RUST_RUSTDOC_LABEL,
    phase_coupling,
    phase_custom_policy,
    phase_signature,
    phase_structural,
    tool_phase_check,
    tool_phase_clippy,
    tool_phase_rustdoc,
)
from desloppify.languages.rust.phases_smells import phase_smells
from desloppify.languages.rust.review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)

RUST_ENTRY_PATTERNS = [
    "src/lib.rs",
    "src/main.rs",
    "src/bin/",
    "tests/",
    "examples/",
    "benches/",
    "fuzz/",
    "build.rs",
]

RUST_ZONE_RULES = [
    ZoneRule(Zone.PRODUCTION, ["/src/bin/"]),
    ZoneRule(
        Zone.TEST,
        ["/tests/", "*_tests/*", "tests.rs", "test.rs", "_tests.rs", "test_"],
    ),
    ZoneRule(Zone.SCRIPT, ["/examples/", "/benches/", "/fuzz/", "build.rs"]),
    ZoneRule(Zone.CONFIG, ["Cargo.toml", "Cargo.lock", "/.cargo/"]),
] + COMMON_ZONE_RULES


class RustConfig(LangConfig):
    """Rust language configuration."""

    def __init__(self):
        tree_sitter_phases = [
            phase for phase in all_treesitter_phases("rust")
            if phase.label != "Unused imports"
        ]

        super().__init__(
            name="rust",
            extensions=[".rs"],
            exclusions=RUST_FILE_EXCLUSIONS,
            default_src="src",
            build_dep_graph=build_rust_dep_graph,
            entry_patterns=RUST_ENTRY_PATTERNS,
            barrel_names={"lib.rs"},
            phases=[
                DetectorPhase("Structural analysis", phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", phase_coupling),
                DetectorPhase(RUST_POLICY_LABEL, phase_custom_policy),
                tool_phase_clippy(),
                tool_phase_check(),
                tool_phase_rustdoc(),
                *tree_sitter_phases,
                DetectorPhase("Signature analysis", phase_signature),
                detector_phase_test_coverage(),
                DetectorPhase("Code smells", phase_smells),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers=get_rust_fixers(),
            get_area=get_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="cargo check",
            file_finder=find_rust_files,
            large_threshold=500,
            complexity_threshold=15,
            boilerplate_min_lines=8,
            default_scan_profile="full",
            detect_markers=["Cargo.toml"],
            external_test_dirs=["tests"],
            test_file_extensions=[".rs"],
            review_module_patterns_fn=module_patterns,
            review_api_surface_fn=api_surface,
            review_guidance=REVIEW_GUIDANCE,
            review_low_value_pattern=LOW_VALUE_PATTERN,
            holistic_review_dimensions=HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=MIGRATION_MIXED_EXTENSIONS,
            extract_functions=extract_functions,
            zone_rules=RUST_ZONE_RULES,
        )


def register() -> None:
    """Register Rust language config + hooks through an explicit entrypoint."""
    register_full_plugin(
        "rust",
        RustConfig,
        test_coverage=rust_test_coverage_hooks,
    )


def register_hooks() -> None:
    """Register Rust hook modules without language-config bootstrap."""
    register_lang_hooks("rust", test_coverage=rust_test_coverage_hooks)


Config = RustConfig


__all__ = [
    "Config",
    "RustConfig",
    "register",
    "register_hooks",
    "RUST_CHECK_LABEL",
    "RUST_CLIPPY_LABEL",
    "RUST_ENTRY_PATTERNS",
    "RUST_POLICY_LABEL",
    "RUST_RUSTDOC_LABEL",
    "RUST_ZONE_RULES",
    "HOLISTIC_REVIEW_DIMENSIONS",
    "LOW_VALUE_PATTERN",
    "MIGRATION_MIXED_EXTENSIONS",
    "MIGRATION_PATTERN_PAIRS",
    "REVIEW_GUIDANCE",
]
