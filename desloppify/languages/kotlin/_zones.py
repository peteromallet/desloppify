"""Zone/path classification rules for Kotlin.

Kotlin projects are laid out by Gradle source sets, not by a top-level ``test/``
directory. Kotlin Multiplatform in particular names every test source set
``<target>Test`` — ``src/commonTest/kotlin``, ``src/jvmTest/kotlin``,
``src/iosTest/kotlin``, ``src/androidUnitTest/kotlin`` — none of which contain the
``/test/`` path segment the common rules look for. Without these rules every test
file is scored as production code.
"""

from __future__ import annotations

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule

KOTLIN_ZONE_RULES = [
    # Gradle/KMP test source sets: src/test/, src/androidTest/, src/commonTest/,
    # src/jvmTest/, src/iosTest/, src/androidUnitTest/, src/nativeTest/, ...
    # The pattern has no leading "." / trailing "_" so it matches as a path substring.
    ZoneRule(
        Zone.TEST,
        [
            "/src/test/",
            "/src/androidTest/",
            "/src/testFixtures/",
            "Test/kotlin/",
            "Test/java/",
            "Test/resources/",
        ],
    ),
    ZoneRule(Zone.GENERATED, ["/generated/", "/build/generated/"]),
    ZoneRule(
        Zone.CONFIG,
        [
            "build.gradle.kts",
            "settings.gradle.kts",
            "build.gradle",
            "settings.gradle",
            "gradle.properties",
            "gradle/libs.versions.toml",
        ],
    ),
] + COMMON_ZONE_RULES

__all__ = ["KOTLIN_ZONE_RULES"]
