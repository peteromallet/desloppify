"""Tests for Python move helpers."""

from __future__ import annotations

from pathlib import Path


def test_move_py_module_imports():
    import desloppify.lang.python.move

    assert callable(desloppify.lang.python.move.find_py_replacements)
    assert callable(desloppify.lang.python.move.find_py_self_replacements)


class TestMovePyHelpers:
    def test_path_to_py_module(self):
        from desloppify.lang.python.move import _path_to_py_module

        root = Path("/project")
        assert _path_to_py_module("/project/foo/bar.py", root) == "foo.bar"
        assert _path_to_py_module("/project/foo/__init__.py", root) == "foo"
        assert _path_to_py_module("/project/foo/baz/qux.py", root) == "foo.baz.qux"

    def test_path_to_py_module_outside_root(self):
        from desloppify.lang.python.move import _path_to_py_module

        root = Path("/project")
        assert _path_to_py_module("/other/foo.py", root) is None

    def test_has_exact_module(self):
        from desloppify.lang.python.move import _has_exact_module

        assert _has_exact_module("from foo.bar import baz", "foo.bar")
        assert not _has_exact_module("from foo.bar.child import baz", "foo.bar")
        assert _has_exact_module("import foo.bar", "foo.bar")
        assert not _has_exact_module("import foo.barx", "foo.bar")

    def test_replace_exact_module(self):
        from desloppify.lang.python.move import _replace_exact_module

        line = "from foo.bar import baz"
        result = _replace_exact_module(line, "foo.bar", "qux.quux")
        assert result == "from qux.quux import baz"

    def test_replace_exact_module_no_child(self):
        from desloppify.lang.python.move import _replace_exact_module

        line = "from foo.bar.child import baz"
        result = _replace_exact_module(line, "foo.bar", "qux.quux")
        assert result == "from foo.bar.child import baz"

    def test_compute_py_relative_import(self):
        from desloppify.lang.python.move import _compute_py_relative_import

        result = _compute_py_relative_import("/project/pkg/a.py", "/project/pkg/b.py")
        assert result == ".b"

    def test_compute_py_relative_import_parent(self):
        from desloppify.lang.python.move import _compute_py_relative_import

        result = _compute_py_relative_import("/project/pkg/sub/a.py", "/project/pkg/b.py")
        assert result == "..b"

    def test_resolve_py_relative_file(self, tmp_path):
        from desloppify.lang.python.move import _resolve_py_relative

        (tmp_path / "foo.py").write_text("")
        result = _resolve_py_relative(tmp_path, ".", "foo")
        assert result is not None
        assert result.endswith("foo.py")

    def test_resolve_py_relative_package(self, tmp_path):
        from desloppify.lang.python.move import _resolve_py_relative

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        result = _resolve_py_relative(tmp_path, ".", "pkg")
        assert result is not None
        assert result.endswith("__init__.py")

    def test_resolve_py_relative_not_found(self, tmp_path):
        from desloppify.lang.python.move import _resolve_py_relative

        result = _resolve_py_relative(tmp_path, ".", "nonexistent")
        assert result is None
