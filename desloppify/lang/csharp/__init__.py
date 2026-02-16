"""C#/.NET language configuration for Desloppify."""

from __future__ import annotations

from pathlib import Path

from .. import register_lang
from ..base import (
    DetectorPhase,
    LangConfig,
    LangValueSpec,
    detector_phase_security,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from ...zones import COMMON_ZONE_RULES, Zone, ZoneRule
from .extractors import (
    CSHARP_FILE_EXCLUSIONS,
    extract_csharp_functions,
    find_csharp_files,
)
from .phases import _phase_coupling, _phase_structural
from .review import (
    LOW_VALUE_PATTERN as CSHARP_LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS as CSHARP_MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS as CSHARP_MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE as CSHARP_REVIEW_GUIDANCE,
    api_surface as csharp_review_api_surface,
    module_patterns as csharp_review_module_patterns,
)


def _get_csharp_area(filepath: str) -> str:
    """Derive an area name from file path for lightweight grouping."""
    parts = filepath.split("/")
    if len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0] if parts else filepath


def _build_dep_graph(path: Path) -> dict:
    """Build C# dependency graph."""
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _extract_csharp_functions(path: Path) -> list:
    """Extract all C# functions for duplicate detection.
    """
    functions = []
    for filepath in find_csharp_files(path):
        functions.extend(extract_csharp_functions(filepath))
    return functions


CSHARP_ENTRY_PATTERNS = [
    "/Program.cs",
    "/Startup.cs",
    "/Main.cs",
    "/MauiProgram.cs",
    "/MainActivity.cs",
    "/AppDelegate.cs",
    "/SceneDelegate.cs",
    "/WinUIApplication.cs",
    "/App.xaml.cs",
    "/Properties/",
    "/Migrations/",
    ".g.cs",
    ".designer.cs",
]

CSHARP_ZONE_RULES = [
    ZoneRule(Zone.GENERATED, [".g.cs", ".designer.cs", "/obj/", "/bin/"]),
    ZoneRule(Zone.TEST, [".Tests.cs", "Tests.cs", "Test.cs", "/Tests/", "/test/"]),
    ZoneRule(Zone.CONFIG, ["/Program.cs", "/Startup.cs", "/AssemblyInfo.cs"]),
] + COMMON_ZONE_RULES


@register_lang("csharp")
class CSharpConfig(LangConfig):
    """C# language configuration."""

    def detect_lang_security(self, files, zone_map):
        from .detectors.security import detect_csharp_security
        return detect_csharp_security(files, zone_map)

    def __init__(self):
        from .commands import get_detect_commands
        super().__init__(
            name="csharp",
            extensions=[".cs"],
            exclusions=CSHARP_FILE_EXCLUSIONS,
            default_src=".",
            build_dep_graph=_build_dep_graph,
            entry_patterns=CSHARP_ENTRY_PATTERNS,
            barrel_names={"Program.cs"},
            phases=[
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", _phase_coupling),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=_get_csharp_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="dotnet build",
            file_finder=find_csharp_files,
            large_threshold=500,
            complexity_threshold=20,
            default_scan_profile="objective",
            setting_specs={
                "corroboration_min_signals": LangValueSpec(
                    int,
                    2,
                    "Minimum corroboration signals required for medium confidence "
                    "in orphaned/single_use findings",
                ),
                "high_fanout_threshold": LangValueSpec(
                    int,
                    5,
                    "Import-count threshold treated as high fan-out for confidence corroboration",
                ),
            },
            legacy_setting_keys={
                "csharp_corroboration_min_signals": "corroboration_min_signals",
                "csharp_high_fanout_threshold": "high_fanout_threshold",
            },
            runtime_option_specs={
                "roslyn_cmd": LangValueSpec(
                    str,
                    "",
                    "Command that emits Roslyn dependency JSON to stdout",
                ),
            },
            detect_markers=["global.json"],
            external_test_dirs=["tests", "test"],
            test_file_extensions=[".cs"],
            review_module_patterns_fn=csharp_review_module_patterns,
            review_api_surface_fn=csharp_review_api_surface,
            review_guidance=CSHARP_REVIEW_GUIDANCE,
            review_low_value_pattern=CSHARP_LOW_VALUE_PATTERN,
            holistic_review_dimensions=[
                "cross_module_architecture",
                "convention_outlier",
                "error_consistency",
                "abstraction_fitness",
                "api_surface_coherence",
                "authorization_consistency",
                "ai_generated_debt",
                "incomplete_migration",
            ],
            migration_pattern_pairs=CSHARP_MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=CSHARP_MIGRATION_MIXED_EXTENSIONS,
            extract_functions=_extract_csharp_functions,
            zone_rules=CSHARP_ZONE_RULES,
        )
