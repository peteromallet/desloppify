"""Import resolution for src-layout Python packages.

In the src layout — what PyPA recommends, and what hatchling's
`packages = ["src/mypkg"]` and setuptools' `package-dir = {"": "src"}`
produce — `import mypkg.thing` resolves to `src/mypkg/thing.py`. A resolver
that only tries the scan root and the project root finds nothing, which
leaves the whole dependency graph empty: every module reports zero importers,
so orphaned-file, coupling, cycle and single-use detection all go quiet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.base.discovery.source import find_py_files  # noqa: F401
from desloppify.languages.python.detectors.deps import build_dep_graph
from desloppify.languages.python.detectors.deps_resolution import (
    resolve_absolute_import,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture()
def src_layout_project(tmp_path, monkeypatch):
    """A minimal src-layout package: cli imports db, db imports nothing."""
    _write(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    _write(tmp_path / "src" / "demo" / "__init__.py", "")
    _write(
        tmp_path / "src" / "demo" / "db.py",
        "class Database:\n    pass\n",
    )
    _write(
        tmp_path / "src" / "demo" / "cli.py",
        "from demo.db import Database\n\n\ndef main():\n    return Database()\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "desloppify.languages.python.detectors.deps_resolution.get_project_root",
        lambda: tmp_path,
    )
    return tmp_path


class TestResolveAbsoluteImportSrcLayout:
    def test_a_module_under_src_resolves(self, src_layout_project):
        resolved = resolve_absolute_import("demo.db", src_layout_project)

        assert resolved is not None
        assert Path(resolved) == (src_layout_project / "src" / "demo" / "db.py")

    def test_the_package_itself_resolves_to_its_init(self, src_layout_project):
        resolved = resolve_absolute_import("demo", src_layout_project)

        assert resolved is not None
        assert Path(resolved).name == "__init__.py"

    def test_an_unknown_module_still_resolves_to_nothing(self, src_layout_project):
        assert resolve_absolute_import("demo.nope", src_layout_project) is None

    def test_a_third_party_module_is_not_claimed(self, src_layout_project):
        assert resolve_absolute_import("click", src_layout_project) is None


class TestFlatLayoutStillWins:
    def test_a_top_level_package_resolves_ahead_of_src(self, tmp_path, monkeypatch):
        """A module present at the root is preferred over a same-named one in src/."""
        _write(tmp_path / "demo" / "__init__.py", "")
        _write(tmp_path / "demo" / "db.py", "ROOT = True\n")
        _write(tmp_path / "src" / "demo" / "__init__.py", "")
        _write(tmp_path / "src" / "demo" / "db.py", "ROOT = False\n")
        monkeypatch.setattr(
            "desloppify.languages.python.detectors.deps_resolution.get_project_root",
            lambda: tmp_path,
        )

        resolved = resolve_absolute_import("demo.db", tmp_path)

        assert Path(resolved) == (tmp_path / "demo" / "db.py")


class TestDepGraphSrcLayout:
    def test_the_importer_is_recorded_on_the_imported_module(self, src_layout_project):
        graph = build_dep_graph(src_layout_project)

        db = str((src_layout_project / "src" / "demo" / "db.py").resolve())
        cli = str((src_layout_project / "src" / "demo" / "cli.py").resolve())

        assert db in graph, "the imported module is missing from the graph"
        assert graph[db]["importer_count"] == 1
        assert cli in graph[db]["importers"]

    def test_the_importing_module_records_its_import(self, src_layout_project):
        graph = build_dep_graph(src_layout_project)

        cli = str((src_layout_project / "src" / "demo" / "cli.py").resolve())
        db = str((src_layout_project / "src" / "demo" / "db.py").resolve())

        assert db in graph[cli]["imports"]

    def test_the_graph_is_not_empty(self, src_layout_project):
        """The symptom this guards: every module reporting zero importers."""
        graph = build_dep_graph(src_layout_project)

        assert any(entry["importer_count"] > 0 for entry in graph.values())
