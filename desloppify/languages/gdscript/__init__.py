"""GDScript (Godot) language configuration for Desloppify."""

from __future__ import annotations

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages.framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages.framework.base.types import DetectorPhase, LangConfig
from desloppify.languages.gdscript import test_coverage as gdscript_test_coverage_hooks
from desloppify.languages.gdscript.commands import get_detect_commands
from desloppify.languages.gdscript.detectors.deps import (
    build_dep_graph as build_gdscript_dep_graph,
)
from desloppify.languages.gdscript.extractors import (
    GDSCRIPT_FILE_EXCLUSIONS,
    extract_functions,
    find_gdscript_files,
)
from desloppify.languages.gdscript.phases import _phase_coupling, _phase_structural
from desloppify.languages.gdscript.review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)


def _get_gdscript_area(filepath: str) -> str:
    parts = [part for part in filepath.replace("\\", "/").split("/") if part]
    if len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0] if parts else filepath


GDSCRIPT_ENTRY_PATTERNS = [
    "/main.gd",
    "/autoload/",
    "/addons/",
    "/tests/",
    "/test/",
]

GDSCRIPT_ZONE_RULES = [
    ZoneRule(Zone.TEST, ["/tests/", "/test/", "test_", "_test.gd"]),
    ZoneRule(Zone.CONFIG, ["/project.godot", "/.godot/", "/addons/"]),
    ZoneRule(Zone.GENERATED, ["/.import/", ".import", ".uid"]),
] + COMMON_ZONE_RULES


register_lang_hooks("gdscript", test_coverage=gdscript_test_coverage_hooks)


@register_lang("gdscript")
class GdscriptConfig(LangConfig):
    """GDScript language configuration."""

    def __init__(self):
        super().__init__(
            name="gdscript",
            extensions=[".gd"],
            exclusions=GDSCRIPT_FILE_EXCLUSIONS,
            default_src="src",
            build_dep_graph=build_gdscript_dep_graph,
            entry_patterns=GDSCRIPT_ENTRY_PATTERNS,
            barrel_names=set(),
            phases=[
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", _phase_coupling),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=_get_gdscript_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="godot --headless --check-only",
            file_finder=find_gdscript_files,
            large_threshold=500,
            complexity_threshold=16,
            default_scan_profile="full",
            detect_markers=["project.godot"],
            external_test_dirs=["tests", "test"],
            test_file_extensions=[".gd"],
            review_module_patterns_fn=module_patterns,
            review_api_surface_fn=api_surface,
            review_guidance=REVIEW_GUIDANCE,
            review_low_value_pattern=LOW_VALUE_PATTERN,
            holistic_review_dimensions=HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=MIGRATION_MIXED_EXTENSIONS,
            extract_functions=extract_functions,
            zone_rules=GDSCRIPT_ZONE_RULES,
        )
