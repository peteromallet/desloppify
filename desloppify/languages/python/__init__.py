"""Python language configuration for desloppify."""

from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

from desloppify.core._internal.text_utils import get_area
from desloppify.core.source_discovery import find_py_files
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.shared_phases import phase_private_imports
from desloppify.languages._framework.base.types import (
    DetectorCoverageStatus,
    DetectorPhase,
    LangConfig,
    LangSecurityResult,
)
from desloppify.languages.python import test_coverage as py_test_coverage_hooks
from desloppify.languages.python.commands import get_detect_commands
from desloppify.core.source_discovery import collect_exclude_dirs
from desloppify.languages.python.detectors.bandit_adapter import detect_with_bandit
from desloppify.languages.python.detectors.deps import build_dep_graph
from desloppify.languages.python.detectors.private_imports import (
    detect_private_imports as detect_python_private_imports,
)
from desloppify.languages.python.extractors import extract_py_functions
from desloppify.languages.python.phases import (
    PY_COMPLEXITY_SIGNALS as PY_COMPLEXITY_SIGNALS,
)
from desloppify.languages.python.phases import (
    PY_ENTRY_PATTERNS,
    phase_coupling,
    phase_dict_keys,
    phase_layer_violation,
    phase_mutable_state,
    phase_responsibility_cohesion,
    phase_smells,
    phase_structural,
    phase_uncalled_functions,
    phase_unused,
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


_get_py_area = partial(get_area, min_depth=3)


def _py_extract_functions(path: Path) -> list[FunctionInfo]:
    """Extract all Python functions for duplicate detection."""
    functions = []
    for filepath in find_py_files(path):
        functions.extend(extract_py_functions(filepath))
    return functions


def _scan_root_from_files(files: list[str]) -> Path | None:
    """Derive the common ancestor directory from a list of file paths."""
    import os

    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return None
    try:
        common = Path(os.path.commonpath(py_files))
        return common if common.is_dir() else common.parent
    except ValueError:
        return None


@register_lang("python")
class PythonConfig(LangConfig):
    def _missing_bandit_coverage(self) -> DetectorCoverageStatus:
        return DetectorCoverageStatus(
            detector="security",
            status="reduced",
            confidence=0.6,
            summary="bandit is not installed — Python-specific security checks will be skipped.",
            impact=(
                "Python-specific security coverage is reduced; clean security output may "
                "miss shell injection, unsafe deserialization, and risky SQL/subprocess patterns."
            ),
            remediation="Install Bandit: pip install bandit",
            tool="bandit",
            reason="missing_dependency",
        )

    def scan_coverage_prerequisites(self) -> list[DetectorCoverageStatus]:
        if shutil.which("bandit") is not None:
            return []
        return [self._missing_bandit_coverage()]

    def detect_lang_security_detailed(self, files, zone_map) -> LangSecurityResult:
        scan_root = _scan_root_from_files(files)
        if scan_root is None:
            return LangSecurityResult(entries=[], files_scanned=0)

        exclude_dirs = collect_exclude_dirs(scan_root)

        result = detect_with_bandit(scan_root, zone_map, exclude_dirs=exclude_dirs)
        coverage = result.status.coverage()
        return LangSecurityResult(
            entries=result.entries,
            files_scanned=result.files_scanned,
            coverage=coverage,
        )

    def detect_lang_security(self, files, zone_map):
        detailed = self.detect_lang_security_detailed(files, zone_map)
        return detailed.entries, detailed.files_scanned

    def detect_private_imports(self, graph, zone_map):
        return detect_python_private_imports(graph, zone_map)

    def __init__(self):
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
                DetectorPhase("Code smells", phase_smells),
                DetectorPhase("Mutable state", phase_mutable_state),
                detector_phase_security(),
                DetectorPhase("Private imports", phase_private_imports),
                DetectorPhase("Layer violations", phase_layer_violation),
                DetectorPhase("Dict key flow", phase_dict_keys),
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
