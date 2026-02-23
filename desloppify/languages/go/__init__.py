"""Go language configuration for Desloppify.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
Upgraded from generic_lang to full class-based plugin.
"""

from __future__ import annotations

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages.go import test_coverage as go_test_coverage_hooks
from desloppify.languages.go.commands import get_detect_commands
from desloppify.languages.go.detectors.deps import build_dep_graph as build_go_dep_graph
from desloppify.languages.go.extractors import (
    GO_FILE_EXCLUSIONS,
    extract_functions,
    find_go_files,
)
from desloppify.languages.go.phases import _phase_structural
from desloppify.languages.go.review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)
from desloppify.languages._framework.generic import make_tool_phase
from desloppify.languages._framework.treesitter.phases import all_treesitter_phases
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_signature,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.core._internal.text_utils import get_area
from desloppify.languages._framework.base.types import DetectorPhase, LangConfig

GO_ENTRY_PATTERNS = ["/main.go", "/cmd/"]

GO_ZONE_RULES = [
    ZoneRule(Zone.TEST, ["_test.go"]),
] + COMMON_ZONE_RULES

register_lang_hooks("go", test_coverage=go_test_coverage_hooks)


@register_lang("go")
class GoConfig(LangConfig):
    """Go language configuration."""

    def __init__(self):
        super().__init__(
            name="go",
            extensions=[".go"],
            exclusions=GO_FILE_EXCLUSIONS,
            default_src=".",
            build_dep_graph=build_go_dep_graph,
            entry_patterns=GO_ENTRY_PATTERNS,
            barrel_names=set(),
            phases=[
                DetectorPhase("Structural analysis", _phase_structural),
                make_tool_phase(
                    "golangci-lint",
                    "golangci-lint run --out-format=json",
                    "golangci",
                    "golangci_lint",
                    tier=2,
                ),
                make_tool_phase(
                    "go vet", "go vet ./...", "gnu", "vet_error", tier=3
                ),
                *all_treesitter_phases("go"),
                detector_phase_signature(),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=get_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="go vet ./...",
            file_finder=find_go_files,
            large_threshold=500,
            complexity_threshold=15,
            default_scan_profile="full",
            detect_markers=["go.mod"],
            external_test_dirs=[],
            test_file_extensions=[".go"],
            review_module_patterns_fn=module_patterns,
            review_api_surface_fn=api_surface,
            review_guidance=REVIEW_GUIDANCE,
            review_low_value_pattern=LOW_VALUE_PATTERN,
            holistic_review_dimensions=HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=MIGRATION_MIXED_EXTENSIONS,
            extract_functions=extract_functions,
            zone_rules=GO_ZONE_RULES,
        )
