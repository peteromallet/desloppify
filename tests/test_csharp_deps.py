"""Tests for C# dependency graph construction."""

import json
import os
from pathlib import Path

import pytest

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


def test_build_dep_graph_does_not_mark_random_platform_file_as_entrypoint(tmp_path):
    helper = tmp_path / "Platforms" / "iOS" / "Helper.cs"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(
        "\n".join(
            [
                "namespace DemoApp;",
                "public class Helper {}",
            ]
        )
    )

    graph = build_dep_graph(tmp_path)
    helper_key = str(helper.resolve())

    assert helper_key in graph
    assert graph[helper_key]["importer_count"] == 0


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
        ).encode("utf-8")
        stderr = b""

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn")
    monkeypatch.setattr(
        "desloppify.lang.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _Proc(),
    )

    graph = build_dep_graph(tmp_path)

    assert str(source) in graph
    assert str(target) in graph
    assert str(target) in graph[str(source)]["imports"]


def test_build_dep_graph_roslyn_invokes_subprocess_without_shell(tmp_path, monkeypatch):
    source = (tmp_path / "Program.cs").resolve()
    payload = json.dumps({"files": [{"file": str(source), "imports": []}]}).encode("utf-8")

    class _Proc:
        returncode = 0
        stdout = payload
        stderr = b""

    captured: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn --json")
    monkeypatch.setattr("desloppify.lang.csharp.detectors.deps.subprocess.run", _fake_run)

    build_dep_graph(tmp_path)

    assert "args" in captured
    cmd = captured["args"][0]
    kwargs = captured["kwargs"]
    assert isinstance(cmd, list)
    assert kwargs["shell"] is False
    assert kwargs["text"] is False
    assert kwargs["timeout"] >= 1
    assert cmd[-1] == str(tmp_path)


def test_build_dep_graph_falls_back_when_roslyn_command_fails(tmp_path, monkeypatch):
    program = tmp_path / "Program.cs"
    service = tmp_path / "Services" / "Greeter.cs"
    service.parent.mkdir(parents=True, exist_ok=True)
    program.write_text("\n".join(["using Demo.Services;", "namespace DemoApp;", "class Program {}"]))
    service.write_text("\n".join(["namespace Demo.Services;", "class Greeter {}"]))

    class _ProcFail:
        returncode = 1
        stdout = b""
        stderr = b"failed"

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


def test_build_dep_graph_uses_fallback_when_roslyn_payload_too_large(tmp_path, monkeypatch):
    program = tmp_path / "Program.cs"
    service = tmp_path / "Services" / "Greeter.cs"
    service.parent.mkdir(parents=True, exist_ok=True)
    program.write_text("\n".join(["using Demo.Services;", "namespace DemoApp;", "class Program {}"]))
    service.write_text("\n".join(["namespace Demo.Services;", "class Greeter {}"]))

    class _ProcLarge:
        returncode = 0
        stdout = b"{" + b"x" * 2048 + b"}"
        stderr = b""

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn")
    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_MAX_OUTPUT_BYTES", "128")
    monkeypatch.setattr(
        "desloppify.lang.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _ProcLarge(),
    )

    graph = build_dep_graph(tmp_path)
    program_key = str(program.resolve())
    service_key = str(service.resolve())
    assert program_key in graph
    assert service_key in graph
    assert service_key in graph[program_key]["imports"]


def test_build_dep_graph_roslyn_integration_when_command_is_configured(tmp_path, monkeypatch):
    roslyn_cmd = os.environ.get("DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD")
    if not roslyn_cmd:
        pytest.skip("Set DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD to run Roslyn integration test")

    (tmp_path / "Program.cs").write_text(
        "\n".join(
            [
                "using Demo.Services;",
                "namespace DemoApp;",
                "class Program { static void Main() { } }",
            ]
        )
    )
    svc = tmp_path / "Services"
    svc.mkdir(parents=True, exist_ok=True)
    (svc / "Greeter.cs").write_text(
        "\n".join(
            [
                "namespace Demo.Services;",
                "class Greeter {}",
            ]
        )
    )

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", roslyn_cmd)
    graph = build_dep_graph(tmp_path)

    assert isinstance(graph, dict)
    assert len(graph) >= 1
