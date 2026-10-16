"""Integration coverage for JavaScript dependency edges used by orphan detection."""
from pathlib import Path

import pytest

from desloppify.languages._framework.treesitter import JS_SPEC
from desloppify.languages._framework.treesitter.imports.graph import ts_build_dep_graph


@pytest.mark.parametrize('statement', [
    "import { value } from './dep';",
    "const { value } = require('./dep');",
    "const result = import('./dep');",
    "export { value } from './dep';",
])
@pytest.mark.parametrize('relative_paths', [True, False])
def test_local_javascript_edges(tmp_path, monkeypatch, statement, relative_paths):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'src' / 'main.js'
    dependency = tmp_path / 'src' / 'dep.js'
    source.parent.mkdir()
    source.write_text(statement)
    dependency.write_text('export const value = 1;')
    files = [str(p.relative_to(tmp_path)) if relative_paths else str(p) for p in (source, dependency)]

    graph = ts_build_dep_graph(Path('.'), JS_SPEC, files)
    assert graph[files[0]]['imports'] == {files[1]}
    assert graph[files[1]]['importers'] == {files[0]}
    assert graph[files[0]]['import_count'] == 1
    assert graph[files[1]]['importer_count'] == 1


def test_arbitrary_calls_do_not_create_import_edges(tmp_path):
    source = tmp_path / 'main.js'
    dependency = tmp_path / 'dep.js'
    source.write_text("readFile('./dep'); require('external'); require(variable);")
    dependency.write_text('module.exports = 1;')
    graph = ts_build_dep_graph(tmp_path, JS_SPEC, [str(source), str(dependency)])
    assert graph[str(source)]['imports'] == set()
