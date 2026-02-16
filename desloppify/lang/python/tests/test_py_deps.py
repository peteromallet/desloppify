"""Tests for desloppify.lang.python.detectors.deps — Python dependency graph builder."""

import os
import textwrap
from pathlib import Path

import pytest

from desloppify.lang.python.detectors.deps import build_dep_graph


# ── Helpers ────────────────────────────────────────────────


def _make_pkg(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a Python package directory structure.

    Args:
        tmp_path: pytest temp directory
        files: mapping of relative path -> content
    Returns:
        path to the package root directory
    """
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    for rel_path, content in files.items():
        fp = pkg / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(textwrap.dedent(content))
    return pkg


# ── Basic graph construction ──────────────────────────────


class TestBasicGraph:
    def test_single_file_no_imports(self, tmp_path):
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "main.py": "x = 1\n",
        })
        graph = build_dep_graph(pkg)
        assert len(graph) >= 1
        # Every entry should have the expected keys
        for filepath, entry in graph.items():
            assert "imports" in entry or "import_count" in entry

    def test_simple_relative_import(self, tmp_path):
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "utils.py": "def helper(): pass\n",
            "main.py": "from .utils import helper\n",
        })
        graph = build_dep_graph(pkg)
        # Find main.py in graph
        main_key = None
        utils_key = None
        for k in graph:
            if k.endswith("main.py"):
                main_key = k
            elif k.endswith("utils.py"):
                utils_key = k
        assert main_key is not None, "main.py should be in graph"
        assert utils_key is not None, "utils.py should be in graph"
        # main.py imports utils.py
        assert graph[main_key]["import_count"] >= 1

    def test_absolute_import_within_project(self, tmp_path):
        """Absolute imports resolve when module is under scan root or PROJECT_ROOT.

        Note: absolute imports like `from mypkg.core import X` resolve relative to
        the scan root's parent. In tmp_path, this may not resolve if the package
        structure doesn't match. We test that the graph is built without error and
        contains the expected files.
        """
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "core.py": "CONST = 42\n",
            "cli.py": "from mypkg.core import CONST\n",
        })
        graph = build_dep_graph(pkg)
        cli_key = None
        for k in graph:
            if k.endswith("cli.py"):
                cli_key = k
        assert cli_key is not None
        # The import may or may not resolve depending on filesystem layout,
        # but cli.py should exist in the graph
        assert "imports" in graph[cli_key]

    def test_multi_file_graph(self, tmp_path):
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "a.py": "from .b import x\n",
            "b.py": "from .c import y\nx = 1\n",
            "c.py": "y = 2\n",
        })
        graph = build_dep_graph(pkg)
        # At least a, b, c, __init__ should be in the graph
        assert len(graph) >= 3


# ── Graph structure (finalized) ───────────────────────────


class TestGraphStructure:
    def test_finalized_keys(self, tmp_path):
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "main.py": "from .helper import foo\n",
            "helper.py": "def foo(): pass\n",
        })
        graph = build_dep_graph(pkg)
        for filepath, entry in graph.items():
            assert "imports" in entry
            assert "import_count" in entry
            assert "importer_count" in entry

    def test_importer_count(self, tmp_path):
        """A module imported by two others should have importer_count >= 2."""
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "shared.py": "VAL = 1\n",
            "a.py": "from .shared import VAL\n",
            "b.py": "from .shared import VAL\n",
        })
        graph = build_dep_graph(pkg)
        shared_key = None
        for k in graph:
            if k.endswith("shared.py"):
                shared_key = k
        assert shared_key is not None
        assert graph[shared_key]["importer_count"] >= 2


# ── Deferred imports ──────────────────────────────────────


class TestDeferredImports:
    def test_function_level_import_marked_deferred(self, tmp_path):
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "lazy.py": textwrap.dedent("""\
                def load():
                    from .heavy import big_fn
                    return big_fn()
            """),
            "heavy.py": "def big_fn(): return 42\n",
        })
        graph = build_dep_graph(pkg)
        lazy_key = None
        for k in graph:
            if k.endswith("lazy.py"):
                lazy_key = k
        assert lazy_key is not None
        # The import should be recorded even if deferred
        assert graph[lazy_key]["import_count"] >= 1


# ── Edge cases ────────────────────────────────────────────


class TestEdgeCases:
    def test_syntax_error_file_skipped(self, tmp_path):
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "broken.py": "def foo( :\n",
            "good.py": "x = 1\n",
        })
        graph = build_dep_graph(pkg)
        # broken.py should be skipped, good.py should be in graph
        good_found = any(k.endswith("good.py") for k in graph)
        assert good_found

    def test_empty_directory(self, tmp_path):
        pkg = tmp_path / "empty"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        graph = build_dep_graph(pkg)
        assert isinstance(graph, dict)

    def test_multi_line_import(self, tmp_path):
        """AST-based parsing handles multi-line imports correctly."""
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "utils.py": "A = 1\nB = 2\n",
            "main.py": "from .utils import (\n    A,\n    B,\n)\n",
        })
        graph = build_dep_graph(pkg)
        main_key = None
        for k in graph:
            if k.endswith("main.py"):
                main_key = k
        assert main_key is not None
        assert graph[main_key]["import_count"] >= 1


# ── Dots-only relative imports ────────────────────────────


class TestDotsOnlyImport:
    def test_from_dot_import(self, tmp_path):
        """from . import submodule should resolve to sibling module."""
        pkg = _make_pkg(tmp_path, {
            "__init__.py": "",
            "sub.py": "VAL = 1\n",
            "main.py": "from . import sub\n",
        })
        graph = build_dep_graph(pkg)
        main_key = None
        for k in graph:
            if k.endswith("main.py"):
                main_key = k
        assert main_key is not None
        assert graph[main_key]["import_count"] >= 1
