"""Layout/interoperability checks for colocated language tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import setuptools
import tomllib

from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages import available_langs, get_lang
from desloppify.languages._framework.structure_validation import validate_lang_structure
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import rel
from desloppify.utils import compute_tool_hash


def _full_langs() -> list[str]:
    """Return only languages with full (non-generic) plugin structure."""
    return [lang for lang in available_langs() if get_lang(lang).integration_depth == "full"]


def _load_pyproject() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())


def _lang_test_rel_path(lang: str) -> str:
    return f"desloppify/languages/{lang}/tests"


def test_pyproject_discovers_lang_test_paths():
    data = _load_pyproject()
    testpaths = data["tool"]["pytest"]["ini_options"]["testpaths"]
    assert "desloppify/tests" in testpaths
    for lang in _full_langs():
        assert _lang_test_rel_path(lang) in testpaths


def test_pyproject_excludes_tests_from_packages():
    data = _load_pyproject()
    excludes = data["tool"]["setuptools"]["packages"]["find"].get("exclude", [])
    # Only the top-level test suite should be excluded — language plugin
    # tests/ dirs must be included in the wheel for structure_validation.py.
    assert "desloppify.tests" in excludes
    assert "desloppify.tests.*" in excludes
    # The old wildcard pattern must NOT be present — it excluded language
    # plugin tests/ dirs from the wheel, breaking plugin discovery.
    assert "*.tests" not in excludes
    assert "*.tests.*" not in excludes


def test_each_lang_has_colocated_tests_dir():
    for lang in _full_langs():
        test_dir = PROJECT_ROOT / _lang_test_rel_path(lang)
        assert test_dir.is_dir(), f"missing tests dir for {lang}: {test_dir}"
        init_file = test_dir / "__init__.py"
        assert init_file.is_file(), f"missing tests/__init__.py for {lang}"


def test_colocated_lang_tests_are_classified_as_test_zone():
    for lang in _full_langs():
        cfg = get_lang(lang)
        test_dir = PROJECT_ROOT / _lang_test_rel_path(lang)
        files = sorted(str(p) for p in test_dir.glob("test_*.py"))
        files += [str(test_dir / "__init__.py")]
        files = [f for f in files if Path(f).exists()]
        assert files, f"expected colocated language test files for {lang}"

        zm = FileZoneMap(files, cfg.zone_rules, rel_fn=rel)
        assert all(zm.get(f) == Zone.TEST for f in files), (
            f"{lang} tests not in test zone"
        )


def test_packaging_includes_lang_plugin_tests():
    """Regression: pyproject.toml exclude patterns must not drop language plugin tests/.

    The original bug used exclude = ["*.tests", "*.tests.*"] which matched
    desloppify.languages.csharp.tests etc. and dropped them from the wheel.
    structure_validation.py requires a tests/ dir, so installing from that
    wheel broke plugin discovery at import time.

    Calls find_packages() with the live pyproject.toml include/exclude values —
    the same engine setuptools uses during pip install — so any future exclude
    pattern with the same bad effect will fail this test.
    """
    data = _load_pyproject()
    find_cfg = data["tool"]["setuptools"]["packages"]["find"]
    includes = find_cfg.get("include", ["*"])
    excludes = find_cfg.get("exclude", [])

    pkgs = set(
        setuptools.find_packages(str(PROJECT_ROOT), include=includes, exclude=excludes)
    )

    missing = [
        f"desloppify.languages.{lang}.tests"
        for lang in _full_langs()
        if f"desloppify.languages.{lang}.tests" not in pkgs
    ]
    assert not missing, (
        f"Language plugin tests/ packages excluded from wheel by pyproject.toml "
        f"exclude patterns {excludes!r}. Missing: {missing}. "
        f"These are required by structure_validation.py at install time."
    )

    leaked = [p for p in sorted(pkgs) if p.startswith("desloppify.tests")]
    assert not leaked, f"Top-level test suite leaked into wheel packages: {leaked}"


def test_validate_lang_structure_against_importlib_resolved_path():
    """validate_lang_structure passes at the path Python actually resolves.

    test_each_lang_has_colocated_tests_dir checks PROJECT_ROOT, which always
    passes in source mode even after a bad wheel build. This test uses importlib
    to find where Python has actually resolved each language package — in a wheel
    install that excluded tests/, that's site-packages/desloppify/languages/{lang}/
    which lacks tests/ and triggers the ValueError users saw.
    """
    for lang in _full_langs():
        lang_pkg = f"desloppify.languages.{lang}"
        spec = importlib.util.find_spec(lang_pkg)
        assert spec is not None, f"Cannot find installed package {lang_pkg!r}"
        search_locs = list(spec.submodule_search_locations)
        assert search_locs, f"No search locations for {lang_pkg}"
        lang_dir = Path(search_locs[0])
        # Raises ValueError if tests/ is absent, lacks __init__.py, or has no test_*.py.
        validate_lang_structure(lang_dir, lang)


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
