from __future__ import annotations

import json
from pathlib import Path

from desloppify.languages.cxx._helpers import build_cxx_dep_graph


def _write(root: Path, rel_path: str, content: str) -> Path:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_build_dep_graph_from_compile_commands(tmp_path):
    source = _write(
        tmp_path,
        "src/main.cpp",
        '#include "generated.hpp"\nint main() { return 0; }\n',
    )
    header = _write(tmp_path, "generated/generated.hpp", "#pragma once\n")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "src/main.cpp",
                    "command": "clang++ -Igenerated -c src/main.cpp",
                }
            ]
        )
    )

    graph = build_cxx_dep_graph(tmp_path)

    assert str(source.resolve()) in graph
    assert str(header.resolve()) in graph[str(source.resolve())]["imports"]


def test_build_dep_graph_distinguishes_angle_vs_quoted_include_resolution(tmp_path):
    source = _write(
        tmp_path,
        "src/main.cpp",
        '#include <widget.hpp>\n#include "widget_local.hpp"\nint main() { return answer() + local_answer(); }\n',
    )
    local_header = _write(
        tmp_path,
        "src/widget_local.hpp",
        "#pragma once\ninline int local_answer() { return 1; }\n",
    )
    include_header = _write(
        tmp_path,
        "include/widget.hpp",
        "#pragma once\ninline int answer() { return 42; }\n",
    )
    _write(
        tmp_path,
        "src/widget.hpp",
        "#pragma once\ninline int answer() { return -1; }\n",
    )
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "src/main.cpp",
                    "command": "clang++ -Iinclude -c src/main.cpp",
                }
            ]
        )
    )

    graph = build_cxx_dep_graph(tmp_path)

    imports = graph[str(source.resolve())]["imports"]
    assert str(include_header.resolve()) in imports
    assert str(local_header.resolve()) in imports
    assert str((tmp_path / "src" / "widget.hpp").resolve()) not in imports


def test_compile_database_expands_response_files_and_follows_header_includes(tmp_path):
    source = _write(tmp_path, "src/unit.cpp", '#include "Public/api.hpp"\n')
    public = _write(
        tmp_path, "module/Public/api.hpp", '#include "Detail/implementation.hpp"\n'
    )
    detail = _write(
        tmp_path, "module/Detail/implementation.hpp", '#include "Public/api.hpp"\n'
    )
    (tmp_path / "nested.rsp").write_text('-I "module"')
    (tmp_path / "compile.rsp").write_text("@nested.rsp -c src/unit.cpp")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(source),
                    "command": "clang++ @compile.rsp",
                },
            ]
        )
    )
    graph = build_cxx_dep_graph(tmp_path)
    assert graph[str(source.resolve())]["imports"] == {str(public.resolve())}
    assert graph[str(public.resolve())]["imports"] == {str(detail.resolve())}
    assert graph[str(detail.resolve())]["imports"] == {str(public.resolve())}


def test_response_file_cycles_and_missing_files_do_not_invent_includes(tmp_path):
    from desloppify.languages.cxx.detectors.deps import _parse_command_tokens

    (tmp_path / "a.rsp").write_text("@b.rsp -Iinclude")
    (tmp_path / "b.rsp").write_text("@a.rsp -DVALUE=1")
    tokens = _parse_command_tokens(
        {"directory": str(tmp_path), "arguments": ["clang++", "@a.rsp", "@missing.rsp"]}
    )
    assert tokens == ["clang++", "-DVALUE=1", "-Iinclude", "@missing.rsp"]


def test_shared_header_keeps_each_translation_units_include_context(tmp_path):
    first = _write(tmp_path, "first.cpp", '#include "api.hpp"\n')
    second = _write(tmp_path, "second.cpp", '#include "api.hpp"\n')
    public = _write(tmp_path, "common/api.hpp", "#include <config.hpp>\n")
    first_config = _write(tmp_path, "one/config.hpp", "#pragma once\n")
    second_config = _write(tmp_path, "two/config.hpp", "#pragma once\n")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(first),
                    "arguments": ["clang++", "-Icommon", "-Ione", "-c", str(first)],
                },
                {
                    "directory": str(tmp_path),
                    "file": str(second),
                    "arguments": ["clang++", "-Icommon", "-Itwo", "-c", str(second)],
                },
            ]
        )
    )
    graph = build_cxx_dep_graph(tmp_path)
    assert graph[str(public.resolve())]["imports"] == {
        str(first_config.resolve()),
        str(second_config.resolve()),
    }
