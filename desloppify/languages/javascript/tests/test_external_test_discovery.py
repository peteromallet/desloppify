"""JavaScript production can be exercised by TypeScript test suites."""

import importlib
from pathlib import Path

import pytest

import desloppify.languages.javascript as javascript
from desloppify.base.discovery.file_paths import rel
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages import get_lang
from desloppify.languages._framework.base.shared_phases_helpers import (
    _find_external_test_files,
)
from desloppify.languages._framework.base.shared_phases_review import (
    phase_test_coverage,
)
from desloppify.languages._framework.runtime_support.runtime import make_lang_run
from desloppify.languages._framework.treesitter import is_available

pytestmark = pytest.mark.skipif(not is_available(), reason="tree-sitter not installed")


@pytest.mark.parametrize(
    "test_extension", [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"]
)
@pytest.mark.parametrize(
    "scan_scope", ["public", "absolute_public", "root", "absolute_root"]
)
def test_external_tests_map_to_javascript_without_expanding_production_scope(
    tmp_path, monkeypatch, set_project_root, test_extension, scan_scope
):
    monkeypatch.chdir(tmp_path)
    public = tmp_path / "public"
    public.mkdir()
    module = (
        "export function twice(value) {\n"
        "  if (typeof value !== 'number') {\n"
        "    throw new TypeError('Expected a number');\n"
        "  }\n"
        "  if (!Number.isFinite(value)) {\n"
        "    throw new RangeError('Expected a finite value');\n"
        "  }\n"
        "  const result = value * 2;\n"
        "  return result;\n"
        "}\n"
    )
    (public / "tested.js").write_text(module)
    (public / "untested.js").write_text(
        module.replace("twice", "triple").replace("* 2", "* 3")
    )
    (public / "context.ts").write_text(
        "export function context(value: number) { return value; }\n"
    )
    tests = tmp_path / "test"
    tests.mkdir()
    test = tests / f"behavior.test{test_extension}"
    test.write_text(
        "import { twice } from '../public/tested.js';\n"
        "test('doubles positive, zero and negative inputs', () => {\n"
        "  expect(twice(2)).toBe(4);\n"
        "  expect(twice(0)).toBe(0);\n"
        "  expect(twice(-3)).toBe(-6);\n"
        "});\n"
    )
    (tests / "unrelated.py").write_text("def test_other(): pass\n")
    scan_path = {
        "public": Path("public"),
        "absolute_public": public,
        "root": Path("."),
        "absolute_root": tmp_path,
    }[scan_scope]
    # Other registry tests reset hooks independently of cached language configs.
    # Bootstrap the actual plugin so this integration fixture owns its setup.
    importlib.reload(javascript)
    cfg = get_lang("javascript")
    files = cfg.file_finder(scan_path)
    run = make_lang_run(cfg)
    run.zone_map = FileZoneMap(files, cfg.zone_rules, rel_fn=rel)
    production = set(run.zone_map.include_only(files, Zone.PRODUCTION, Zone.SCRIPT))
    assert production == {"public/tested.js", "public/untested.js"}
    already_in_graph = scan_scope in {"root", "absolute_root"} and test_extension in {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
    }
    assert _find_external_test_files(scan_path, run) == (
        set() if already_in_graph else {str(test)}
    )

    issues, _potential = phase_test_coverage(scan_path, run)

    by_file = {issue["file"] for issue in issues}
    assert "public/tested.js" not in by_file
    assert "public/untested.js" in by_file
    assert by_file <= set(files)
