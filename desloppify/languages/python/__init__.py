"""Python language configuration for desloppify."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages.framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages.framework.base.shared_phases import phase_private_imports
from desloppify.languages.framework.base.types import DetectorPhase, LangConfig
from desloppify.languages.python import test_coverage as py_test_coverage_hooks
from desloppify.languages.python.commands import get_detect_commands
from desloppify.languages.python.detectors.deps import build_dep_graph
from desloppify.languages.python.detectors.private_imports import (
    detect_private_imports as detect_python_private_imports,
)
from desloppify.languages.python.detectors.security import detect_python_security
from desloppify.languages.python.extractors import extract_py_functions
from desloppify.languages.python.phases import (
    PY_COMPLEXITY_SIGNALS as PY_COMPLEXITY_SIGNALS,
)
from desloppify.languages.python.phases import (
    PY_ENTRY_PATTERNS,
    _phase_coupling,
    _phase_dict_keys,
    _phase_layer_violation,
    _phase_mutable_state,
    _phase_responsibility_cohesion,
    _phase_smells,
    _phase_structural,
    _phase_unused,
)
from desloppify.languages.python.phases import (
    PY_GOD_RULES as PY_GOD_RULES,
)
from desloppify.languages.python.phases import (
    PY_SKIP_NAMES as PY_SKIP_NAMES,
)
from desloppify.languages.python.review import (
    HOLISTIC_REVIEW_DIMENSIONS as PY_HOLISTIC_REVIEW_DIMENSIONS,
)
from desloppify.languages.python.review import LOW_VALUE_PATTERN as PY_LOW_VALUE_PATTERN
from desloppify.languages.python.review import (
    MIGRATION_MIXED_EXTENSIONS as PY_MIGRATION_MIXED_EXTENSIONS,
)
from desloppify.languages.python.review import (
    MIGRATION_PATTERN_PAIRS as PY_MIGRATION_PATTERN_PAIRS,
)
from desloppify.languages.python.review import REVIEW_GUIDANCE as PY_REVIEW_GUIDANCE
from desloppify.languages.python.review import api_surface as py_review_api_surface
from desloppify.languages.python.review import (
    module_patterns as py_review_module_patterns,
)
from desloppify.utils import find_py_files

# ── Zone classification rules (order matters — first match wins) ──

PY_ZONE_RULES = [
    ZoneRule(Zone.GENERATED, ["/migrations/", "_pb2.py", "_pb2_grpc.py"]),
    ZoneRule(Zone.TEST, ["test_", "_test.py", "conftest.py", "/factories/"]),
    ZoneRule(
        Zone.CONFIG,
        [
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "manage.py",
            "wsgi.py",
            "asgi.py",
            "settings.py",
            "config.py",
        ],
    ),
    ZoneRule(Zone.SCRIPT, ["__main__.py", "/commands/"]),
] + COMMON_ZONE_RULES


register_lang_hooks("python", test_coverage=py_test_coverage_hooks)


def _get_py_area(filepath: str) -> str:
    """Derive an area name from a Python file path for grouping."""
    parts = [part for part in re.split(r"[\\/]+", filepath) if part]
    if len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if parts else filepath


def _py_build_dep_graph(path: Path) -> dict:
    return build_dep_graph(path)


def _py_extract_functions(path: Path) -> list:
    """Extract all Python functions for duplicate detection."""
    functions = []
    for filepath in find_py_files(path):
        functions.extend(extract_py_functions(filepath))
    return functions


@register_lang("python")
class PythonConfig(LangConfig):
    def detect_lang_security(self, files, zone_map):
        return detect_python_security(files, zone_map)

    def detect_private_imports(self, graph, zone_map):
        return detect_python_private_imports(graph, zone_map)

    def __init__(self):
        super().__init__(
            name="python",
            extensions=[".py"],
            exclusions=["__pycache__", ".venv", "node_modules", ".eggs", "*.egg-info"],
            default_src=".",
            build_dep_graph=_py_build_dep_graph,
            entry_patterns=PY_ENTRY_PATTERNS,
            barrel_names={"__init__.py"},
            phases=[
                DetectorPhase("Unused (ruff)", _phase_unused),
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Responsibility cohesion", _phase_responsibility_cohesion),
                DetectorPhase("Coupling + cycles + orphaned", _phase_coupling),
                detector_phase_test_coverage(),
                DetectorPhase("Code smells", _phase_smells),
                DetectorPhase("Mutable state", _phase_mutable_state),
                detector_phase_security(),
                DetectorPhase("Private imports", phase_private_imports),
                DetectorPhase("Layer violations", _phase_layer_violation),
                DetectorPhase("Dict key flow", _phase_dict_keys),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=_get_py_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="",
            file_finder=find_py_files,
            large_threshold=300,
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
            extract_functions=_py_extract_functions,
            zone_rules=PY_ZONE_RULES,
        )
