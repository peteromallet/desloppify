"""Layout/interoperability checks for colocated language tests."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

from desloppify.lang import available_langs, get_lang
from desloppify.utils import PROJECT_ROOT, compute_tool_hash, rel
from desloppify.zones import FileZoneMap, Zone


def _load_pyproject() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())


def _lang_test_rel_path(lang: str) -> str:
    return f"desloppify/lang/{lang}/tests"


def _lang_test_exclude(lang: str) -> str:
    return f"desloppify.lang.{lang}.tests*"


def test_pyproject_discovers_lang_test_paths():
    data = _load_pyproject()
    testpaths = data["tool"]["pytest"]["ini_options"]["testpaths"]
    assert "tests" in testpaths
    for lang in available_langs():
        assert _lang_test_rel_path(lang) in testpaths


def test_pyproject_excludes_lang_tests_from_packages():
    data = _load_pyproject()
    excludes = data["tool"]["setuptools"]["packages"]["find"]["exclude"]
    for lang in available_langs():
        assert _lang_test_exclude(lang) in excludes


def test_each_lang_has_colocated_tests_package():
    for lang in available_langs():
        test_dir = PROJECT_ROOT / _lang_test_rel_path(lang)
        assert test_dir.is_dir(), f"missing tests dir for {lang}: {test_dir}"
        init_file = test_dir / "__init__.py"
        assert init_file.is_file(), f"missing tests/__init__.py for {lang}"


def test_colocated_lang_tests_are_classified_as_test_zone():
    for lang in available_langs():
        cfg = get_lang(lang)
        test_dir = PROJECT_ROOT / _lang_test_rel_path(lang)
        files = sorted(str(p) for p in test_dir.glob("test_*.py"))
        files += [str(test_dir / "__init__.py")]
        files = [f for f in files if Path(f).exists()]
        assert files, f"expected colocated language test files for {lang}"

        zm = FileZoneMap(files, cfg.zone_rules, rel_fn=rel)
        assert all(zm.get(f) == Zone.TEST for f in files), f"{lang} tests not in test zone"


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

