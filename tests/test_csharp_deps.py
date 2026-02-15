"""Tests for C# dependency graph construction."""

import json
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


def test_build_dep_graph_marks_platform_entrypoint_as_referenced(tmp_path):
    app_delegate = tmp_path / "Platforms" / "iOS" / "AppDelegate.cs"
    app_delegate.parent.mkdir(parents=True, exist_ok=True)
    app_delegate.write_text(
        "\n".join(
            [
                "using Foundation;",
                "using UIKit;",
                "namespace DemoApp;",
                '[Register("AppDelegate")]',
                "public class AppDelegate : UIApplicationDelegate {}",
            ]
        )
    )

    graph = build_dep_graph(tmp_path)
    app_delegate_key = str(app_delegate.resolve())

    assert app_delegate_key in graph
    assert graph[app_delegate_key]["importer_count"] >= 1


def test_build_dep_graph_uses_roslyn_payload_when_available(tmp_path, monkeypatch):
    source = (tmp_path / "Program.cs").resolve()
    target = (tmp_path / "Services" / "Greeter.cs").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    class _Proc:
        returncode = 0
        stdout = json.dumps(
            {
                "files": [
                    {"file": str(source), "imports": [str(target)]},
                    {"file": str(target), "imports": []},
                ]
            }
        )
        stderr = ""

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn")
    monkeypatch.setattr(
        "desloppify.lang.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _Proc(),
    )

    graph = build_dep_graph(tmp_path)

    assert str(source) in graph
    assert str(target) in graph
    assert str(target) in graph[str(source)]["imports"]


def test_build_dep_graph_falls_back_when_roslyn_command_fails(tmp_path, monkeypatch):
    program = tmp_path / "Program.cs"
    service = tmp_path / "Services" / "Greeter.cs"
    service.parent.mkdir(parents=True, exist_ok=True)
    program.write_text("\n".join(["using Demo.Services;", "namespace DemoApp;", "class Program {}"]))
    service.write_text("\n".join(["namespace Demo.Services;", "class Greeter {}"]))

    class _ProcFail:
        returncode = 1
        stdout = ""
        stderr = "failed"

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn")
    monkeypatch.setattr(
        "desloppify.lang.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _ProcFail(),
    )

    graph = build_dep_graph(tmp_path)

    program_key = str(program.resolve())
    service_key = str(service.resolve())
    assert program_key in graph
    assert service_key in graph
    assert service_key in graph[program_key]["imports"]
