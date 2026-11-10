"""Tests for the ``test_roots`` config: external tests outside the scan path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from desloppify.base.config import CONFIG_SCHEMA
from desloppify.languages._framework.base import shared_phases_helpers as helpers
from desloppify.languages._framework.runtime_support.runtime import (
    LangRunOverrides,
    make_lang_run,
)
from desloppify.languages.typescript.test_coverage import parse_test_import_specs


def _touch(root: Path, rel: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("// test\n", encoding="utf-8")
    return str(p)


def _lang(test_roots=None, **kw):
    kw.setdefault("file_finder", None)
    return SimpleNamespace(
        external_test_dirs=["tests", "test", "__tests__"],
        test_file_extensions=[".ts", ".tsx"],
        extensions=[".ts", ".tsx"],
        exclusions=["node_modules"],
        test_roots=test_roots if test_roots is not None else [],
        **kw,
    )


def _find(tmp_path, lang, scan="src"):
    return helpers._find_external_test_files(
        tmp_path / scan, lang, get_project_root_fn=lambda: tmp_path
    )


def test_schema_default_is_empty_list():
    key = CONFIG_SCHEMA["test_roots"]
    assert key.type is list
    assert key.default == []


def test_test_roots_finds_file_outside_scan_path(tmp_path):
    hit = _touch(tmp_path, "apps/x/__tests__/a.test.ts")
    _touch(tmp_path, "apps/x/src/not_a_test_dir.ts")
    _touch(tmp_path, "apps/x/__tests__/readme.md")
    found = _find(tmp_path, _lang(["apps/*/__tests__/**"]))
    assert found == {hit}


def test_directory_pattern_matches_everything_below(tmp_path):
    hit = _touch(tmp_path, "apps/x/__tests__/deep/a.test.tsx")
    assert _find(tmp_path, _lang(["apps/x/__tests__"])) == {hit}


def test_file_inside_scan_path_is_skipped_and_not_duplicated(tmp_path):
    _touch(tmp_path, "src/__tests__/in_scope.test.ts")
    outside = _touch(tmp_path, "apps/x/__tests__/a.test.ts")
    found = _find(tmp_path, _lang(["**/__tests__/**"]))
    assert found == {outside}


def test_overlap_with_external_test_dirs_is_a_set(tmp_path):
    hit = _touch(tmp_path, "tests/a.test.ts")
    found = _find(tmp_path, _lang(["tests/**"]))
    assert found == {hit}


def test_empty_test_roots_is_unchanged_behavior(tmp_path):
    ext = _touch(tmp_path, "tests/a.test.ts")
    _touch(tmp_path, "apps/x/__tests__/a.test.ts")
    assert _find(tmp_path, _lang([])) == {ext}
    legacy = SimpleNamespace(
        external_test_dirs=["tests"],
        test_file_extensions=[".ts"],
        extensions=[".ts"],
    )
    assert _find(tmp_path, legacy) == {ext}


def test_node_modules_is_pruned(tmp_path):
    _touch(tmp_path, "node_modules/pkg/__tests__/a.test.ts")
    assert _find(tmp_path, _lang(["**/__tests__/**"])) == set()


def test_runtime_exclusions_are_respected(tmp_path):
    from desloppify.base.discovery import source as source_mod

    _touch(tmp_path, "apps/retired/__tests__/a.test.ts")
    keep = _touch(tmp_path, "apps/live/__tests__/a.test.ts")
    source_mod.set_exclusions(["apps/retired"])
    try:
        found = _find(tmp_path, _lang(["apps/*/__tests__/**"]))
    finally:
        source_mod.set_exclusions([])
    assert found == {keep}


def test_typescript_file_finder_drops_d_ts(tmp_path, monkeypatch):
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    from desloppify.languages.typescript.detectors.io import iter_typescript_sources

    _touch(tmp_path, "apps/x/__tests__/types.d.ts")
    keep = _touch(tmp_path, "apps/x/__tests__/a.test.ts")
    found = _find(tmp_path, _lang(["apps/*/__tests__/**"], file_finder=iter_typescript_sources))
    assert found == {keep}


def test_test_roots_reach_runtime_through_overrides():
    run = make_lang_run(
        SimpleNamespace(name="x"), LangRunOverrides(test_roots=["apps/*/__tests__/**"])
    )
    assert run.test_roots == ["apps/*/__tests__/**"]
    assert make_lang_run(SimpleNamespace(name="x")).test_roots == []


def test_require_spec_is_extracted():
    assert parse_test_import_specs("const m = require('../X');") == ["../X"]
    assert parse_test_import_specs('require ( "../Y.tsx" )') == ["../Y.tsx"]


def test_require_spec_inside_ternary_and_isolate_modules():
    src = (
        "jest.isolateModules(() => {\n"
        "  mod = flag ? require('../A') : require('../B.tsx');\n"
        "});\n"
    )
    assert parse_test_import_specs(src) == ["../A", "../B.tsx"]


def test_require_word_boundary():
    assert parse_test_import_specs("myrequire('../X'); requireActual('../Y')") == []


def test_import_forms_unchanged():
    src = (
        "import a from '../a';\n"
        "import type { T } from '../t';\n"
        "import '../side';\n"
        "const m = await import('../dyn');\n"
        "export { z } from '../z';\n"
    )
    assert parse_test_import_specs(src) == ["../a", "../t", "../side", "../dyn", "../z"]
