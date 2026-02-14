"""Tests for C# dependency graph construction."""

from pathlib import Path

from desloppify.detectors.graph import detect_cycles
from desloppify.lang.csharp.detectors.deps import build_dep_graph


def _fixture_root(name: str) -> Path:
    return (Path("tests") / "fixtures" / "csharp" / name).resolve()


def test_build_dep_graph_simple_app():
    root = _fixture_root("simple_app")
    graph = build_dep_graph(root)

    program = str((root / "Program.cs").resolve())
    greeter = str((root / "Services" / "Greeter.cs").resolve())

    assert program in graph
    assert greeter in graph
    assert greeter in graph[program]["imports"]
    assert program in graph[greeter]["importers"]
    assert graph[greeter]["importer_count"] >= 1


def test_build_dep_graph_project_reference():
    root = _fixture_root("multi_project")
    graph = build_dep_graph(root)

    program = str((root / "App" / "Program.cs").resolve())
    helper = str((root / "Lib" / "Helper.cs").resolve())

    assert program in graph
    assert helper in graph
    assert helper in graph[program]["imports"]


def test_build_dep_graph_handles_cycles():
    root = _fixture_root("cyclic")
    graph = build_dep_graph(root)
    cycles, _ = detect_cycles(graph)
    assert len(cycles) >= 1
