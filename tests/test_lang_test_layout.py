"""Layout/interoperability checks for colocated language tests."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

from desloppify.lang.python import PythonConfig
from desloppify.utils import PROJECT_ROOT, compute_tool_hash, rel
from desloppify.zones import FileZoneMap, Zone


def _load_pyproject() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())


def test_pyproject_discovers_lang_test_paths():
    data = _load_pyproject()
    testpaths = data["tool"]["pytest"]["ini_options"]["testpaths"]
    assert "tests" in testpaths
    assert "desloppify/lang/python/tests" in testpaths
    assert "desloppify/lang/typescript/tests" in testpaths


def test_pyproject_excludes_lang_tests_from_packages():
    data = _load_pyproject()
    excludes = data["tool"]["setuptools"]["packages"]["find"]["exclude"]
    assert "desloppify.lang.python.tests*" in excludes
    assert "desloppify.lang.typescript.tests*" in excludes


def test_no_lang_specific_test_prefixes_in_top_level_tests():
    top = PROJECT_ROOT / "tests"
    assert list(top.glob("test_py_*.py")) == []
    assert list(top.glob("test_ts_*.py")) == []


def test_colocated_lang_tests_are_classified_as_test_zone():
    cfg = PythonConfig()
    files = sorted(str(p) for p in (
        list((PROJECT_ROOT / "desloppify/lang/python/tests").glob("test_*.py")) +
        list((PROJECT_ROOT / "desloppify/lang/typescript/tests").glob("test_*.py")) +
        list((PROJECT_ROOT / "desloppify/lang/python/tests").glob("__init__.py")) +
        list((PROJECT_ROOT / "desloppify/lang/typescript/tests").glob("__init__.py"))
    ))
    assert files, "expected colocated language test files"

    zm = FileZoneMap(files, cfg.zone_rules, rel_fn=rel)
    assert all(zm.get(f) == Zone.TEST for f in files)


def test_compute_tool_hash_ignores_colocated_tests(tmp_path):
    runtime_file = tmp_path / "core.py"
    runtime_file.write_text("x = 1\n")

    test_dir = tmp_path / "lang/python/tests"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_core.py"
    test_file.write_text("def test_x():\n    assert True\n")

    with patch("desloppify.utils.TOOL_DIR", tmp_path):
        base = compute_tool_hash()

        # Test-only changes should not affect runtime tool hash.
        test_file.write_text("def test_x():\n    assert 1 == 1\n")
        after_test_edit = compute_tool_hash()
        assert after_test_edit == base

        # Runtime code changes must affect tool hash.
        runtime_file.write_text("x = 2\n")
        after_runtime_edit = compute_tool_hash()
        assert after_runtime_edit != base
