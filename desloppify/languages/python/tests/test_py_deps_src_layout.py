"""Tests for src-layout absolute-import resolution in the Python deps detector.

Covers the case where a project uses the ``src/`` layout (sources under
``<project_root>/src/<pkg>/...``) and is scanned with ``--path .`` so the
scan root is the project root itself, not ``src/``. Without the src-prefix
fallback in :func:`resolve_absolute_import`, every file under ``src/<pkg>/``
would appear unimported and the orphan-file detector would emit false
positives for entire production packages.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from desloppify.languages.python.detectors.deps import build_dep_graph
from desloppify.languages.python.detectors.deps_resolution import (
    resolve_absolute_import,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


class TestResolveAbsoluteImportSrcLayout:
    """Unit-level tests for the resolver helper itself."""

    def test_resolves_module_under_src(self, tmp_path: Path, monkeypatch) -> None:
        """``from pkg.mod import x`` should resolve to ``<root>/src/pkg/mod.py``."""
        _write(tmp_path / "src" / "pkg" / "__init__.py", "")
        _write(tmp_path / "src" / "pkg" / "mod.py", "VAL = 1\n")
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        resolved = resolve_absolute_import("pkg.mod", tmp_path)
        assert resolved is not None
        assert resolved.endswith("src/pkg/mod.py")

    def test_resolves_package_init_under_src(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """``from pkg import x`` should resolve to ``<root>/src/pkg/__init__.py``."""
        _write(tmp_path / "src" / "pkg" / "__init__.py", "X = 1\n")
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        resolved = resolve_absolute_import("pkg", tmp_path)
        assert resolved is not None
        assert resolved.endswith("src/pkg/__init__.py")

    def test_resolves_nested_module_under_src(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Deeply nested ``from pkg.a.b.c import x`` should resolve."""
        _write(tmp_path / "src" / "pkg" / "__init__.py", "")
        _write(tmp_path / "src" / "pkg" / "a" / "__init__.py", "")
        _write(tmp_path / "src" / "pkg" / "a" / "b" / "__init__.py", "")
        _write(tmp_path / "src" / "pkg" / "a" / "b" / "c.py", "x = 1\n")
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        resolved = resolve_absolute_import("pkg.a.b.c", tmp_path)
        assert resolved is not None
        assert resolved.endswith("src/pkg/a/b/c.py")

    def test_flat_layout_still_resolves(self, tmp_path: Path, monkeypatch) -> None:
        """Flat layout (no ``src/``) must keep working exactly as before."""
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "mod.py", "X = 1\n")
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        resolved = resolve_absolute_import("pkg.mod", tmp_path)
        assert resolved is not None
        assert resolved.endswith("pkg/mod.py")
        # And it must NOT have been mis-routed through a non-existent src/.
        assert "/src/" not in resolved

    def test_unresolvable_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """A missing module returns None even when ``src/`` exists."""
        (tmp_path / "src").mkdir()
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        assert resolve_absolute_import("nonexistent.module", tmp_path) is None

    def test_flat_layout_preferred_over_src_when_both_exist(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When both ``<root>/pkg`` and ``<root>/src/pkg`` exist, the flat one wins.

        This preserves the original probe order: scan_root / project_root come
        before the src-prefixed fallbacks.
        """
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "mod.py", "FLAT = 1\n")
        _write(tmp_path / "src" / "pkg" / "__init__.py", "")
        _write(tmp_path / "src" / "pkg" / "mod.py", "SRC = 1\n")
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        resolved = resolve_absolute_import("pkg.mod", tmp_path)
        assert resolved is not None
        assert resolved.endswith("pkg/mod.py")
        assert "/src/" not in resolved


class TestBuildDepGraphSrcLayout:
    """End-to-end: build_dep_graph counts importers across src-layout files."""

    def test_importer_count_under_src_layout(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A module under ``src/pkg/`` imported via absolute path is tracked.

        Reproduces the original bug: ``src/getaccept_worker/entities/activity.py``
        was imported by 21 files but appeared as ``importer_count == 0`` because
        the resolver never probed ``src/`` when the scan root was the project root.
        """
        _write(tmp_path / "src" / "pkg" / "__init__.py", "")
        _write(tmp_path / "src" / "pkg" / "shared.py", "VAL = 1\n")
        _write(
            tmp_path / "src" / "pkg" / "a.py",
            "from pkg.shared import VAL\n",
        )
        _write(
            tmp_path / "src" / "pkg" / "b.py",
            "from pkg.shared import VAL\n",
        )
        monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))

        # Scan root == project root (not src/) — this is the bug scenario.
        graph = build_dep_graph(tmp_path)

        shared_key = next(
            (k for k in graph if k.endswith("src/pkg/shared.py")), None
        )
        assert shared_key is not None, (
            f"shared.py not in graph; keys: {list(graph.keys())}"
        )
        assert graph[shared_key]["importer_count"] >= 2, (
            f"Expected shared.py to have >= 2 importers, "
            f"got {graph[shared_key]['importer_count']}"
        )
