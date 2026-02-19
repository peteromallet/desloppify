"""Tests for GDScript test-coverage language hooks."""

from __future__ import annotations

import desloppify.languages.gdscript.test_coverage as gd_cov


def test_strip_test_markers_for_gdscript():
    assert gd_cov.strip_test_markers("test_player.gd") == "player.gd"
    assert gd_cov.strip_test_markers("player_test.gd") == "player.gd"
    assert gd_cov.strip_test_markers("player.gd") is None


def test_parse_test_import_specs_extracts_res_paths():
    content = (
        'extends "res://tests/base_test.gd"\n'
        'var helper = preload("res://src/helper.gd")\n'
        'var enemy = load("res://src/enemy.gd")\n'
    )
    specs = gd_cov.parse_test_import_specs(content)
    assert "res://tests/base_test.gd" in specs
    assert "res://src/helper.gd" in specs
    assert "res://src/enemy.gd" in specs


def test_resolve_import_spec_maps_res_url_to_file(tmp_path):
    (tmp_path / "project.godot").write_text("[application]\n")
    script = tmp_path / "src" / "player.gd"
    script.parent.mkdir(parents=True)
    script.write_text("extends Node\n")
    test_file = tmp_path / "tests" / "test_player.gd"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("extends Node\n")

    production = {str(script.resolve())}
    resolved = gd_cov.resolve_import_spec(
        "res://src/player.gd", str(test_file), production
    )
    assert resolved == str(script.resolve())


def test_map_test_to_source_prefers_sibling_script(tmp_path):
    source = tmp_path / "tests" / "player.gd"
    source.parent.mkdir(parents=True)
    source.write_text("extends Node\n")
    test_file = tmp_path / "tests" / "test_player.gd"
    test_file.write_text("extends Node\n")
    production = {str(source.resolve())}
    mapped = gd_cov.map_test_to_source(str(test_file), production)
    assert mapped == str(source.resolve())
