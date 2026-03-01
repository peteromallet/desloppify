"""Tests for cross-file smells, string filtering helpers, and output structure."""

import textwrap
from pathlib import Path

from desloppify.languages.python.detectors import smells as smells_mod
from desloppify.languages.python.detectors.smells import detect_smells

# ── Helpers ────────────────────────────────────────────────


def _write_py(tmp_path: Path, code: str, filename: str = "test_mod.py") -> Path:
    """Write a Python file and return the directory containing it."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return tmp_path


def _smell_ids(entries: list[dict]) -> set[str]:
    """Extract the set of smell IDs from detect_smells output."""
    return {e["id"] for e in entries}


def _find_smell(entries: list[dict], smell_id: str) -> dict | None:
    """Find a specific smell entry by ID."""
    for e in entries:
        if e["id"] == smell_id:
            return e
    return None


# ── Multi-line string filtering ──────────────────────────


class TestBuildStringLineSet:
    def test_triple_quote_lines_excluded(self):
        lines = [
            'x = """',
            'eval("danger")',
            '"""',
            'eval("real")',
        ]
        string_lines = smells_mod._build_string_line_set(lines)
        assert 1 in string_lines  # inside triple-quote
        assert 3 not in string_lines  # outside triple-quote

    def test_same_line_triple_quote(self):
        lines = ['x = """hello"""', 'eval("real")']
        string_lines = smells_mod._build_string_line_set(lines)
        assert 0 not in string_lines  # closed on same line
        assert 1 not in string_lines


class TestMatchIsInString:
    def test_match_outside_string(self):
        assert not smells_mod._match_is_in_string('eval("code")', 0)

    def test_match_inside_string(self):
        line = '"eval(x)" + stuff'
        idx = line.index("eval")
        assert smells_mod._match_is_in_string(line, idx)

    def test_match_in_comment(self):
        line = "x = 1  # eval(x)"
        idx = line.index("eval")
        assert smells_mod._match_is_in_string(line, idx)


# ── Clean code produces no high-severity smells ──────────


class TestCleanCode:
    def test_clean_file(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            \"\"\"A clean module.\"\"\"

            import os
            from pathlib import Path


            def greet(name: str) -> str:
                return f"Hello, {name}"


            class Config:
                DEBUG = False
                VERSION = "1.0"
        """,
        )
        entries, count = detect_smells(path)
        high = [e for e in entries if e["severity"] == "high"]
        assert len(high) == 0
        assert count == 1


# ── Duplicate constants (cross-file) ─────────────────────


class TestDuplicateConstants:
    def test_same_constant_in_two_files(self, tmp_path):
        (tmp_path / "a.py").write_text("MAX_RETRIES = 3\n")
        (tmp_path / "b.py").write_text("MAX_RETRIES = 3\n")
        entries, _ = detect_smells(tmp_path)
        assert "duplicate_constant" in _smell_ids(entries)

    def test_different_constants_ok(self, tmp_path):
        (tmp_path / "a.py").write_text("MAX_RETRIES = 3\n")
        (tmp_path / "b.py").write_text("MAX_RETRIES = 5\n")
        entries, _ = detect_smells(tmp_path)
        assert "duplicate_constant" not in _smell_ids(entries)


# ── star_import_no_all ───────────────────────────────────


class TestStarImportNoAll:
    def test_star_import_target_without_all(self, tmp_path):
        """from .helper import * where helper.py has no __all__ -> flagged."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "helper.py").write_text("def foo(): pass\n")
        (pkg / "main.py").write_text("from .helper import *\n")
        entries, _ = detect_smells(pkg)
        assert "star_import_no_all" in _smell_ids(entries)

    def test_star_import_target_with_all(self, tmp_path):
        """from .helper import * where helper.py defines __all__ -> not flagged."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "helper.py").write_text('__all__ = ["foo"]\ndef foo(): pass\n')
        (pkg / "main.py").write_text("from .helper import *\n")
        entries, _ = detect_smells(pkg)
        assert "star_import_no_all" not in _smell_ids(entries)

    def test_absolute_star_import_target_without_all_from_scan_root(self, tmp_path):
        """from mypkg.helper import * resolves when scanning the project root."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "helper.py").write_text("def foo(): pass\n")
        (tmp_path / "main.py").write_text("from mypkg.helper import *\n")

        entries, _ = detect_smells(tmp_path)

        assert "star_import_no_all" in _smell_ids(entries)

    def test_absolute_star_import_target_without_all_from_package_scan(self, tmp_path):
        """from mypkg.helper import * resolves when scanning a single package."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "helper.py").write_text("def foo(): pass\n")
        (pkg / "main.py").write_text("from mypkg.helper import *\n")

        entries, _ = detect_smells(pkg)

        assert "star_import_no_all" in _smell_ids(entries)


# ── Output structure ─────────────────────────────────────


class TestOutputStructure:
    def test_entry_keys(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def foo(items=[]):
                pass
        """,
        )
        entries, _ = detect_smells(path)
        assert len(entries) > 0
        e = entries[0]
        assert "id" in e
        assert "label" in e
        assert "severity" in e
        assert "count" in e
        assert "files" in e
        assert "matches" in e

    def test_severity_sort_order(self, tmp_path):
        """Entries should be sorted high -> medium -> low."""
        path = _write_py(
            tmp_path,
            """\
            # TODO: something
            def foo(items=[]):
                pass
        """,
        )
        entries, _ = detect_smells(path)
        severities = [e["severity"] for e in entries]
        order = {"high": 0, "medium": 1, "low": 2}
        ranks = [order[s] for s in severities]
        assert ranks == sorted(ranks)
