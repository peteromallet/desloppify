"""Tests for the GDScript dependency graph builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.languages.gdscript.detectors.deps import (
    _find_project_root,
    build_dep_graph,
    find_gdscript_dynamic_imports,
)

_FILLER = "\t# filler\n" * 12


@pytest.fixture
def godot_repo(tmp_path: Path) -> Path:
    """A repo whose Godot project sits one directory down, as is common."""
    project = tmp_path / "Game"
    (project / "Scripts").mkdir(parents=True)
    (project / "Scenes").mkdir(parents=True)
    (project / "project.godot").write_text(
        '[autoload]\n\nNetworkManager="*res://Scripts/net.gd"\n'
    )
    (project / "Scripts" / "emitter.gd").write_text(
        "class_name Emitter\nextends Node\n\nfunc play() -> void:\n\tpass\n" + _FILLER
    )
    (project / "Scripts" / "audio.gd").write_text(
        "extends Node\n\nvar e: Emitter = Emitter.new()\n" + _FILLER
    )
    (project / "Scripts" / "preloader.gd").write_text(
        'extends Node\n\nconst E = preload("res://Scripts/emitter.gd")\n' + _FILLER
    )
    (project / "Scripts" / "net.gd").write_text(
        "extends Node\n\nfunc boot() -> void:\n\tpass\n" + _FILLER
    )
    (project / "Scripts" / "scene_only.gd").write_text(
        "extends Node\n\nfunc _ready() -> void:\n\tpass\n" + _FILLER
    )
    (project / "Scripts" / "dead.gd").write_text(
        "extends Node\n\nfunc nobody() -> void:\n\tpass\n" + _FILLER
    )
    (project / "Scripts" / "only_mentions.gd").write_text(
        'extends Node\n# Emitter named in a comment\nvar s := "Emitter"\n' + _FILLER
    )
    (project / "Scenes" / "room.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://Scripts/scene_only.gd" id="1_a"]\n\n'
        '[node name="Room" type="Node3D"]\n'
    )
    return tmp_path


def _importers(graph: dict, project_root: Path, name: str) -> set[str]:
    key = str((project_root / "Game" / "Scripts" / name).resolve())
    return {Path(p).name for p in graph[key]["importers"]}


def test_finds_project_root_in_a_subdirectory(godot_repo: Path) -> None:
    assert _find_project_root(godot_repo).name == "Game"


def test_finds_project_root_upward_from_inside(godot_repo: Path) -> None:
    assert _find_project_root(godot_repo / "Game" / "Scripts").name == "Game"


def test_class_name_reference_is_an_edge(godot_repo: Path) -> None:
    graph = build_dep_graph(godot_repo)
    assert "audio.gd" in _importers(graph, godot_repo, "emitter.gd")


def test_preload_reference_is_still_an_edge(godot_repo: Path) -> None:
    graph = build_dep_graph(godot_repo)
    assert "preloader.gd" in _importers(graph, godot_repo, "emitter.gd")


def test_class_name_in_a_comment_or_string_is_not_an_edge(godot_repo: Path) -> None:
    graph = build_dep_graph(godot_repo)
    assert "only_mentions.gd" not in _importers(graph, godot_repo, "emitter.gd")


def test_unreferenced_file_keeps_zero_importers(godot_repo: Path) -> None:
    graph = build_dep_graph(godot_repo)
    assert not _importers(graph, godot_repo, "dead.gd")


def test_scene_attached_and_autoload_scripts_are_dynamic_targets(
    godot_repo: Path,
) -> None:
    targets = find_gdscript_dynamic_imports(godot_repo, [".gd"])
    assert targets == {"Scripts/scene_only", "Scripts/net"}


def test_no_gdscript_files_yields_empty_graph(tmp_path: Path) -> None:
    assert build_dep_graph(tmp_path) == {}
