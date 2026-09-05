"""Tests for GDScript zone classification and test-to-source mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.engine.policy.zones import Zone, classify_file
from desloppify.languages.gdscript import GDSCRIPT_ZONE_RULES
from desloppify.languages.gdscript.test_coverage import (
    parse_test_import_specs,
    resolve_import_spec,
)


def _zone(rel_path: str) -> Zone:
    return classify_file(rel_path, GDSCRIPT_ZONE_RULES)


@pytest.mark.parametrize(
    "rel_path",
    [
        "Game/Tests/netplay_tests.gd",
        "Game/tests/netplay_tests.gd",
        "Game/Tests/av_suite.gd",
        "Game/Scripts/rope_tests.gd",
    ],
)
def test_godot_suites_are_test_zone(rel_path: str) -> None:
    assert _zone(rel_path) is Zone.TEST


@pytest.mark.parametrize(
    "rel_path",
    [
        # Builds an in-game scene; `test_` is not a Godot test convention.
        "Game/Scripts/test_scene_builder.gd",
        "Game/Scripts/Audio/spatial_audio_emitter.gd",
    ],
)
def test_production_scripts_stay_production(rel_path: str) -> None:
    assert _zone(rel_path) is Zone.PRODUCTION


class TestClassNameCoverageMapping:
    """A suite references what it covers by global class_name, not by import."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        root = tmp_path / "Game"
        (root / "Scripts").mkdir(parents=True)
        (root / "Tests").mkdir(parents=True)
        (root / "project.godot").write_text("[application]\n")
        (root / "Scripts" / "emitter.gd").write_text("class_name Emitter\nextends Node\n")
        return root

    def _production(self, project: Path) -> set[str]:
        return {str((project / "Scripts" / "emitter.gd").resolve())}

    def test_bare_class_name_resolves_to_its_file(self, project: Path) -> None:
        resolved = resolve_import_spec(
            "Emitter",
            str(project / "Tests" / "audio_tests.gd"),
            self._production(project),
        )
        assert resolved == str((project / "Scripts" / "emitter.gd").resolve())

    def test_unknown_class_name_resolves_to_nothing(self, project: Path) -> None:
        assert (
            resolve_import_spec(
                "NotAThing",
                str(project / "Tests" / "audio_tests.gd"),
                self._production(project),
            )
            is None
        )

    def test_specs_include_class_names_and_paths(self) -> None:
        specs = parse_test_import_specs(
            'extends Node\n'
            'const P = preload("res://Scripts/other.gd")\n'
            'var e := Emitter.new()\n'
        )
        assert "res://Scripts/other.gd" in specs
        assert "Emitter" in specs

    def test_class_named_only_in_a_comment_or_string_is_not_a_spec(self) -> None:
        specs = parse_test_import_specs(
            'extends Node\n# Emitter is discussed here\nvar s := "Emitter"\n'
        )
        assert "Emitter" not in specs
