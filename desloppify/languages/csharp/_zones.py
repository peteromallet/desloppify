"""Zone/path and entrypoint patterns for C#/.NET projects."""

from __future__ import annotations

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule

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
    "/App.razor",
    "/Routes.razor",
    "/_Imports.razor",
    "/_ViewImports.cshtml",
    "/_ViewStart.cshtml",
    "/Properties/",
    "/Migrations/",
    ".g.cs",
    ".designer.cs",
]

CSHARP_ZONE_RULES = [
    ZoneRule(
        Zone.GENERATED,
        [".g.cs", ".designer.cs", ".razor.g.cs", ".cshtml.g.cs", "/obj/", "/bin/"],
    ),
    ZoneRule(Zone.TEST, [".Tests.cs", "Tests.cs", "Test.cs", "/Tests/", "/test/"]),
    ZoneRule(
        Zone.CONFIG,
        [
            "/Program.cs",
            "/Startup.cs",
            "/AssemblyInfo.cs",
            "/_Imports.razor",
            "/_ViewImports.cshtml",
            "/_ViewStart.cshtml",
        ],
    ),
] + COMMON_ZONE_RULES

__all__ = ["CSHARP_ENTRY_PATTERNS", "CSHARP_ZONE_RULES"]
