"""Normal package imports must survive scanning a larger enclosing project."""

import importlib
import sys

import pytest

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine.detectors.coverage.mapping import import_based_mapping
from desloppify.languages.python.detectors.deps import build_dep_graph
from desloppify.languages.python.detectors.deps_dynamic import (
    find_python_dynamic_imports,
)
from desloppify.languages.python.detectors.deps_resolution import (
    resolve_python_from_import,
    resolve_python_import,
)


def write(root, relative, content=""):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.fixture(params=[True, False], ids=["regular", "namespace"])
def nested_package(tmp_path, request):
    if request.param:
        write(tmp_path, "tools/fixture_package/__init__.py")
    worker = write(tmp_path, "tools/fixture_package/worker.py", "VALUE = 7\n")
    consumer = write(tmp_path, "tools/fixture_package/consumer.py")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        yield tmp_path, worker, consumer


@pytest.mark.parametrize("scan_subtree", [False, True])
@pytest.mark.parametrize("relative_source", [False, True])
def test_qualified_import_resolves_from_nested_package(
    nested_package, scan_subtree, relative_source
):
    root, worker, consumer = nested_package
    scan_root = consumer.parent if scan_subtree else root
    source = str(consumer.relative_to(root)) if relative_source else str(consumer)

    assert resolve_python_import("fixture_package.worker", source, scan_root) == str(
        worker
    )


def test_graph_records_import_that_python_itself_can_execute(
    nested_package, monkeypatch
):
    root, worker, consumer = nested_package
    consumer.write_text("from fixture_package.worker import VALUE\n")
    monkeypatch.syspath_prepend(str(root / "tools"))
    assert "fixture_package" not in sys.modules
    try:
        assert importlib.import_module("fixture_package.consumer").VALUE == 7
        graph = build_dep_graph(root)
        assert str(worker) in graph[str(consumer)]["imports"]
        assert graph[str(worker)]["importer_count"] == 1
        assert import_based_mapping(
            graph, {str(consumer)}, {str(worker)}, "python"
        ) == {str(worker)}
    finally:
        for name in list(sys.modules):
            if name == "fixture_package" or name.startswith("fixture_package."):
                sys.modules.pop(name)


def test_qualified_from_import_maps_package_and_submodule(nested_package):
    root, worker, consumer = nested_package
    expected = {str(worker)}
    initializer = consumer.parent / "__init__.py"
    if initializer.exists():
        expected.add(str(initializer))
    assert (
        set(
            resolve_python_from_import("fixture_package", "worker", str(consumer), root)
        )
        == expected
    )


def test_literal_dynamic_import_uses_source_package_context(nested_package):
    root, worker, consumer = nested_package
    consumer.write_text(
        'import importlib\nimportlib.import_module("fixture_package.worker")\n'
    )
    assert find_python_dynamic_imports(root, [".py"]) == {str(worker)}


def test_project_root_precedence_is_preserved(nested_package):
    root, _, consumer = nested_package
    preferred = write(root, "fixture_package/worker.py", "VALUE = 11\n")
    assert resolve_python_import("fixture_package.worker", str(consumer), root) == str(
        preferred
    )


def test_bare_implicit_relative_import_is_still_rejected(nested_package):
    root, _, consumer = nested_package
    write(root, "tools/fixture_package/__init__.py")
    assert resolve_python_import("worker", str(consumer), root) is None


def test_unrelated_sibling_package_is_not_inferred(nested_package):
    root, _, consumer = nested_package
    write(root, "tools/other_package/__init__.py")
    write(root, "tools/other_package/worker.py")
    assert resolve_python_import("other_package.worker", str(consumer), root) is None


def test_multiple_matching_package_contexts_remain_unresolved(tmp_path):
    for relative in [
        "tools/repeated/__init__.py",
        "tools/repeated/repeated/__init__.py",
        "tools/repeated/worker.py",
        "tools/repeated/repeated/worker.py",
    ]:
        write(tmp_path, relative)
    consumer = write(tmp_path, "tools/repeated/repeated/consumer.py")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        assert resolve_python_import("repeated.worker", str(consumer), tmp_path) is None


@pytest.mark.parametrize("module", [".worker", "..worker"])
def test_explicit_relative_resolution_is_unchanged(nested_package, module):
    root, worker, consumer = nested_package
    if module.startswith(".."):
        write(root, "tools/fixture_package/sub/__init__.py")
        consumer = write(root, "tools/fixture_package/sub/consumer.py")
    assert resolve_python_import(module, str(consumer), root) == str(worker)


def test_package_context_does_not_escape_active_roots(nested_package):
    root, _, consumer = nested_package
    write(root, "tools/worker.py")
    with runtime_scope(RuntimeContext(project_root=root / "unrelated")):
        assert (
            resolve_python_import("tools.worker", str(consumer), consumer.parent)
            is None
        )
