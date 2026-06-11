"""Tests for desloppify.languages.python.detectors.deps — Python dependency graph builder."""

import textwrap
from pathlib import Path

from desloppify.languages.python.detectors.deps import (
    build_dep_graph,
    find_python_dynamic_imports,
)

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
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "main.py": "x = 1\n",
            },
        )
        graph = build_dep_graph(pkg)
        assert len(graph) >= 1
        # Every entry should have the expected keys
        for _filepath, entry in graph.items():
            assert "imports" in entry or "import_count" in entry

    def test_simple_relative_import(self, tmp_path):
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "utils.py": "def helper(): pass\n",
                "main.py": "from .utils import helper\n",
            },
        )
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
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "core.py": "CONST = 42\n",
                "cli.py": "from mypkg.core import CONST\n",
            },
        )
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
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "a.py": "from .b import x\n",
                "b.py": "from .c import y\nx = 1\n",
                "c.py": "y = 2\n",
            },
        )
        graph = build_dep_graph(pkg)
        # At least a, b, c, __init__ should be in the graph
        assert len(graph) >= 3


# ── Graph structure (finalized) ───────────────────────────


class TestGraphStructure:
    def test_finalized_keys(self, tmp_path):
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "main.py": "from .helper import foo\n",
                "helper.py": "def foo(): pass\n",
            },
        )
        graph = build_dep_graph(pkg)
        for _filepath, entry in graph.items():
            assert "imports" in entry
            assert "import_count" in entry
            assert "importer_count" in entry

    def test_importer_count(self, tmp_path):
        """A module imported by two others should have importer_count >= 2."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "shared.py": "VAL = 1\n",
                "a.py": "from .shared import VAL\n",
                "b.py": "from .shared import VAL\n",
            },
        )
        graph = build_dep_graph(pkg)
        shared_key = None
        for k in graph:
            if k.endswith("shared.py"):
                shared_key = k
        assert shared_key is not None
        assert graph[shared_key]["importer_count"] >= 2


# ── src/ layout (PyPA recommended) ────────────────────────


class TestSrcLayout:
    """Absolute imports must resolve when the package lives under ``src/``.

    Regression for the ``src``-layout import resolver: ``from mypkg.schema
    import VAL`` in ``<root>/src/mypkg/main.py`` resolves to
    ``<root>/src/mypkg/schema.py``. Before the fix, only ``<root>/mypkg`` and
    ``<project_root>/mypkg`` were tried, so the edge was dropped and
    ``schema.py`` was misreported as orphaned with zero importers.
    """

    def test_absolute_import_resolves_under_src(self, tmp_path):
        root = tmp_path / "proj"
        src_pkg = root / "src" / "mypkg"
        src_pkg.mkdir(parents=True)
        (src_pkg / "__init__.py").write_text("")
        (src_pkg / "schema.py").write_text("VAL = 1\n")
        (src_pkg / "main.py").write_text("from mypkg.schema import VAL\n")

        graph = build_dep_graph(root)

        schema_key = next((k for k in graph if k.endswith("schema.py")), None)
        assert schema_key is not None, "schema.py should be in graph"
        assert graph[schema_key]["importer_count"] >= 1, (
            "schema.py is imported via `from mypkg.schema import VAL` under src/ layout"
        )


# ── Deferred imports ──────────────────────────────────────


class TestDeferredImports:
    def test_function_level_import_marked_deferred(self, tmp_path):
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "lazy.py": textwrap.dedent("""\
                def load():
                    from .heavy import big_fn
                    return big_fn()
            """),
                "heavy.py": "def big_fn(): return 42\n",
            },
        )
        graph = build_dep_graph(pkg)
        lazy_key = None
        for k in graph:
            if k.endswith("lazy.py"):
                lazy_key = k
        assert lazy_key is not None
        # The import should be recorded even if deferred
        assert graph[lazy_key]["import_count"] >= 1


# ── TYPE_CHECKING guard ──────────────────────────────────


class TestTypeCheckingGuard:
    """Imports inside ``if TYPE_CHECKING:`` blocks are not runtime imports.

    They should be tracked as deferred so cycle detection skips them.
    """

    def test_type_checking_import_marked_deferred(self, tmp_path):
        """from-import inside ``if TYPE_CHECKING:`` should land in deferred_imports."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "models.py": "class Model: pass\n",
                "service.py": textwrap.dedent("""\
                    from typing import TYPE_CHECKING
                    if TYPE_CHECKING:
                        from .models import Model
                    def run() -> None: ...
                """),
            },
        )
        graph = build_dep_graph(pkg)
        svc_key = next(k for k in graph if k.endswith("service.py"))
        models_key = next(k for k in graph if k.endswith("models.py"))
        # Import is recorded in imports (for general analysis)
        assert models_key in graph[svc_key]["imports"]
        # But also flagged as deferred (excluded from cycle detection)
        assert models_key in graph[svc_key]["deferred_imports"]

    def test_qualified_typing_type_checking(self, tmp_path):
        """``if typing.TYPE_CHECKING:`` should also be detected."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "types.py": "MyType = int\n",
                "consumer.py": textwrap.dedent("""\
                    import typing
                    if typing.TYPE_CHECKING:
                        from .types import MyType
                """),
            },
        )
        graph = build_dep_graph(pkg)
        consumer_key = next(k for k in graph if k.endswith("consumer.py"))
        types_key = next(k for k in graph if k.endswith("types.py"))
        assert types_key in graph[consumer_key]["deferred_imports"]

    def test_regular_import_not_deferred(self, tmp_path):
        """A normal top-level import must NOT be marked as deferred."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "utils.py": "def helper(): pass\n",
                "main.py": "from .utils import helper\n",
            },
        )
        graph = build_dep_graph(pkg)
        main_key = next(k for k in graph if k.endswith("main.py"))
        utils_key = next(k for k in graph if k.endswith("utils.py"))
        assert utils_key in graph[main_key]["imports"]
        assert utils_key not in graph[main_key].get("deferred_imports", set())

    def test_type_checking_cycle_not_reported(self, tmp_path):
        """A cycle that exists only via TYPE_CHECKING imports should not be detected."""
        from desloppify.engine.detectors.graph import detect_cycles

        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "a.py": textwrap.dedent("""\
                    from typing import TYPE_CHECKING
                    from .b import real_fn
                    if TYPE_CHECKING:
                        from .b import SomeType
                """),
                "b.py": textwrap.dedent("""\
                    from typing import TYPE_CHECKING
                    if TYPE_CHECKING:
                        from .a import something
                    def real_fn(): pass
                """),
            },
        )
        graph = build_dep_graph(pkg)
        # b.py -> a.py is only via TYPE_CHECKING, so with skip_deferred the
        # cycle (a imports b at runtime, b imports a only under TYPE_CHECKING)
        # should not be flagged.
        cycles, _ = detect_cycles(graph, skip_deferred=True)
        assert cycles == [], f"Expected no cycles but got: {cycles}"


# ── Edge cases ────────────────────────────────────────────


class TestEdgeCases:
    def test_syntax_error_file_skipped(self, tmp_path):
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "broken.py": "def foo( :\n",
                "good.py": "x = 1\n",
            },
        )
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
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "utils.py": "A = 1\nB = 2\n",
                "main.py": "from .utils import (\n    A,\n    B,\n)\n",
            },
        )
        graph = build_dep_graph(pkg)
        main_key = None
        for k in graph:
            if k.endswith("main.py"):
                main_key = k
        assert main_key is not None
        assert graph[main_key]["import_count"] >= 1


# ── Dots-only relative imports ────────────────────────────


# ── Dynamic import finder ─────────────────────────────────


class TestDynamicImportFinder:
    def test_finds_importlib_import_module(self, tmp_path):
        """importlib.import_module('foo.bar') should be found."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "loader.py": textwrap.dedent("""\
                    import importlib
                    mod = importlib.import_module("mypkg.plugins.auth")
                """),
                "plugins/__init__.py": "",
                "plugins/auth.py": "x = 1\n",
            },
        )
        targets = find_python_dynamic_imports(pkg, [".py"])
        # Should contain the resolved path or the raw specifier
        assert len(targets) >= 1
        # The raw specifier should match if resolution fails,
        # or a resolved path ending in auth.py if it succeeds
        found = any(
            "auth" in t for t in targets
        )
        assert found, f"Expected 'auth' in targets, got {targets}"

    def test_ignores_non_string_args(self, tmp_path):
        """importlib.import_module(variable) should NOT be found."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "loader.py": textwrap.dedent("""\
                    import importlib
                    name = "foo"
                    mod = importlib.import_module(name)
                """),
            },
        )
        targets = find_python_dynamic_imports(pkg, [".py"])
        assert len(targets) == 0

    def test_ignores_unrelated_import_module_calls(self, tmp_path):
        """other_lib.import_module() should NOT be found."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "loader.py": textwrap.dedent("""\
                    import custom_loader
                    mod = custom_loader.import_module("foo")
                """),
            },
        )
        targets = find_python_dynamic_imports(pkg, [".py"])
        assert len(targets) == 0

    def test_syntax_error_skipped(self, tmp_path):
        """Files with syntax errors should be skipped gracefully."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "broken.py": "def foo( :\n",
                "good.py": textwrap.dedent("""\
                    import importlib
                    mod = importlib.import_module("some.module")
                """),
            },
        )
        targets = find_python_dynamic_imports(pkg, [".py"])
        assert len(targets) >= 1

    def test_multiple_calls_collected(self, tmp_path):
        """Multiple importlib.import_module() calls in different files."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "a.py": textwrap.dedent("""\
                    import importlib
                    importlib.import_module("pkg.alpha")
                """),
                "b.py": textwrap.dedent("""\
                    import importlib
                    importlib.import_module("pkg.beta")
                """),
            },
        )
        targets = find_python_dynamic_imports(pkg, [".py"])
        assert len(targets) >= 2


class TestDotsOnlyImport:
    def test_from_dot_import(self, tmp_path):
        """from . import submodule should resolve to sibling module."""
        pkg = _make_pkg(
            tmp_path,
            {
                "__init__.py": "",
                "sub.py": "VAL = 1\n",
                "main.py": "from . import sub\n",
            },
        )
        graph = build_dep_graph(pkg)
        main_key = None
        for k in graph:
            if k.endswith("main.py"):
                main_key = k
        assert main_key is not None
        assert graph[main_key]["import_count"] >= 1
