"""Python language configuration for desloppify."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from desloppify.base.discovery.source import find_py_files
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
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
from desloppify.languages._framework.registry.registration import register_full_plugin
from desloppify.languages._framework.registry.state import register_lang_hooks
from desloppify.languages._framework.base.shared_phases import phase_private_imports
from desloppify.languages._framework.base.types import (
    DetectorCoverageStatus,
    DetectorPhase,
    LangConfig,
    LangSecurityResult,
)
from desloppify.languages.python import test_coverage as py_test_coverage_hooks
from desloppify.languages.python._helpers import _get_py_area, py_extract_functions
from desloppify.languages.python.review import (
    HOLISTIC_REVIEW_DIMENSIONS as PY_HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN as PY_LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS as PY_MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS as PY_MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE as PY_REVIEW_GUIDANCE,
    api_surface as py_review_api_surface,
    module_patterns as py_review_module_patterns,
)
from desloppify.languages.python._security import (
    detect_python_security,
    missing_bandit_coverage,
    python_scan_coverage_prerequisites,
)
from desloppify.languages.python._zones import PY_ZONE_RULES
from desloppify.languages.python.commands import get_detect_commands
from desloppify.languages.python.detectors.deps import build_dep_graph
from desloppify.languages.python.detectors.private_imports import (
    detect_private_imports as detect_python_private_imports,
)
from desloppify.languages.python.phases import (
    PY_COMPLEXITY_SIGNALS,
    PY_ENTRY_PATTERNS,
    PY_GOD_RULES,
    PY_SKIP_NAMES,
    phase_coupling,
    phase_dict_keys,
    phase_layer_violation,
    phase_mutable_state,
    phase_responsibility_cohesion,
    phase_smells,
    phase_structural,
    phase_uncalled_functions,
    phase_unused,
    phase_unused_enums,
)

if TYPE_CHECKING:
    from desloppify.engine.policy.zones import FileZoneMap


class PythonConfig(LangConfig):
    def _missing_bandit_coverage(self) -> DetectorCoverageStatus:
        return missing_bandit_coverage()

    def scan_coverage_prerequisites(self) -> list[DetectorCoverageStatus]:
        return python_scan_coverage_prerequisites()

    def detect_lang_security_detailed(
        self,
        files: list[str],
        zone_map: FileZoneMap | None,
    ) -> LangSecurityResult:
        return detect_python_security(files, zone_map)

    def detect_private_imports(
        self,
        graph: dict[str, dict[str, Any]],
        zone_map: FileZoneMap | None,
    ) -> tuple[list[dict], int]:
        return detect_python_private_imports(graph, zone_map)

    def __init__(self) -> None:
        super().__init__(
            name="python",
            extensions=[".py"],
            exclusions=["__pycache__", ".venv", "node_modules", ".eggs", "*.egg-info"],
            default_src=".",
            build_dep_graph=build_dep_graph,
            entry_patterns=PY_ENTRY_PATTERNS,
            barrel_names={"__init__.py"},
            phases=[
                DetectorPhase("Unused (ruff)", phase_unused),
                DetectorPhase("Structural analysis", phase_structural),
                DetectorPhase("Responsibility cohesion", phase_responsibility_cohesion),
                DetectorPhase("Coupling + cycles + orphaned", phase_coupling),
                DetectorPhase("Uncalled functions", phase_uncalled_functions),
                detector_phase_test_coverage(),
                detector_phase_signature(),
                DetectorPhase("Code smells", phase_smells),
                DetectorPhase("Mutable state", phase_mutable_state),
                detector_phase_security(),
                DetectorPhase("Private imports", phase_private_imports),
                DetectorPhase("Layer violations", phase_layer_violation),
                DetectorPhase("Dict key flow", phase_dict_keys),
                DetectorPhase("Unused enums", phase_unused_enums),
                detector_phase_advocacy_language(),
                detector_phase_advocacy_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=_get_py_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="",
            file_finder=find_py_files,
            large_threshold=500,
            complexity_threshold=25,
            default_scan_profile="full",
            detect_markers=["pyproject.toml", "setup.py", "setup.cfg"],
            external_test_dirs=["tests", "test"],
            test_file_extensions=[".py"],
            review_module_patterns_fn=py_review_module_patterns,
            review_api_surface_fn=py_review_api_surface,
            review_guidance=PY_REVIEW_GUIDANCE,
            review_low_value_pattern=PY_LOW_VALUE_PATTERN,
            holistic_review_dimensions=PY_HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=PY_MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=PY_MIGRATION_MIXED_EXTENSIONS,
            extract_functions=py_extract_functions,
            zone_rules=PY_ZONE_RULES,
        )


def register() -> None:
    """Register Python language config + hooks through an explicit entrypoint."""
    register_full_plugin(
        "python",
        PythonConfig,
        test_coverage=py_test_coverage_hooks,
    )


def register_hooks() -> None:
    """Register Python hook modules without language-config bootstrap."""
    register_lang_hooks("python", test_coverage=py_test_coverage_hooks)


Config = PythonConfig


__all__ = [
    "Config",
    "PY_COMPLEXITY_SIGNALS",
    "PY_ENTRY_PATTERNS",
    "PY_GOD_RULES",
    "PY_HOLISTIC_REVIEW_DIMENSIONS",
    "PY_LOW_VALUE_PATTERN",
    "PY_MIGRATION_MIXED_EXTENSIONS",
    "PY_MIGRATION_PATTERN_PAIRS",
    "PY_REVIEW_GUIDANCE",
    "PY_SKIP_NAMES",
    "PY_ZONE_RULES",
    "PythonConfig",
    "register",
    "register_hooks",
]
