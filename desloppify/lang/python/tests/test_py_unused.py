"""Tests for desloppify.lang.python.detectors.unused — ruff/pyflakes unused detection."""

import shutil
import textwrap
from pathlib import Path

import pytest

from desloppify.lang.python.detectors.unused import detect_unused

# Skip all tests if ruff is not available
pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not installed"
)


# ── Helpers ────────────────────────────────────────────────


def _write_py(tmp_path: Path, code: str, filename: str = "test_mod.py") -> Path:
    """Write a Python file and return the directory containing it."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return tmp_path


# ── Unused import detection ───────────────────────────────


class TestUnusedImports:
    def test_unused_import_detected(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os
            import sys

            def main():
                return sys.argv
        """)
        entries, total = detect_unused(path, category="imports")
        assert total == 1
        names = [e["name"] for e in entries]
        assert "os" in names

    def test_used_import_not_flagged(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os

            def main():
                return os.getcwd()
        """)
        entries, _ = detect_unused(path, category="imports")
        names = [e["name"] for e in entries]
        assert "os" not in names

    def test_underscore_prefix_suppressed(self, tmp_path):
        """Imports starting with _ should be suppressed by detect_unused."""
        path = _write_py(tmp_path, """\
            from collections import _chain
            x = 1
        """)
        entries, _ = detect_unused(path, category="imports")
        names = [e["name"] for e in entries]
        assert "_chain" not in names


# ── Unused variable detection ─────────────────────────────


class TestUnusedVars:
    def test_unused_var_detected(self, tmp_path):
        path = _write_py(tmp_path, """\
            def foo():
                unused_var = 42
                return 1
        """)
        entries, _ = detect_unused(path, category="vars")
        names = [e["name"] for e in entries]
        assert "unused_var" in names

    def test_used_var_not_flagged(self, tmp_path):
        path = _write_py(tmp_path, """\
            def foo():
                used_var = 42
                return used_var
        """)
        entries, _ = detect_unused(path, category="vars")
        names = [e["name"] for e in entries]
        assert "used_var" not in names


# ── Category filtering ────────────────────────────────────


class TestCategoryFilter:
    def test_all_category(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os

            def foo():
                unused_var = 42
                return 1
        """)
        entries, _ = detect_unused(path, category="all")
        categories = {e["category"] for e in entries}
        # Both imports and vars should be present
        assert "imports" in categories
        assert "vars" in categories

    def test_imports_only(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os

            def foo():
                unused_var = 42
                return 1
        """)
        entries, _ = detect_unused(path, category="imports")
        categories = {e["category"] for e in entries}
        assert categories <= {"imports"}

    def test_vars_only(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os

            def foo():
                unused_var = 42
                return 1
        """)
        entries, _ = detect_unused(path, category="vars")
        categories = {e["category"] for e in entries}
        assert categories <= {"vars"}


# ── Output structure ──────────────────────────────────────


class TestOutputStructure:
    def test_entry_keys(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os
            x = 1
        """)
        entries, total = detect_unused(path)
        assert isinstance(total, int)
        if entries:
            e = entries[0]
            assert "file" in e
            assert "line" in e
            assert "name" in e
            assert "category" in e


# ── Clean code ────────────────────────────────────────────


class TestCleanCode:
    def test_no_unused_in_clean_code(self, tmp_path):
        path = _write_py(tmp_path, """\
            import os

            def main():
                return os.getcwd()
        """)
        entries, _ = detect_unused(path)
        assert len(entries) == 0
