"""Tests for GDScript dependency graph parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.gdscript.detectors.deps import build_dep_graph


def _write(path: Path, relpath: str, content: str) -> Path:
    file_path = path / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def test_build_dep_graph_resolves_preload_load_and_extends(tmp_path):
    _write(tmp_path, "project.godot", "[application]\nconfig/name=\"Demo\"\n")
    main = _write(
        tmp_path,
        "src/main.gd",
        (
            "extends \"res://src/base.gd\"\n"
            "var helper = preload(\"res://src/helper.gd\")\n"
            "func _ready():\n"
            "    var inst = load(\"res://src/helper.gd\")\n"
        ),
    )
    base = _write(tmp_path, "src/base.gd", "extends Node\n")
    helper = _write(tmp_path, "src/helper.gd", "extends RefCounted\n")

    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        graph = build_dep_graph(tmp_path / "src")

    main_key = str(main.resolve())
    base_key = str(base.resolve())
    helper_key = str(helper.resolve())
    assert graph[main_key]["imports"] == {base_key, helper_key}
    assert graph[base_key]["importers"] == {main_key}
    assert graph[helper_key]["importers"] == {main_key}


def test_build_dep_graph_ignores_non_gd_paths(tmp_path):
    _write(tmp_path, "project.godot", "[application]\n")
    main = _write(
        tmp_path,
        "src/main.gd",
        'var tex = load("res://assets/icon.png")\n',
    )

    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        graph = build_dep_graph(tmp_path / "src")

    main_key = str(main.resolve())
    assert graph[main_key]["imports"] == set()
