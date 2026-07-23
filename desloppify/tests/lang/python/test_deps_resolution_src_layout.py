"""Absolute-import resolution for conventional ``src/`` package layouts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.python.detectors.deps_resolution import (
    resolve_absolute_import,
)


def _mk(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def _patched_project_root(project_root: Path):
    return patch(
        "desloppify.languages.python.detectors.deps_resolution.get_project_root",
        return_value=project_root,
    )


class TestResolveAbsoluteImportSrcLayout:
    def test_resolves_module_under_scan_root_src(self, tmp_path):
        """<scan_root>/src/<pkg>/... resolves without special configuration."""
        scan_root = tmp_path / "agents" / "my-agent"
        target = _mk(scan_root, "src/my_pkg/orchestration/showcase.py")
        _mk(scan_root, "src/my_pkg/__init__.py")
        _mk(scan_root, "src/my_pkg/orchestration/__init__.py")
        with _patched_project_root(tmp_path):
            resolved = resolve_absolute_import(
                "my_pkg.orchestration.showcase", scan_root
            )
        assert resolved == str(target.resolve())

    def test_resolves_package_init_under_src(self, tmp_path):
        scan_root = tmp_path / "proj"
        init = _mk(scan_root, "src/my_pkg/__init__.py")
        with _patched_project_root(tmp_path):
            resolved = resolve_absolute_import("my_pkg", scan_root)
        assert resolved == str(init.resolve())

    def test_plain_layout_wins_over_src_layout(self, tmp_path):
        """Direct <root>/<pkg> resolution keeps precedence over <root>/src/<pkg>."""
        scan_root = tmp_path / "proj"
        plain = _mk(scan_root, "my_pkg/mod.py")
        _mk(scan_root, "src/my_pkg/mod.py")
        with _patched_project_root(tmp_path):
            resolved = resolve_absolute_import("my_pkg.mod", scan_root)
        assert resolved == str(plain.resolve())

    def test_scan_root_src_beats_project_root_src(self, tmp_path):
        """Monorepo: the scanned project's src wins over a sibling at project root."""
        scan_root = tmp_path / "agents" / "my-agent"
        ours = _mk(scan_root, "src/shared_pkg/mod.py")
        _mk(tmp_path, "src/shared_pkg/mod.py")
        with _patched_project_root(tmp_path):
            resolved = resolve_absolute_import("shared_pkg.mod", scan_root)
        assert resolved == str(ours.resolve())

    def test_project_root_src_is_fallback(self, tmp_path):
        scan_root = tmp_path / "tools" / "cli"
        scan_root.mkdir(parents=True)
        target = _mk(tmp_path, "src/root_pkg/mod.py")
        with _patched_project_root(tmp_path):
            resolved = resolve_absolute_import("root_pkg.mod", scan_root)
        assert resolved == str(target.resolve())

    def test_unresolvable_returns_none(self, tmp_path):
        scan_root = tmp_path / "proj"
        scan_root.mkdir(parents=True)
        with _patched_project_root(tmp_path):
            assert resolve_absolute_import("missing_pkg.mod", scan_root) is None
