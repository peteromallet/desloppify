"""Tests for Python move helpers."""

from __future__ import annotations

from pathlib import Path

import desloppify.languages.python.move as py_move
from desloppify.languages.python.detectors.deps import build_dep_graph


def test_move_py_module_imports():
    assert callable(py_move.find_replacements)
    assert callable(py_move.find_self_replacements)


class TestMovePyHelpers:
    def test_path_to_py_module(self):
        root = Path("/project")
        assert py_move._path_to_py_module("/project/foo/bar.py", root) == "foo.bar"
        assert py_move._path_to_py_module("/project/foo/__init__.py", root) == "foo"
        assert (
            py_move._path_to_py_module("/project/foo/baz/qux.py", root) == "foo.baz.qux"
        )

    def test_path_to_py_module_outside_root(self):
        root = Path("/project")
        assert py_move._path_to_py_module("/other/foo.py", root) is None

    def test_has_exact_module(self):
        assert py_move._has_exact_module("from foo.bar import baz", "foo.bar")
        assert not py_move._has_exact_module("from foo.bar.child import baz", "foo.bar")
        assert py_move._has_exact_module("import foo.bar", "foo.bar")
        assert not py_move._has_exact_module("import foo.barx", "foo.bar")

    def test_replace_exact_module(self):
        line = "from foo.bar import baz"
        result = py_move._replace_exact_module(line, "foo.bar", "qux.quux")
        assert result == "from qux.quux import baz"

    def test_replace_exact_module_no_child(self):
        line = "from foo.bar.child import baz"
        result = py_move._replace_exact_module(line, "foo.bar", "qux.quux")
        assert result == "from foo.bar.child import baz"

    def test_compute_py_relative_import(self):
        result = py_move._compute_py_relative_import(
            "/project/pkg/a.py", "/project/pkg/b.py"
        )
        assert result == ".b"

    def test_compute_py_relative_import_parent(self):
        result = py_move._compute_py_relative_import(
            "/project/pkg/sub/a.py", "/project/pkg/b.py"
        )
        assert result == "..b"

    def test_resolve_py_relative_file(self, tmp_path):
        (tmp_path / "foo.py").write_text("")
        result = py_move._resolve_py_relative(tmp_path, ".", "foo")
        assert result is not None
        assert result.endswith("foo.py")

    def test_resolve_py_relative_package(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        result = py_move._resolve_py_relative(tmp_path, ".", "pkg")
        assert result is not None
        assert result.endswith("__init__.py")

    def test_resolve_py_relative_not_found(self, tmp_path):
        result = py_move._resolve_py_relative(tmp_path, ".", "nonexistent")
        assert result is None

    def test_relative_import_replacement_uses_full_line(self, tmp_path, monkeypatch):
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("SOME_CONSTANT = 42\n")
        (pkg_dir / "utils.py").write_text("def helper():\n    return 1\n")

        sub_dir = pkg_dir / "sub"
        sub_dir.mkdir()
        importer = sub_dir / "importer.py"
        importer.write_text(
            "from .. import SOME_CONSTANT\nfrom ..utils import helper\n"
        )

        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        graph = build_dep_graph(tmp_path)
        source_abs = str((pkg_dir / "__init__.py").resolve())
        dest_abs = str((tmp_path / "newpkg" / "__init__.py").resolve())

        changes = py_move.find_replacements(source_abs, dest_abs, graph)
        importer_abs = str(importer.resolve())

        assert changes[importer_abs] == [
            (
                "from .. import SOME_CONSTANT",
                "from ...newpkg import SOME_CONSTANT",
            )
        ]

        content = importer.read_text()
        for old_str, new_str in changes[importer_abs]:
            content = content.replace(old_str, new_str)

        assert content == (
            "from ...newpkg import SOME_CONSTANT\nfrom ..utils import helper\n"
        )
