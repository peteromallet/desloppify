"""Language configuration for go."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages.framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages.framework.base.types import DetectorPhase, LangConfig
from desloppify.utils import find_source_files

from . import test_coverage as go_test_coverage_hooks
from .commands import get_detect_commands
from .extractors import extract_functions
from .phases import _phase_structural
from .review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)


GO_ZONE_RULES = [ZoneRule(Zone.TEST, ["_test.go"])] + COMMON_ZONE_RULES

register_lang_hooks("go", test_coverage=go_test_coverage_hooks)


def _find_files(path: Path) -> list[str]:
    return find_source_files(path, ['.go'])


def _build_dep_graph(path: Path) -> dict:
    from .detectors.deps import build_dep_graph

    return build_dep_graph(path)


@register_lang("go")
class GoConfig(LangConfig):
    def __init__(self):
        super().__init__(
            name='go',
            extensions=['.go'],
            exclusions=["node_modules", ".venv"],
            default_src='.',
            build_dep_graph=_build_dep_graph,
            entry_patterns=[],
            barrel_names=set(),
            phases=[
                DetectorPhase("Structural analysis", _phase_structural),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=lambda filepath: filepath.split("/")[0],
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="",
            file_finder=_find_files,
            detect_markers=['go.mod'],
            external_test_dirs=["tests", "test"],
            test_file_extensions=['.go'],
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
