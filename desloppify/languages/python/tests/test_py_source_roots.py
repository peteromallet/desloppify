"""Tests for pyproject-declared Python source roots in import resolution.

Covers projects whose importable code lives in a subdirectory of the repo
root (e.g. ``scripts/`` with ``PYTHONPATH=scripts``): declared roots must be
honored by ``resolve_absolute_import`` and by the test-coverage import-spec
mapper, otherwise the dependency graph reports 0 importers everywhere and
fully-tested modules are flagged untested.
"""

import textwrap
from pathlib import Path

from desloppify.languages.python.detectors.deps_resolution import (
    resolve_absolute_import,
)
from desloppify.languages.python.source_roots import declared_source_roots
from desloppify.languages.python.test_coverage import resolve_import_spec

# ── Helpers ────────────────────────────────────────────────


def _project(tmp_path: Path, pyproject: str, files: dict[str, str]) -> Path:
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent(pyproject))
    for rel_path, content in files.items():
        fp = tmp_path / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    declared_source_roots.cache_clear()
    return tmp_path


def _use_root(monkeypatch, root: Path) -> None:
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(root))


# ── declared_source_roots ─────────────────────────────────


class TestDeclaredSourceRoots:
    def test_no_pyproject_returns_empty(self, tmp_path):
        declared_source_roots.cache_clear()
        assert declared_source_roots(str(tmp_path)) == ()

    def test_pytest_pythonpath_list(self, tmp_path):
        _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = ["scripts", "tools"]
            """,
            {},
        )
        assert declared_source_roots(str(tmp_path)) == ("scripts", "tools")

    def test_pytest_pythonpath_string(self, tmp_path):
        _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = "scripts"
            """,
            {},
        )
        assert declared_source_roots(str(tmp_path)) == ("scripts",)

    def test_mypy_path_and_explicit_override_deduped(self, tmp_path):
        _project(
            tmp_path,
            """
            [tool.desloppify]
            python_source_roots = ["scripts"]

            [tool.mypy]
            mypy_path = "scripts"
            """,
            {},
        )
        assert declared_source_roots(str(tmp_path)) == ("scripts",)

    def test_unsafe_roots_dropped(self, tmp_path):
        _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = [".", "/abs", "../up", "scripts/"]
            """,
            {},
        )
        assert declared_source_roots(str(tmp_path)) == ("scripts",)

    def test_invalid_toml_returns_empty(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("not [ valid toml")
        declared_source_roots.cache_clear()
        assert declared_source_roots(str(tmp_path)) == ()


# ── resolve_absolute_import with declared roots ───────────


class TestResolveAbsoluteImportSourceRoots:
    def test_resolves_module_under_declared_root(self, tmp_path, monkeypatch):
        root = _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = ["scripts"]
            """,
            {"scripts/mypkg/__init__.py": "", "scripts/mypkg/store.py": "X = 1\n"},
        )
        _use_root(monkeypatch, root)
        resolved = resolve_absolute_import("mypkg.store", root)
        assert resolved == str((root / "scripts/mypkg/store.py").resolve())

    def test_scan_root_still_wins_over_declared_root(self, tmp_path, monkeypatch):
        root = _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = ["scripts"]
            """,
            {
                "mypkg/store.py": "ROOT = 1\n",
                "scripts/mypkg/store.py": "SCRIPTS = 1\n",
            },
        )
        _use_root(monkeypatch, root)
        resolved = resolve_absolute_import("mypkg.store", root)
        assert resolved == str((root / "mypkg/store.py").resolve())

    def test_unresolvable_returns_none(self, tmp_path, monkeypatch):
        root = _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = ["scripts"]
            """,
            {},
        )
        _use_root(monkeypatch, root)
        assert resolve_absolute_import("missing.module", root) is None


# ── test-coverage import-spec mapping with declared roots ─


class TestResolveImportSpecSourceRoots:
    def test_spec_resolves_via_declared_root_prefix(self, tmp_path, monkeypatch):
        root = _project(
            tmp_path,
            """
            [tool.pytest.ini_options]
            pythonpath = ["scripts"]
            """,
            {},
        )
        _use_root(monkeypatch, root)
        production = {"scripts/mypkg/store.py", "scripts/mypkg/__init__.py"}
        assert (
            resolve_import_spec("mypkg.store", "tests/unit/test_store.py", production)
            == "scripts/mypkg/store.py"
        )
        assert (
            resolve_import_spec("mypkg", "tests/unit/test_store.py", production)
            == "scripts/mypkg/__init__.py"
        )

    def test_src_prefix_still_supported(self, tmp_path, monkeypatch):
        root = _project(tmp_path, "", {})
        _use_root(monkeypatch, root)
        production = {"src/mypkg/store.py"}
        assert (
            resolve_import_spec("mypkg.store", "tests/test_store.py", production)
            == "src/mypkg/store.py"
        )
