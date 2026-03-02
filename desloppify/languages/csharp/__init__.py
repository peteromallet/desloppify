"""C#/.NET language configuration for Desloppify."""

from __future__ import annotations

from pathlib import Path

from desloppify.core._internal.text_utils import get_area
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_signature,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.types import (
    DetectorPhase,
    LangConfig,
    LangSecurityResult,
    LangValueSpec,
)
from desloppify.languages._framework.treesitter.phases import all_treesitter_phases
from desloppify.languages.csharp import move as csharp_move_helpers
from desloppify.languages.csharp import test_coverage as csharp_test_coverage_hooks
from desloppify.languages.csharp.commands import get_detect_commands
from desloppify.languages.csharp.detectors.deps import (
    build_dep_graph as build_csharp_dep_graph,
)
from desloppify.languages.csharp.detectors.security import detect_csharp_security
from desloppify.languages.csharp.extractors import (
    CSHARP_FILE_EXCLUSIONS,
    extract_csharp_functions,
    find_csharp_files,
)
from desloppify.languages.csharp.phases import _phase_coupling, _phase_structural
from desloppify.languages.csharp.review import (
    HOLISTIC_REVIEW_DIMENSIONS as CSHARP_HOLISTIC_REVIEW_DIMENSIONS,
)
from desloppify.languages.csharp.review import (
    LOW_VALUE_PATTERN as CSHARP_LOW_VALUE_PATTERN,
)
from desloppify.languages.csharp.review import (
    MIGRATION_MIXED_EXTENSIONS as CSHARP_MIGRATION_MIXED_EXTENSIONS,
)
from desloppify.languages.csharp.review import (
    MIGRATION_PATTERN_PAIRS as CSHARP_MIGRATION_PATTERN_PAIRS,
)
from desloppify.languages.csharp.review import REVIEW_GUIDANCE as CSHARP_REVIEW_GUIDANCE
from desloppify.languages.csharp.review import api_surface as csharp_review_api_surface
from desloppify.languages.csharp.review import (
    module_patterns as csharp_review_module_patterns,
)

_CSHARP_MOVE_HELPERS = (
    csharp_move_helpers.find_replacements,
    csharp_move_helpers.find_self_replacements,
    csharp_move_helpers.filter_intra_package_importer_changes,
    csharp_move_helpers.filter_directory_self_changes,
)


def _extract_csharp_functions(path: Path) -> list[FunctionInfo]:
    """Extract all C# functions for duplicate detection."""
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


register_lang_hooks("csharp", test_coverage=csharp_test_coverage_hooks)


@register_lang("csharp")
class CSharpConfig(LangConfig):
    """C# language configuration."""

    def detect_lang_security_detailed(self, files, zone_map):
        entries, files_scanned = detect_csharp_security(files, zone_map)
        return LangSecurityResult(entries=entries, files_scanned=files_scanned)

    def __init__(self):
        super().__init__(
            name="csharp",
            extensions=[".cs"],
            exclusions=CSHARP_FILE_EXCLUSIONS,
            default_src=".",
            build_dep_graph=build_csharp_dep_graph,
            entry_patterns=CSHARP_ENTRY_PATTERNS,
            barrel_names={"Program.cs"},
            phases=[
                DetectorPhase("Structural analysis", _phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", _phase_coupling),
                *all_treesitter_phases("csharp"),
                detector_phase_signature(),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=get_area,
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
            holistic_review_dimensions=CSHARP_HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=CSHARP_MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=CSHARP_MIGRATION_MIXED_EXTENSIONS,
            extract_functions=_extract_csharp_functions,
            zone_rules=CSHARP_ZONE_RULES,
        )
