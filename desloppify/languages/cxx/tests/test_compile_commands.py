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


def test_compile_database_marks_only_actual_translation_unit_roots(tmp_path):
    compiled = _write(tmp_path, "compiled/unit.cpp", "int compiled() { return 1; }\n")
    unused = _write(tmp_path, "unused/unit.cpp", "int unused() { return 0; }\n")
    header = _write(tmp_path, "include/pch.hpp", "#pragma once\n")
    malformed = _write(tmp_path, "missing-command.cpp", "int missing() { return 0; }\n")
    (tmp_path / "compile_commands.json").write_text(json.dumps([
        {"directory": str(tmp_path), "file": str(compiled), "arguments": ["clang++", "-c", str(compiled)]},
        {"directory": str(tmp_path), "file": str(header), "command": f"clang++ -x c++-header {header}"},
        {"directory": str(tmp_path), "file": str(malformed)},
    ]))
    graph = build_cxx_dep_graph(tmp_path)
    assert graph[str(compiled.resolve())]["is_entry_point"] is True
    for path in (unused, header, malformed):
        assert not graph[str(path.resolve())].get("is_entry_point", False)
