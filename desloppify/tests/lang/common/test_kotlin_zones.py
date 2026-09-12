"""Regression tests for Kotlin/Gradle zone classification.

Kotlin projects are organised by Gradle source sets rather than a top-level
``test/`` directory, so the common rules classify every test file as production.
"""

from __future__ import annotations

import pytest

from desloppify.engine.policy.zones import Zone, classify_file
from desloppify.languages.kotlin._zones import KOTLIN_ZONE_RULES


def _zone(rel_path: str) -> Zone:
    return classify_file(rel_path, KOTLIN_ZONE_RULES)


@pytest.mark.parametrize(
    "rel_path",
    [
        # Kotlin Multiplatform source sets
        "shared/src/commonTest/kotlin/com/example/FormEngineTest.kt",
        "sync/src/jvmTest/kotlin/com/example/SubmissionStoreTest.kt",
        "sync/src/iosTest/kotlin/com/example/DeviceCryptoTest.kt",
        "composeApp/src/androidUnitTest/kotlin/com/example/RendererTest.kt",
        "shared/src/nativeTest/kotlin/com/example/ParserTest.kt",
        # Plain Gradle JVM / Android layouts
        "app/src/test/java/com/example/HelperTest.kt",
        "app/src/androidTest/java/com/example/LoginFlowTest.kt",
        "lib/src/testFixtures/kotlin/com/example/Fixtures.kt",
    ],
)
def test_gradle_test_source_sets_are_test_zone(rel_path):
    assert _zone(rel_path) == Zone.TEST


@pytest.mark.parametrize(
    "rel_path",
    [
        "shared/src/commonMain/kotlin/com/example/FormEngine.kt",
        "sync/src/jvmMain/kotlin/com/example/SubmissionStore.kt",
        "composeApp/src/androidMain/kotlin/com/example/Renderer.kt",
        "composeApp/src/iosMain/kotlin/com/example/MapSeam.ios.kt",
    ],
)
def test_main_source_sets_stay_production(rel_path):
    assert _zone(rel_path) == Zone.PRODUCTION


@pytest.mark.parametrize(
    "rel_path",
    [
        "build.gradle.kts",
        "settings.gradle.kts",
        "androidApp/build.gradle.kts",
        "gradle.properties",
        "gradle/libs.versions.toml",
    ],
)
def test_gradle_build_files_are_config_zone(rel_path):
    assert _zone(rel_path) == Zone.CONFIG


def test_latest_is_not_mistaken_for_a_test_source_set():
    """A directory merely ending in 'Test' must still need the source-set suffix."""
    assert _zone("shared/src/commonMain/kotlin/com/example/LatestKotlinThing.kt") == Zone.PRODUCTION
