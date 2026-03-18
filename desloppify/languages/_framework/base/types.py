"""Core language-framework dataclasses and contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.languages._framework.base.lang_config_runtime import (
    clone_default,
    coerce_value,
    normalize_spec_values,
    runtime_value,
)
from desloppify.languages._framework.base.types_shared import (
    BoundaryRule,
    CoverageStatus,
    DetectorEntry,
    DetectorCoverageRecord,
    DetectorCoverageStatus,
    FixerConfig,
    FixResult,
    LangSecurityResult,
    LangValueSpec,
    ScanCoverageRecord,
)

if TYPE_CHECKING:
    from desloppify.engine.policy.zones import FileZoneMap, ZoneRule

# ---------------------------------------------------------------------------
# Type aliases for complex Callable signatures used in LangConfig fields
# ---------------------------------------------------------------------------
DepGraphBuilder = Callable[[Path], dict[str, dict[str, Any]]]
FunctionExtractor = Callable[[Path], list[FunctionInfo]]
FileFinder = Callable[[Path], list[str]]


@dataclass
class DetectorPhase:
    """A single phase in the scan pipeline.

    Each phase runs one or more detectors and returns normalized issues.
    The `run` function handles both detection AND normalization (converting
    raw detector output to issues with tiers/confidence).
    """

    label: str
    run: Callable[[Path, LangRuntimeContract], tuple[list[DetectorEntry], dict[str, int]]]
    slow: bool = False


class LangRuntimeContract(Protocol):
    """Explicit runtime interface consumed by detector phases.

    This Protocol lives here (rather than in runtime.py) to avoid an import
    cycle: runtime.py imports concrete types from this module, and
    DetectorPhase.run references LangRuntimeContract in its signature.
    """

    name: str
    extensions: list[str]
    entry_patterns: list[str]
    barrel_names: set[str]
    external_test_dirs: list[str]
    test_file_extensions: list[str]
    review_low_value_pattern: object | None
    file_finder: FileFinder | None
    extract_functions: FunctionExtractor | None
    get_area: Callable[[str], str] | None
    build_dep_graph: DepGraphBuilder
    detect_lang_security_detailed: Callable[[list[str], FileZoneMap | None], LangSecurityResult]
    detect_private_imports: Callable[
        [dict, FileZoneMap | None], tuple[list[DetectorEntry], int]
    ]
    large_threshold: int
    complexity_threshold: int
    props_threshold: int

    zone_map: FileZoneMap | None
    dep_graph: dict[str, dict[str, Any]] | None
    complexity_map: dict[str, float]
    runtime_cache: dict[str, Any]
    review_cache: dict[str, Any]
    review_max_age_days: int
    subjective_assessments: dict[str, Any]
    detector_coverage: dict[str, DetectorCoverageRecord]
    coverage_warnings: list[DetectorCoverageRecord]

    def runtime_setting(self, key: str, default: Any = None) -> Any: ...

    def runtime_option(self, key: str, default: Any = None) -> Any: ...

    def scan_coverage_prerequisites(self) -> list[DetectorCoverageStatus]: ...


@dataclass
class LangConfig:
    """Language configuration — everything the pipeline needs to scan a codebase."""

    name: str
    extensions: list[str]
    exclusions: list[str]
    default_src: str  # relative to PROJECT_ROOT

    # Dep graph builder (language-specific import parsing)
    build_dep_graph: DepGraphBuilder

    # Entry points (not orphaned even with 0 importers)
    entry_patterns: list[str]
    barrel_names: set[str]

    # Detector phases (ordered)
    phases: list[DetectorPhase] = field(default_factory=list)

    # Fixer registry
    fixers: dict[str, FixerConfig] = field(default_factory=dict)

    # Area classification (project-specific grouping)
    get_area: Callable[[str], str] | None = None

    # Commands for `detect` subcommand (language-specific overrides)
    # Keys serve as the valid detector name list.
    detect_commands: dict[str, Callable[..., Any]] = field(default_factory=dict)

    # Function extractor (for duplicate detection). Returns a list of FunctionInfo items.
    extract_functions: FunctionExtractor | None = None

    # Coupling boundaries (optional, project-specific)
    boundaries: list[BoundaryRule] = field(default_factory=list)

    # Unused detection tool command (for post-fix checklist)
    typecheck_cmd: str = ""

    # File finder: (path) -> list[str]
    file_finder: FileFinder | None = None

    # Structural analysis thresholds
    large_threshold: int = 500
    complexity_threshold: int = 15
    props_threshold: int = 14
    default_scan_profile: str = "full"

    # Language-specific persisted settings and per-run runtime options.
    setting_specs: dict[str, LangValueSpec] = field(default_factory=dict)
    runtime_option_specs: dict[str, LangValueSpec] = field(default_factory=dict)

    # Project-level files that indicate this language is present
    detect_markers: list[str] = field(default_factory=list)

    # External test discovery (outside scanned path)
    external_test_dirs: list[str] = field(default_factory=lambda: ["tests", "test"])
    test_file_extensions: list[str] = field(default_factory=list)

    # Review-context language hooks
    review_module_patterns_fn: Callable[[str], list[str]] | None = None
    review_api_surface_fn: Callable[[dict[str, str]], dict] | None = None
    review_guidance: dict = field(default_factory=dict)
    review_low_value_pattern: object | None = None
    holistic_review_dimensions: list[str] = field(default_factory=list)
    migration_pattern_pairs: list[tuple[str, object, object]] = field(
        default_factory=list
    )
    migration_mixed_extensions: set[str] = field(default_factory=set)

    # Zone classification rules
    zone_rules: list[ZoneRule] = field(default_factory=list)

    # Integration depth: "full" | "standard" | "shallow" | "minimal"
    integration_depth: str = "full"

    _default_runtime_settings: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )
    _default_runtime_options: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )

    @staticmethod
    def _clone_default(default: object) -> object:
        return clone_default(default)

    @classmethod
    def _coerce_value(cls, raw: object, expected: type, default: object) -> object:
        return coerce_value(raw, expected, default)

    def normalize_settings(self, values: dict[str, object] | None) -> dict[str, object]:
        return normalize_spec_values(values, self.setting_specs)

    def normalize_runtime_options(
        self,
        values: dict[str, object] | None,
        *,
        strict: bool = False,
    ) -> dict[str, object]:
        return normalize_spec_values(
            values,
            self.runtime_option_specs,
            strict=strict,
            owner_name=self.name,
        )

    def set_runtime_context(
        self,
        *,
        settings: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        """Set default runtime settings/options for future LangRun creation."""
        if settings is not None:
            self._default_runtime_settings = self.normalize_settings(settings)
        if options is not None:
            self._default_runtime_options = self.normalize_runtime_options(options)

    def runtime_setting(self, key: str, default: Any = None) -> Any:
        """Read setting from config-level runtime defaults."""
        return runtime_value(
            self._default_runtime_settings,
            self.setting_specs,
            key,
            default,
        )

    def runtime_option(self, key: str, default: Any = None) -> Any:
        """Read option from config-level runtime defaults."""
        return runtime_value(
            self._default_runtime_options,
            self.runtime_option_specs,
            key,
            default,
        )

    def detect_lang_security_detailed(
        self,
        files: list[str],
        zone_map: FileZoneMap | None,
    ) -> LangSecurityResult:
        """Language-specific security checks with optional coverage metadata."""
        return LangSecurityResult(entries=[], files_scanned=0)

    def detect_private_imports(
        self, graph: dict, zone_map: FileZoneMap | None
    ) -> tuple[list[DetectorEntry], int]:
        """Language-specific private-import detection. Override in subclasses."""
        return [], 0

    def scan_coverage_prerequisites(self) -> list[DetectorCoverageStatus]:
        """Optional preflight checks that can reduce scan confidence."""
        return []


__all__ = [
    "BoundaryRule",
    "CoverageStatus",
    "DepGraphBuilder",
    "DetectorEntry",
    "DetectorCoverageRecord",
    "DetectorCoverageStatus",
    "DetectorPhase",
    "FileFinder",
    "FixerConfig",
    "FixResult",
    "FunctionExtractor",
    "LangConfig",
    "LangRuntimeContract",
    "LangSecurityResult",
    "LangValueSpec",
    "ScanCoverageRecord",
]
