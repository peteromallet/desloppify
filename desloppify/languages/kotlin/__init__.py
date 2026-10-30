"""Kotlin language plugin — ktlint, package-aware import graph."""

from desloppify.engine.policy.zones import Zone, ZoneRule
from desloppify.languages._framework.generic_support.core import generic_lang, generic_zone_rules
from desloppify.languages._framework.treesitter import KOTLIN_SPEC
from desloppify.languages.kotlin.deps import build_kotlin_dep_graph

KOTLIN_ZONE_RULES = [
    # Gradle Kotlin DSL scripts configure the build; they are not app code.
    ZoneRule(Zone.CONFIG, [".gradle.kts"]),
    # Android instrumented tests (src/androidTest) next to JVM tests (src/test).
    ZoneRule(Zone.TEST, ["/androidTest/", "/testFixtures/"]),
] + generic_zone_rules([".kt", ".kts"])

generic_lang(
    name="kotlin",
    extensions=[".kt", ".kts"],
    tools=[
        {
            "label": "ktlint",
            "cmd": "ktlint --reporter=json",
            "fmt": "json",
            "id": "ktlint_violation",
            "tier": 2,
            "fix_cmd": "ktlint --format",
        },
    ],
    exclude=["build"],
    depth="shallow",
    detect_markers=["build.gradle.kts", "build.gradle"],
    treesitter_spec=KOTLIN_SPEC,
    dep_graph_builder=build_kotlin_dep_graph,
    zone_rules=KOTLIN_ZONE_RULES,
    # Gradle build scripts are run by Gradle, never imported.
    entry_patterns=[".gradle.kts"],
)

__all__ = [
    "KOTLIN_ZONE_RULES",
    "generic_lang",
    "KOTLIN_SPEC",
]
