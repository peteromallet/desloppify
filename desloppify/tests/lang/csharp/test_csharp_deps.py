"""Tests for C# dependency graph construction."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.engine.detectors.graph import detect_cycles
from desloppify.languages.csharp.detectors.deps import (
    _build_roslyn_command,
    build_dep_graph,
    resolve_roslyn_cmd_from_args,
)


def _fixture_root(name: str) -> Path:
    base = Path("desloppify") / "tests" / "fixtures" / "csharp"
    return (base / name).resolve()


def _edge_set_within_root(graph: dict[str, dict], root: Path) -> set[tuple[str, str]]:
    root_resolved = root.resolve()
    edges: set[tuple[str, str]] = set()
    for source, entry in graph.items():
        try:
            source_rel = Path(source).resolve().relative_to(root_resolved).as_posix()
        except (OSError, ValueError) as exc:
            _skip_reason = f"ignore source outside fixture root: {exc}"
            continue
        for target in entry.get("imports", set()):
            try:
                target_rel = (
                    Path(target).resolve().relative_to(root_resolved).as_posix()
                )
            except (OSError, ValueError) as exc:
                _skip_reason = f"ignore target outside fixture root: {exc}"
                continue
            edges.add((source_rel, target_rel))
    return edges


def _require_roslyn_payload(roslyn_cmd: str, root: Path):
    cmd = _build_roslyn_command(roslyn_cmd, root)
    assert cmd is not None
    proc = subprocess.run(
        cmd,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout or "{}")
    assert isinstance(payload, dict)
    assert "files" in payload or "edges" in payload


def test_resolve_roslyn_cmd_from_args_uses_runtime_options():
    args = SimpleNamespace(lang_runtime_options={"roslyn_cmd": "dotnet-roslyn --json"})
    assert resolve_roslyn_cmd_from_args(args) == "dotnet-roslyn --json"


def test_resolve_roslyn_cmd_from_args_returns_none_when_missing():
    args = SimpleNamespace(lang_runtime_options={})
    assert resolve_roslyn_cmd_from_args(args) is None


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


@pytest.mark.parametrize("namespace_style", ["file", "block"])
def test_build_dep_graph_resolves_same_namespace_type_references(tmp_path, namespace_style):
    def source(body):
        if namespace_style == "file":
            return f"namespace Demo.App;\n{body}\n"
        return f"namespace Demo.App {{\n{body}\n}}\n"

    program = tmp_path / "Program.cs"
    helper = tmp_path / "Rendering.cs"
    unused = tmp_path / "Unused.cs"
    program.write_text(source("class Program { Renderer renderer = new(); }"))
    helper.write_text(source("class Renderer {}"))
    unused.write_text(source("class Unused {}"))

    graph = build_dep_graph(tmp_path)

    assert str(helper) in graph[str(program)]["imports"]
    assert graph[str(helper)]["importers"] == {str(program)}
    assert graph[str(unused)]["importer_count"] == 0
    assert str(program) not in graph[str(helper)]["imports"]


def test_build_dep_graph_same_namespace_ignores_comments_and_literals(tmp_path):
    program = tmp_path / "Program.cs"
    program.write_text('''namespace Demo.App;
class Program {
    // Unused CommentType
    /* BlockType */
    string text = "StringType";
    string verbatim = @"VerbatimType ""Unused""";
    string raw = """RawType "Unused""";
}
''')
    for name in ["Unused", "CommentType", "BlockType", "StringType", "VerbatimType", "RawType"]:
        (tmp_path / f"{name}.cs").write_text(f"namespace Demo.App;\nclass {name} {{}}")

    graph = build_dep_graph(tmp_path)

    assert graph[str(program)]["imports"] == set()


def test_build_dep_graph_same_namespace_respects_project_references(tmp_path):
    paths = {}
    for name in ["App", "Referenced", "Unreferenced"]:
        directory = tmp_path / name
        directory.mkdir()
        paths[name] = directory
        references = '<ItemGroup><ProjectReference Include="../Referenced/Referenced.csproj" /></ItemGroup>' if name == "App" else ""
        (directory / f"{name}.csproj").write_text(f'<Project Sdk="Microsoft.NET.Sdk">{references}</Project>')
    program = paths["App"] / "Program.cs"
    program.write_text("namespace Shared;\nclass Program { Helper helper; Unavailable unavailable; }")
    helper = paths["Referenced"] / "Helper.cs"
    helper.write_text("namespace Shared;\nclass Helper {}")
    unavailable = paths["Unreferenced"] / "Unavailable.cs"
    unavailable.write_text("namespace Shared;\nclass Unavailable {}")

    graph = build_dep_graph(tmp_path)

    assert str(helper) in graph[str(program)]["imports"]
    assert str(unavailable) not in graph[str(program)]["imports"]


@pytest.mark.parametrize("directive", ["using static Demo.App.Palette;", "using Colors = Demo.App.Palette;"])
def test_build_dep_graph_type_using_does_not_import_entire_namespace(tmp_path, directive):
    program = tmp_path / "Program.cs"
    palette = tmp_path / "Palette.cs"
    unused = tmp_path / "Unused.cs"
    program.write_text(f"{directive}\nnamespace Demo.Client;\nclass Program {{}}")
    palette.write_text("namespace Demo.App;\nstatic class Palette {}")
    unused.write_text("namespace Demo.App;\nclass Unused {}")

    graph = build_dep_graph(tmp_path)

    assert graph[str(program)]["imports"] == {str(palette)}
    assert graph[str(unused)]["importer_count"] == 0


@pytest.mark.parametrize("unused_name", ["Unused", "Services"])
def test_build_dep_graph_namespace_using_requires_referenced_symbol(tmp_path, unused_name):
    program = tmp_path / "Program.cs"
    helper = tmp_path / "Helper.cs"
    unused = tmp_path / f"{unused_name}.cs"
    program.write_text('''using Demo.Services;
namespace Demo.App;
class Program {
    Helper helper = new();
    // Unused
    string label = "Unused";
}
''')
    helper.write_text("namespace Demo.Services;\nclass Helper {}")
    unused.write_text(f"namespace Demo.Services;\nclass {unused_name} {{}}")

    graph = build_dep_graph(tmp_path)

    assert graph[str(program)]["imports"] == {str(helper)}
    assert graph[str(unused)]["importer_count"] == 0


def test_build_dep_graph_namespace_using_preserves_extension_method_reference(tmp_path):
    program = tmp_path / "Program.cs"
    extension = tmp_path / "TextExtensions.cs"
    unused = tmp_path / "Unused.cs"
    program.write_text('''using Demo.Extensions;
namespace Demo.App;
class Program { string text = "example".NormalizeText(); }
''')
    extension.write_text('''namespace Demo.Extensions;
static class TextExtensions {
    public static string NormalizeText(this string value) => value.Trim();
}
''')
    unused.write_text("namespace Demo.Extensions;\nclass Unused {}")

    graph = build_dep_graph(tmp_path)

    assert graph[str(program)]["imports"] == {str(extension)}
    assert graph[str(unused)]["importer_count"] == 0


def test_build_dep_graph_namespace_using_preserves_attribute_shorthand(tmp_path):
    program = tmp_path / "Program.cs"
    attribute = tmp_path / "MarkAttribute.cs"
    program.write_text("using Demo.Attributes;\nnamespace Demo.App;\n[Mark] class Program {}")
    attribute.write_text("namespace Demo.Attributes;\nclass MarkAttribute : System.Attribute {}")

    graph = build_dep_graph(tmp_path)

    assert graph[str(program)]["imports"] == {str(attribute)}


@pytest.mark.parametrize("declaration", ["class", "struct", "interface", "enum", "record", "record class", "record struct"])
def test_build_dep_graph_same_namespace_supports_type_declarations(tmp_path, declaration):
    program = tmp_path / "Program.cs"
    helper = tmp_path / "Helpers.cs"
    program.write_text("namespace Demo;\nclass Program { Helper helper; }")
    helper.write_text(f"namespace Demo;\n{declaration} Helper {{}}")

    graph = build_dep_graph(tmp_path)

    assert str(helper) in graph[str(program)]["imports"]


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


def test_build_dep_graph_uses_project_assets_for_transitive_project_references(
    tmp_path,
):
    app_dir = tmp_path / "App"
    lib_dir = tmp_path / "Lib"
    core_dir = tmp_path / "Core"
    app_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)
    core_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "App.csproj").write_text(
        "\n".join(
            [
                '<Project Sdk="Microsoft.NET.Sdk">',
                "  <ItemGroup>",
                '    <ProjectReference Include="..\\Lib\\Lib.csproj" />',
                "  </ItemGroup>",
                "</Project>",
            ]
        )
    )
    (lib_dir / "Lib.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
    (core_dir / "Core.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')

    program = app_dir / "Program.cs"
    helper = lib_dir / "Helper.cs"
    core_file = core_dir / "CoreService.cs"
    program.write_text(
        "\n".join(["using Demo.Core;", "namespace Demo.App;", "class Program { CoreService service; }"])
    )
    helper.write_text("\n".join(["namespace Demo.Lib;", "class Helper {}"]))
    core_file.write_text("\n".join(["namespace Demo.Core;", "class CoreService {}"]))

    graph_without_assets = build_dep_graph(tmp_path)
    program_key = str(program.resolve())
    core_key = str(core_file.resolve())
    assert core_key not in graph_without_assets[program_key]["imports"]

    assets_file = app_dir / "obj" / "project.assets.json"
    assets_file.parent.mkdir(parents=True, exist_ok=True)
    assets_file.write_text(
        json.dumps(
            {
                "libraries": {
                    "Lib/1.0.0": {"type": "project", "path": "../Lib/Lib.csproj"},
                    "Core/1.0.0": {"type": "project", "path": "../Core/Core.csproj"},
                }
            }
        )
    )

    graph_with_assets = build_dep_graph(tmp_path)
    assert core_key in graph_with_assets[program_key]["imports"]


def test_build_dep_graph_ignores_invalid_project_assets_json(tmp_path):
    app_dir = tmp_path / "App"
    lib_dir = tmp_path / "Lib"
    app_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "App.csproj").write_text(
        "\n".join(
            [
                '<Project Sdk="Microsoft.NET.Sdk">',
                "  <ItemGroup>",
                '    <ProjectReference Include="..\\Lib\\Lib.csproj" />',
                "  </ItemGroup>",
                "</Project>",
            ]
        )
    )
    (lib_dir / "Lib.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')

    program = app_dir / "Program.cs"
    helper = lib_dir / "Helper.cs"
    program.write_text(
        "\n".join(["using Demo.Lib;", "namespace Demo.App;", "class Program { Helper helper; }"])
    )
    helper.write_text("\n".join(["namespace Demo.Lib;", "class Helper {}"]))

    assets_file = app_dir / "obj" / "project.assets.json"
    assets_file.parent.mkdir(parents=True, exist_ok=True)
    assets_file.write_text("{not-json")

    graph = build_dep_graph(tmp_path)
    program_key = str(program.resolve())
    helper_key = str(helper.resolve())
    assert helper_key in graph[program_key]["imports"]


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
        "desloppify.languages.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _Proc(),
    )

    graph = build_dep_graph(tmp_path)

    assert str(source) in graph
    assert str(target) in graph
    assert str(target) in graph[str(source)]["imports"]


def test_build_dep_graph_roslyn_invokes_subprocess_without_shell(tmp_path, monkeypatch):
    source = (tmp_path / "Program.cs").resolve()
    payload = json.dumps({"files": [{"file": str(source), "imports": []}]}).encode(
        "utf-8"
    )

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
    monkeypatch.setattr(
        "desloppify.languages.csharp.detectors.deps.subprocess.run", _fake_run
    )

    build_dep_graph(tmp_path)

    assert "args" in captured
    cmd = captured["args"][0]
    kwargs = captured["kwargs"]
    assert isinstance(cmd, list)
    assert kwargs["shell"] is False
    assert kwargs["text"] is False
    assert kwargs["timeout"] >= 1
    assert cmd[-1] == str(tmp_path)


def test_build_dep_graph_prefers_explicit_roslyn_cmd_over_env(tmp_path, monkeypatch):
    source = (tmp_path / "Program.cs").resolve()
    payload = json.dumps({"files": [{"file": str(source), "imports": []}]}).encode(
        "utf-8"
    )

    class _Proc:
        returncode = 0
        stdout = payload
        stderr = b""

    captured: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "env-roslyn --json")
    monkeypatch.setattr(
        "desloppify.languages.csharp.detectors.deps.subprocess.run", _fake_run
    )

    build_dep_graph(tmp_path, roslyn_cmd="explicit-roslyn --json")

    cmd = captured["args"][0]
    assert isinstance(cmd, list)
    assert cmd[0] == "explicit-roslyn"
    assert "env-roslyn" not in " ".join(cmd)


def test_build_dep_graph_falls_back_when_roslyn_command_fails(tmp_path, monkeypatch):
    program = tmp_path / "Program.cs"
    service = tmp_path / "Services" / "Greeter.cs"
    service.parent.mkdir(parents=True, exist_ok=True)
    program.write_text(
        "\n".join(["using Demo.Services;", "namespace DemoApp;", "class Program { Greeter greeter; }"])
    )
    service.write_text("\n".join(["namespace Demo.Services;", "class Greeter {}"]))

    class _ProcFail:
        returncode = 1
        stdout = b""
        stderr = b"failed"

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn")
    monkeypatch.setattr(
        "desloppify.languages.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _ProcFail(),
    )

    graph = build_dep_graph(tmp_path)

    program_key = str(program.resolve())
    service_key = str(service.resolve())
    assert program_key in graph
    assert service_key in graph
    assert service_key in graph[program_key]["imports"]


def test_build_dep_graph_uses_fallback_when_roslyn_payload_too_large(
    tmp_path, monkeypatch
):
    program = tmp_path / "Program.cs"
    service = tmp_path / "Services" / "Greeter.cs"
    service.parent.mkdir(parents=True, exist_ok=True)
    program.write_text(
        "\n".join(["using Demo.Services;", "namespace DemoApp;", "class Program { Greeter greeter; }"])
    )
    service.write_text("\n".join(["namespace Demo.Services;", "class Greeter {}"]))

    class _ProcLarge:
        returncode = 0
        stdout = b"{" + b"x" * 2048 + b"}"
        stderr = b""

    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", "fake-roslyn")
    monkeypatch.setenv("DESLOPPIFY_CSHARP_ROSLYN_MAX_OUTPUT_BYTES", "128")
    monkeypatch.setattr(
        "desloppify.languages.csharp.detectors.deps.subprocess.run",
        lambda *args, **kwargs: _ProcLarge(),
    )

    graph = build_dep_graph(tmp_path)
    program_key = str(program.resolve())
    service_key = str(service.resolve())
    assert program_key in graph
    assert service_key in graph
    assert service_key in graph[program_key]["imports"]


def test_build_dep_graph_roslyn_integration_when_command_is_configured(
    tmp_path, monkeypatch
):
    roslyn_cmd = os.environ.get("DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD")
    if not roslyn_cmd:
        pytest.skip(
            "Set DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD to run Roslyn integration test"
        )

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


def test_build_dep_graph_heuristic_matches_roslyn_simple_app(monkeypatch):
    roslyn_cmd = os.environ.get("DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD")
    if not roslyn_cmd:
        pytest.skip("Set DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD to run parity tests")

    root = _fixture_root("simple_app")
    _require_roslyn_payload(roslyn_cmd, root)

    monkeypatch.delenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", raising=False)
    heuristic_graph = build_dep_graph(root)
    roslyn_graph = build_dep_graph(root, roslyn_cmd=roslyn_cmd)

    assert _edge_set_within_root(heuristic_graph, root) == _edge_set_within_root(
        roslyn_graph, root
    )


def test_build_dep_graph_heuristic_matches_roslyn_multi_project(monkeypatch):
    roslyn_cmd = os.environ.get("DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD")
    if not roslyn_cmd:
        pytest.skip("Set DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD to run parity tests")

    root = _fixture_root("multi_project")
    _require_roslyn_payload(roslyn_cmd, root)

    monkeypatch.delenv("DESLOPPIFY_CSHARP_ROSLYN_CMD", raising=False)
    heuristic_graph = build_dep_graph(root)
    roslyn_graph = build_dep_graph(root, roslyn_cmd=roslyn_cmd)

    assert _edge_set_within_root(heuristic_graph, root) == _edge_set_within_root(
        roslyn_graph, root
    )
