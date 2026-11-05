"""Dependency graph keys retain caller identity across path representations."""

from pathlib import Path

import pytest

from desloppify.languages._framework.treesitter import JS_SPEC
from desloppify.languages._framework.treesitter.imports.graph import ts_build_dep_graph


@pytest.mark.parametrize("key_style", ["absolute", "relative", "nested", "mixed"])
def test_graph_preserves_keys_and_scanned_boundary(
    monkeypatch, tmp_path: Path, key_style: str
) -> None:
    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    entry = source_dir / "entry.mjs"
    dependency = source_dir / "dependency.mjs"
    outside = source_dir / "outside.mjs"
    entry.write_text(
        "import { value } from './dependency.mjs';\n"
        "import './outside.mjs';\nexport const result = value;\n",
        encoding="utf-8",
    )
    dependency.write_text("export const value = 42;\n", encoding="utf-8")
    outside.write_text("export const outside = true;\n", encoding="utf-8")

    keys = [str(entry), str(dependency)]
    if key_style in {"relative", "nested", "mixed"}:
        keys[0] = str(entry.relative_to(tmp_path))
    if key_style in {"relative", "nested"}:
        keys[1] = str(dependency.relative_to(tmp_path))
    root = source_dir if key_style in {"absolute", "nested", "mixed"} else tmp_path

    graph = ts_build_dep_graph(root, JS_SPEC, keys)
    assert set(graph) == set(keys)
    assert graph[keys[0]]["imports"] == {keys[1]}
    assert graph[keys[0]]["import_count"] == 1
    assert graph[keys[1]]["importers"] == {keys[0]}
    assert graph[keys[1]]["importer_count"] == 1
    assert graph[keys[1]]["imports"] == set()
