"""Dependency graph edges retain the discovered files' path spelling."""

from pathlib import Path

import pytest

from desloppify.languages._framework.generic_support.capabilities import (
    make_file_finder,
)
from desloppify.languages._framework.treesitter import is_available
from desloppify.languages._framework.treesitter.imports.graph import (
    make_ts_dep_builder,
    ts_build_dep_graph,
)
from desloppify.languages._framework.treesitter.specs.compiled import KOTLIN_SPEC
from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter-language-pack not installed"
)


@pytest.mark.parametrize("path_style", ["relative", "absolute", "dotted", "mixed"])
def test_javascript_edges_preserve_file_keys(tmp_path, monkeypatch, path_style):
    monkeypatch.chdir(tmp_path)
    public = tmp_path / "public"
    (public / "lib").mkdir(parents=True)
    (public / "main.js").write_text(
        "import { value } from './lib/../lib/value.js';\n"
        "import { external } from '../outside.js';\n"
        "export const result = value + external;\n"
    )
    (public / "lib/value.js").write_text("export const value = 1;\n")
    (tmp_path / "outside.js").write_text("export const external = 2;\n")
    files = ["public/main.js", "public/lib/value.js"]
    if path_style == "absolute":
        files = [str(tmp_path / file) for file in files]
    elif path_style == "dotted":
        files = [f"./{file}" for file in files]
    elif path_style == "mixed":
        files[1] = str(tmp_path / files[1])

    graph = ts_build_dep_graph(Path("public"), JS_SPEC, files)

    assert set(graph) == set(files)
    assert graph[files[0]]["imports"] == {files[1]}
    assert graph[files[1]]["importers"] == {files[0]}
    assert graph[files[0]]["import_count"] == 1
    assert graph[files[1]]["importer_count"] == 1


def test_generic_javascript_builder_connects_discovered_paths(
    tmp_path, monkeypatch, set_project_root
):
    monkeypatch.chdir(tmp_path)
    public = tmp_path / "public"
    public.mkdir()
    (public / "main.js").write_text("import { value } from './value.js';\n")
    (public / "value.js").write_text("export const value = 1;\n")
    builder = make_ts_dep_builder(JS_SPEC, make_file_finder([".js"]))

    graph = builder(Path("public"))

    assert graph["public/main.js"]["imports"] == {"public/value.js"}
    assert graph["public/value.js"]["importers"] == {"public/main.js"}


def test_kotlin_absolute_resolution_preserves_relative_file_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path("src/main/kotlin/example")
    source.mkdir(parents=True)
    main = source / "Main.kt"
    dependency = source / "Value.kt"
    main.write_text("package example\nimport example.Value\nclass Main\n")
    dependency.write_text("package example\nclass Value\n")

    graph = ts_build_dep_graph(tmp_path, KOTLIN_SPEC, [str(main), str(dependency)])

    assert graph[str(main)]["imports"] == {str(dependency)}
    assert graph[str(dependency)]["importers"] == {str(main)}
