"""Kotlin graph resolution follows declarations, not package-shaped filenames."""

from pathlib import Path

import pytest

from desloppify.languages._framework.treesitter import is_available
from desloppify.languages._framework.treesitter.imports.graph import ts_build_dep_graph
from desloppify.languages._framework.treesitter.specs.compiled import KOTLIN_SPEC

pytestmark = pytest.mark.skipif(not is_available(), reason="tree-sitter not installed")


def graph_for(tmp_path, monkeypatch, sources):
    monkeypatch.chdir(tmp_path)
    for name, text in sources.items():
        file = Path(name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    return ts_build_dep_graph(tmp_path, KOTLIN_SPEC, list(sources))


def test_explicit_imports_resolve_flat_multimodule_declarations(tmp_path, monkeypatch):
    source = "feature/ui/src/main/kotlin/Screen.kt"
    model = "core/data/src/main/kotlin/Records.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package ui\nimport data.Record as Row\nimport data.caption\nval row = Row()\n",
            model: 'package data\nclass Record\nfun Record.caption() = "row"\n',
        },
    )
    assert graph[source]["imports"] == {model}
    assert graph[model]["importers"] == {source}
    assert graph[source]["import_count"] == graph[model]["importer_count"] == 1


def test_same_package_types_and_constructors_connect_tests(tmp_path, monkeypatch):
    source = "core/data/src/test/kotlin/RepositoryTest.kt"
    implementation = "core/data/src/main/kotlin/Repository.kt"
    model = "core/data/src/main/kotlin/Values.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package data\nfun test(value: Snapshot): Unit {\n    DefaultRepository()\n}\n",
            implementation: "package data\nclass DefaultRepository\n",
            model: "package data\ntypealias Snapshot = String\n",
        },
    )
    assert graph[source]["imports"] == {implementation, model}
    assert graph[implementation]["imports"] == set()


def test_member_property_and_operator_imports_resolve_owning_file(
    tmp_path, monkeypatch
):
    source = "consumer/Use.kt"
    container = "model/Types.kt"
    properties = "model/Constants.kt"
    operators = "model/Extensions.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package consumer\nimport model.Box.Entry\nimport model.limit\nimport model.get\n",
            container: "package model\nclass Box {\n    class Entry\n}\n",
            properties: "package model\nval limit = 4\n",
            operators: "package model\noperator fun Box.get(i: Int) = i\n",
        },
    )
    assert graph[source]["imports"] == {container, properties, operators}


def test_star_import_only_connects_referenced_unique_types(tmp_path, monkeypatch):
    source = "Use.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package ui\nimport model.*\nfun use(row: Row) = row\n",
            "model/Rows.kt": "package model\nclass Row\n",
            "model/Unused.kt": "package model\nclass Unused\n",
        },
    )
    assert graph[source]["imports"] == {"model/Rows.kt"}


def test_import_alias_and_local_names_do_not_create_same_package_edges(
    tmp_path, monkeypatch
):
    source = "ui/Use.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package ui\nimport remote.External as Row\nfun use(RowFactory: () -> Unit) {\n    RowFactory()\n    Row()\n}\n",
            "remote/Types.kt": "package remote\nclass External\n",
            "ui/Row.kt": "package ui\nclass Row\n",
            "ui/Factory.kt": "package ui\nclass RowFactory\n",
        },
    )
    assert graph[source]["imports"] == {"remote/Types.kt"}


def test_ambiguous_declarations_and_member_calls_do_not_guess_edges(
    tmp_path, monkeypatch
):
    source = "Use.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package model\nfun use(other: Any) {\n    Duplicate()\n    other.Row()\n}\n",
            "one/Types.kt": "package model\nclass Duplicate\nclass Row\n",
            "two/Types.kt": "package model\nclass Duplicate\n",
        },
    )
    assert graph[source]["imports"] == set()


def test_private_declarations_comments_and_strings_are_not_dependencies(
    tmp_path, monkeypatch
):
    source = "Use.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: 'package model\n// Row()\nval text = "Row()"\nfun use() = Secret()\n',
            "Types.kt": "package model\nclass Row\nprivate class Secret\n",
        },
    )
    assert graph[source]["imports"] == set()


def test_unscanned_and_other_package_files_are_not_candidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("Excluded.kt").write_text("package model\nclass Missing\n")
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            "Use.kt": "package model\nimport model.Missing\nfun use() = Row()\n",
            "Other.kt": "package other\nclass Row\n",
        },
    )
    assert graph["Use.kt"]["imports"] == set()
    assert set(graph) == {"Use.kt", "Other.kt"}


def test_local_functions_type_parameters_and_nested_types_shadow_package_types(
    tmp_path, monkeypatch
):
    source = "Use.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package model\nfun Factory() = 1\nfun <Record> use(value: Record) = Factory()\nclass Host {\n    class Nested\n    fun make() = Nested()\n}\n",
            "Types.kt": "package model\nclass Factory\nclass Record\nclass Nested\n",
        },
    )
    assert graph[source]["imports"] == set()


def test_star_collisions_and_qualified_types_do_not_guess_edges(tmp_path, monkeypatch):
    source = "Use.kt"
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            source: "package ui\nimport one.*\nimport two.*\nfun use(row: Row, other: remote.Value) = row\n",
            "One.kt": "package one\nclass Row\n",
            "Two.kt": "package two\nclass Row\n",
            "Value.kt": "package ui\nclass Value\n",
        },
    )
    assert graph[source]["imports"] == set()


@pytest.mark.parametrize("path_style", ["absolute", "mixed", "dotted"])
def test_graph_preserves_discovered_file_keys(tmp_path, monkeypatch, path_style):
    monkeypatch.chdir(tmp_path)
    Path("Main.kt").write_text("package main\nimport model.Record\n")
    Path("Values.kt").write_text("package model\nclass Record\n")
    main, values = "Main.kt", "Values.kt"
    if path_style == "absolute":
        main, values = str(tmp_path / main), str(tmp_path / values)
    elif path_style == "mixed":
        values = str(tmp_path / values)
    else:
        main, values = "./Main.kt", "./Values.kt"
    graph = ts_build_dep_graph(tmp_path, KOTLIN_SPEC, [main, values])
    assert set(graph) == {main, values}
    assert graph[main]["imports"] == {values}
    assert graph[values]["importers"] == {main}


def test_index_is_rebuilt_for_each_discovered_inventory(tmp_path, monkeypatch):
    graph_for(
        tmp_path,
        monkeypatch,
        {
            "Main.kt": "package ui\nimport model.Record\n",
            "One.kt": "package model\nclass Record\n",
        },
    )
    Path("Two.kt").write_text("package model\nclass Record\n")
    graph = ts_build_dep_graph(tmp_path, KOTLIN_SPEC, ["Main.kt", "Two.kt"])
    assert graph["Main.kt"]["imports"] == {"Two.kt"}


def test_ambiguous_star_candidate_does_not_fall_through_to_other_package(
    tmp_path, monkeypatch
):
    graph = graph_for(
        tmp_path,
        monkeypatch,
        {
            "Use.kt": "package ui\nimport one.*\nimport two.*\nfun use(row: Row) = row\n",
            "One.kt": "package one\nclass Row\n",
            "Duplicate.kt": "package one\nclass Row\n",
            "Two.kt": "package two\nclass Row\n",
        },
    )
    assert graph["Use.kt"]["imports"] == set()
