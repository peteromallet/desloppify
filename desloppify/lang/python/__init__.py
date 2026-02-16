"""Python language configuration for desloppify."""

from __future__ import annotations

from pathlib import Path

from .. import register_lang
from ..base import (
    DetectorPhase,
    LangConfig,
    phase_dupes,
    phase_private_imports,
    phase_security,
    phase_subjective_review,
    phase_test_coverage,
)
from ...utils import find_py_files
from ...zones import COMMON_ZONE_RULES, Zone, ZoneRule
from .phases import (
    PY_COMPLEXITY_SIGNALS,  # noqa: F401 - re-exported for commands/tests
    PY_ENTRY_PATTERNS,  # noqa: F401 - re-exported for commands/tests
    PY_GOD_RULES,  # noqa: F401 - re-exported for commands/tests
    PY_SKIP_NAMES,  # noqa: F401 - re-exported for commands/tests
    _phase_coupling,
    _phase_dict_keys,
    _phase_layer_violation,
    _phase_mutable_state,
    _phase_smells,
    _phase_structural,
    _phase_unused,
)
from .review import (
    LOW_VALUE_PATTERN as PY_LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS as PY_MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS as PY_MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE as PY_REVIEW_GUIDANCE,
    api_surface as py_review_api_surface,
    module_patterns as py_review_module_patterns,
)


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
    ZoneRule(Zone.SCRIPT, ["__main__.py"]),
] + COMMON_ZONE_RULES


def _get_py_area(filepath: str) -> str:
    """Derive an area name from a Python file path for grouping."""
    parts = filepath.split("/")
    if len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if parts else filepath


def _py_build_dep_graph(path: Path) -> dict:
    from .detectors.deps import build_dep_graph

    return build_dep_graph(path)


def _py_extract_functions(path: Path) -> list:
    """Extract all Python functions for duplicate detection."""
    from .extractors import extract_py_functions

    functions = []
    for filepath in find_py_files(path):
        functions.extend(extract_py_functions(filepath))
    return functions


@register_lang("python")
class PythonConfig(LangConfig):
    def detect_lang_security(self, files, zone_map):
        from .detectors.security import detect_python_security

        return detect_python_security(files, zone_map)

    def detect_private_imports(self, graph, zone_map):
        from .detectors.private_imports import detect_private_imports

        return detect_private_imports(graph, zone_map)

    def __init__(self):
        from .commands import get_detect_commands

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
                DetectorPhase("Coupling + cycles + orphaned", _phase_coupling),
                DetectorPhase("Test coverage", phase_test_coverage),
                DetectorPhase("Code smells", _phase_smells),
                DetectorPhase("Mutable state", _phase_mutable_state),
                DetectorPhase("Security", phase_security),
                DetectorPhase("Private imports", phase_private_imports),
                DetectorPhase("Layer violations", _phase_layer_violation),
                DetectorPhase("Subjective review", phase_subjective_review),
                DetectorPhase("Dict key flow", _phase_dict_keys),
                DetectorPhase("Duplicates", phase_dupes, slow=True),
            ],
            fixers={},
            get_area=_get_py_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="",
            file_finder=find_py_files,
            large_threshold=300,
            complexity_threshold=25,
            detect_markers=["pyproject.toml", "setup.py", "setup.cfg"],
            external_test_dirs=["tests", "test"],
            test_file_extensions=[".py"],
            review_module_patterns_fn=py_review_module_patterns,
            review_api_surface_fn=py_review_api_surface,
            review_guidance=PY_REVIEW_GUIDANCE,
            review_low_value_pattern=PY_LOW_VALUE_PATTERN,
            holistic_review_dimensions=[
                "cross_module_architecture",
                "convention_outlier",
                "error_consistency",
                "abstraction_fitness",
                "dependency_health",
                "test_strategy",
                "ai_generated_debt",
                "package_organization",
            ],
            migration_pattern_pairs=PY_MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=PY_MIGRATION_MIXED_EXTENSIONS,
            extract_functions=_py_extract_functions,
            zone_rules=PY_ZONE_RULES,
        )
