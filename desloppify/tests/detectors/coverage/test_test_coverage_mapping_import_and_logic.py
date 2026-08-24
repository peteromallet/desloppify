"""Focused tests for test coverage mapping/import and non-testable logic behavior."""

from __future__ import annotations

import pytest

import desloppify.languages.typescript.test_coverage as ts_cov
from desloppify.engine.detectors.coverage.mapping import (
    _build_prod_module_index,
    analyze_test_quality,
    import_based_mapping,
    naming_based_mapping,
)
from desloppify.engine.detectors.coverage.mapping_imports import (
    _resolve_barrel_reexports,
    _resolve_import,
)
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine.detectors.test_coverage.heuristics import _has_testable_logic
from desloppify.engine.detectors.test_coverage.io import (
    clear_coverage_read_warning_cache_for_tests,
)
from desloppify.engine.policy.zones import FileZoneMap, Zone, ZoneRule
from desloppify.languages.python.test_coverage import _strip_py_comment
from desloppify.languages.typescript.test_coverage import (
    has_testable_logic as ts_has_testable_logic,
)


def _make_zone_map(file_list: list[str]) -> FileZoneMap:
    """Build a minimal FileZoneMap with standard test-detection rules."""
    rules = [
        ZoneRule(Zone.TEST, ["test_", ".test.", ".spec.", "/tests/", "/__tests__/"])
    ]
    return FileZoneMap(file_list, rules)


def _write_file(tmp_path, relpath: str, content: str = "") -> str:
    """Write a file under tmp_path and return its absolute path."""
    p = tmp_path / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(p)


@pytest.fixture(autouse=True)
def _reset_read_warning_cache():
    clear_coverage_read_warning_cache_for_tests()
    yield
    clear_coverage_read_warning_cache_for_tests()


# ── _naming_based_mapping ────────────────────────────────


class TestNamingBasedMapping:
    def test_python_test_prefix(self):
        test_files = {"src/test_utils.py"}
        production_files = {"src/utils.py"}
        result = naming_based_mapping(test_files, production_files, "python")
        assert result == {"src/utils.py"}

    def test_python_test_suffix(self):
        test_files = {"src/utils_test.py"}
        production_files = {"src/utils.py"}
        result = naming_based_mapping(test_files, production_files, "python")
        assert result == {"src/utils.py"}

    def test_typescript_test_marker(self):
        test_files = {"src/utils.test.ts"}
        production_files = {"src/utils.ts"}
        result = naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/utils.ts"}

    def test_typescript_spec_marker(self):
        test_files = {"src/utils.spec.tsx"}
        production_files = {"src/utils.tsx"}
        result = naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/utils.tsx"}

    def test_typescript_test_ts_finds_tsx_source(self):
        """Closes #507: .test.ts must find .tsx production files."""
        test_files = {"src/components/OverlayEditor.test.ts"}
        production_files = {"src/components/OverlayEditor.tsx"}
        result = naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/components/OverlayEditor.tsx"}

    def test_typescript_test_tsx_finds_ts_source(self):
        test_files = {"src/utils/parser.test.tsx"}
        production_files = {"src/utils/parser.ts"}
        result = naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/utils/parser.ts"}

    def test_typescript_spec_ts_finds_jsx_source(self):
        test_files = {"src/Button.spec.ts"}
        production_files = {"src/Button.jsx"}
        result = naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/Button.jsx"}

    def test_no_match(self):
        test_files = {"src/test_foo.py"}
        production_files = {"src/bar.py"}
        result = naming_based_mapping(test_files, production_files, "python")
        assert result == set()

    def test_fuzzy_basename_fallback(self):
        """Fuzzy basename matching when _map_test_to_source fails (different dir)."""
        test_files = {"completely/different/test_utils.py"}
        production_files = {"src/deep/utils.py"}
        result = naming_based_mapping(test_files, production_files, "python")
        # _strip_test_markers("test_utils.py") → "utils.py"
        # prod_by_basename["utils.py"] → "src/deep/utils.py"
        assert result == {"src/deep/utils.py"}

    def test_go_non_test_file_does_not_map(self):
        test_files = {"tests/helpers.go"}
        production_files = {"pkg/helpers.go"}
        result = naming_based_mapping(test_files, production_files, "go")
        assert result == set()


# ── _resolve_import (TypeScript) ─────────────────────────


class TestResolveTsImport:
    def test_relative_import_same_dir(self, tmp_path):
        """./utils resolves to sibling file."""
        prod = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        test = _write_file(tmp_path, "src/utils.test.ts", "")
        result = _resolve_import("./utils", test, {prod}, "typescript")
        assert result == prod

    def test_relative_import_parent_dir(self, tmp_path):
        """../utils resolves to parent directory file."""
        prod = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        test = _write_file(tmp_path, "src/__tests__/utils.test.ts", "")
        result = _resolve_import("../utils", test, {prod}, "typescript")
        assert result == prod

    def test_relative_import_deep(self, tmp_path):
        """../../lib/helpers resolves multi-level relative path."""
        prod = _write_file(tmp_path, "lib/helpers.ts", "export const x = 1;\n")
        test = _write_file(tmp_path, "src/__tests__/sub/test.ts", "")
        result = _resolve_import("../../../lib/helpers", test, {prod}, "typescript")
        assert result == prod

    def test_alias_at_slash(self, tmp_path, monkeypatch):
        """@/components/Button resolves via get_src_path()."""
        monkeypatch.setattr(ts_cov, "get_src_path", lambda: tmp_path / "src")
        prod = _write_file(
            tmp_path,
            "src/components/Button.tsx",
            "export default function Button() {}\n",
        )
        result = _resolve_import(
            "@/components/Button", "/any/test.ts", {prod}, "typescript"
        )
        assert result == prod

    def test_alias_tilde(self, tmp_path, monkeypatch):
        """~/utils resolves via get_src_path()."""
        monkeypatch.setattr(ts_cov, "get_src_path", lambda: tmp_path / "src")
        prod = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        result = _resolve_import("~/utils", "/any/test.ts", {prod}, "typescript")
        assert result == prod

    def test_alias_resolves_relative_production_paths(self, tmp_path, monkeypatch):
        """Alias resolution should also work when production paths are project-relative."""
        monkeypatch.setattr(ts_cov, "get_src_path", lambda: tmp_path / "src")
        monkeypatch.setattr(ts_cov, "get_project_root", lambda: tmp_path)
        _write_file(
            tmp_path,
            "src/components/Button.tsx",
            "export default function Button() {}\n",
        )
        result = _resolve_import(
            "@/components/Button",
            "/any/test.ts",
            {"src/components/Button.tsx"},
            "typescript",
        )
        assert result == "src/components/Button.tsx"

    def test_index_ts_extension_probing(self, tmp_path):
        """Bare directory import resolves to index.ts."""
        prod = _write_file(
            tmp_path, "src/components/index.ts", "export * from './Button';\n"
        )
        test = _write_file(tmp_path, "src/components.test.ts", "")
        result = _resolve_import("./components", test, {prod}, "typescript")
        assert result == prod

    def test_nonexistent_returns_none(self, tmp_path):
        test = _write_file(tmp_path, "src/test.ts", "")
        result = _resolve_import("./nonexistent", test, set(), "typescript")
        assert result is None

    def test_non_relative_returns_none(self):
        """Bare module specifiers (like 'react') return None."""
        result = _resolve_import("react", "/test.ts", set(), "typescript")
        assert result is None


# ── _resolve_barrel_reexports ────────────────────────────


class TestResolveBarrelReexports:
    def test_named_reexports(self, tmp_path):
        """export { Foo } from './foo' resolves the re-exported module."""
        foo = _write_file(tmp_path, "src/foo.ts", "export const Foo = 1;\n")
        barrel = _write_file(
            tmp_path,
            "src/index.ts",
            "export { Foo } from './foo';\nexport { Bar } from './bar';\n",
        )
        bar = _write_file(tmp_path, "src/bar.ts", "export const Bar = 2;\n")
        result = _resolve_barrel_reexports(barrel, {foo, bar})
        assert foo in result
        assert bar in result

    def test_star_reexport(self, tmp_path):
        """export * from './utils' resolves."""
        utils = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        barrel = _write_file(tmp_path, "src/index.ts", "export * from './utils';\n")
        result = _resolve_barrel_reexports(barrel, {utils})
        assert utils in result

    def test_non_barrel_file(self, tmp_path):
        """File with no re-exports returns empty set."""
        f = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        result = _resolve_barrel_reexports(f, set())
        assert result == set()

    def test_nonexistent_file(self):
        result = _resolve_barrel_reexports("/no/such/file.ts", set())
        assert result == set()

    def test_barrel_expansion_in_import_mapping(self, tmp_path):
        """Integration: barrel imports expand to re-exported modules."""
        utils = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        helpers = _write_file(tmp_path, "src/helpers.ts", "export const y = 2;\n")
        barrel = _write_file(
            tmp_path,
            "src/index.ts",
            "export * from './utils';\nexport { y } from './helpers';\n",
        )
        test = _write_file(
            tmp_path,
            "src/__tests__/test.ts",
            "import { x, y } from '../index';\n",
        )
        production = {utils, helpers, barrel}
        graph = {}
        result = import_based_mapping(graph, {test}, production)
        assert barrel in result
        assert utils in result
        assert helpers in result

    def test_prod_module_index_drops_ambiguous_basename_aliases(
        self,
        tmp_path,
        monkeypatch,
    ):
        util_a = _write_file(tmp_path, "pkg/util.py", "# a\n")
        util_b = _write_file(tmp_path, "services/util.py", "# b\n")
        monkeypatch.setattr(
            "desloppify.engine.detectors.coverage.mapping.get_project_root",
            lambda: tmp_path,
        )

        index = _build_prod_module_index({util_a, util_b})

        assert index["pkg.util"] == util_a
        assert index["services.util"] == util_b
        assert "util" not in index


# ── Comment stripping in assertion counting ──────────────


class TestCommentStripping:
    def test_ts_comment_not_counted(self, tmp_path):
        """Assertions in TS // comments should not be counted."""
        content = (
            'it("a", () => {\n  // expect(foo).toBe(1);\n  expect(bar).toBe(2);\n});\n'
        )
        tf = _write_file(tmp_path, "foo.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] == 1

    def test_ts_block_comment_not_counted(self, tmp_path):
        """Assertions in TS /* */ comments should not be counted."""
        content = (
            'it("a", () => {\n'
            "  /* expect(foo).toBe(1); */\n"
            "  expect(bar).toBe(2);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "bar.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] == 1

    def test_py_comment_not_counted(self, tmp_path):
        """Assertions in Python # comments should not be counted."""
        content = (
            "def test_a():\n"
            "    # assert False\n"
            "    assert True\n"
            "    assert True\n"
            "    assert True\n"
        )
        tf = _write_file(tmp_path, "test_commented.py", content)
        result = analyze_test_quality({tf}, "python")
        assert result[tf]["assertions"] == 3

    def test_py_comment_in_string_not_stripped(self):
        """# inside strings should NOT be treated as comments."""
        assert _strip_py_comment('x = "has # in string"') == 'x = "has # in string"'
        assert _strip_py_comment("x = 'has # in string'") == "x = 'has # in string'"

    def test_py_comment_strips_after_code(self):
        """# after code should be stripped."""
        assert _strip_py_comment("x = 1  # comment").rstrip() == "x = 1"


# ── RTL assertion patterns ───────────────────────────────


class TestTypeLevelAssertions:
    def test_vitest_expect_type_of_calls_count_as_assertions(self, tmp_path):
        content = (
            "import { expectTypeOf, it } from 'vitest';\n"
            "it('checks types', () => {\n"
            "  expectTypeOf(value).toEqualTypeOf<string>();\n"
            "  expectTypeOf<Readonly<Array<string>>>().toMatchTypeOf(value);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "types.test.ts", content)

        result = analyze_test_quality({tf}, "typescript")

        assert result[tf]["assertions"] == 2
        assert result[tf]["quality"] == "adequate"

    def test_imported_expect_type_of_without_call_is_not_an_assertion(self, tmp_path):
        content = (
            "import { expectTypeOf, it } from 'vitest';\n"
            "it('does not check a type', () => {});\n"
        )
        tf = _write_file(tmp_path, "types-unused.test.ts", content)

        result = analyze_test_quality({tf}, "typescript")

        assert result[tf]["assertions"] == 0
        assert result[tf]["quality"] == "assertion_free"


class TestRTLPatterns:
    def test_getby_counted(self, tmp_path):
        content = "it(\"renders\", () => {\n  screen.getByText('hello');\n});\n"
        tf = _write_file(tmp_path, "comp.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] >= 1

    def test_findby_counted(self, tmp_path):
        content = (
            "it(\"finds\", async () => {\n  await screen.findByRole('button');\n});\n"
        )
        tf = _write_file(tmp_path, "comp2.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] >= 1

    def test_waitfor_counted(self, tmp_path):
        content = 'it("waits", async () => {\n  await waitFor(() => {});\n});\n'
        tf = _write_file(tmp_path, "comp3.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] >= 1

    def test_jest_dom_matchers(self, tmp_path):
        content = (
            'it("checks dom", () => {\n'
            "  expect(el).toBeInTheDocument();\n"
            "  expect(el).toBeVisible();\n"
            "  expect(el).toHaveTextContent('hello');\n"
            "  expect(el).toHaveAttribute('id');\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "dom.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        # Each line matches at least one pattern; any() per line → 4
        assert result[tf]["assertions"] == 4

    def test_no_double_counting(self, tmp_path):
        """expect(el).toBeVisible() should count as 1, not 2."""
        content = 'it("check", () => {\n  expect(el).toBeVisible();\n});\n'
        tf = _write_file(tmp_path, "dbl.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] == 1

    def test_destructured_queries(self, tmp_path):
        """Destructured RTL queries like getByText(...) should count."""
        content = (
            'it("destr", () => {\n'
            "  const { getByText } = render(<Comp />);\n"
            "  getByText('hello');\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "destr.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        # getByText( appears on both lines but 2nd is the assertion
        assert result[tf]["assertions"] >= 1

    def test_rtl_quality_adequate(self, tmp_path):
        """RTL-heavy test should be classified as adequate/thorough, not assertion_free."""
        content = (
            'it("renders", () => {\n'
            "  screen.getByText('hello');\n"
            "  screen.getByRole('button');\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "rtl.test.tsx", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] in ("adequate", "thorough")


# ── Transitive coverage semantics ────────────────────────


class TestTransitiveSemantics:
    def test_transitive_high_importers_tier_2(self, tmp_path):
        """Transitive-only file with >=10 importers gets tier 2."""
        prod_a = _write_file(
            tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13
        )
        prod_b = _write_file(
            tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13
        )
        test_a = _write_file(
            tmp_path,
            "test_a.py",
            "def test_a():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_a, prod_b, test_a]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": {prod_b}, "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 15},
            test_a: {"imports": {prod_a}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        trans = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans) == 1
        assert trans[0]["tier"] == 2
        assert "covered only via imports" in trans[0]["summary"]

    def test_transitive_low_importers_tier_3(self, tmp_path):
        """Transitive-only file with <10 importers stays at tier 3."""
        prod_a = _write_file(
            tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13
        )
        prod_b = _write_file(
            tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13
        )
        test_a = _write_file(
            tmp_path,
            "test_a.py",
            "def test_a():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_a, prod_b, test_a]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": {prod_b}, "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 2},
            test_a: {"imports": {prod_a}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        trans = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans) == 1
        assert trans[0]["tier"] == 3

    def test_transitive_summary_text(self, tmp_path):
        """Transitive issue summary has clarified text."""
        prod_a = _write_file(
            tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13
        )
        prod_b = _write_file(
            tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13
        )
        test_a = _write_file(
            tmp_path,
            "test_a.py",
            "def test_a():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_a, prod_b, test_a]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": {prod_b}, "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 1},
            test_a: {"imports": {prod_a}},
        }
        entries, _ = detect_test_coverage(graph, zone_map, "python")
        trans = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans) == 1
        assert "No direct tests" in trans[0]["summary"]
        assert "covered only via imports from tested modules" in trans[0]["summary"]


# ── Complexity-weighted tier upgrade ──────────────────────


class TestComplexityTierUpgrade:
    def test_untested_complex_file_tier_2(self, tmp_path):
        """Untested file with high complexity score → tier 2 (critical)."""
        prod = _write_file(
            tmp_path, "complex.py", "def process():\n    pass\n" + "# code\n" * 18
        )
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 1}}
        # Complexity score above threshold (20)
        cmap = {prod: 25}
        entries, _ = detect_test_coverage(
            graph, zone_map, "python", complexity_map=cmap
        )
        assert len(entries) == 1
        assert entries[0]["tier"] == 2
        assert entries[0]["detail"]["kind"] == "untested_critical"
        assert entries[0]["detail"]["complexity_score"] == 25

    def test_untested_simple_file_stays_tier_3(self, tmp_path):
        """Untested file without high complexity stays at tier 3."""
        prod = _write_file(
            tmp_path, "simple.py", "def run():\n    pass\n" + "# code\n" * 18
        )
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 1}}
        # Complexity score below threshold
        cmap = {prod: 15}
        entries, _ = detect_test_coverage(
            graph, zone_map, "python", complexity_map=cmap
        )
        assert len(entries) == 1
        assert entries[0]["tier"] == 3
        assert entries[0]["detail"]["kind"] == "untested_module"
        assert "complexity_score" not in entries[0]["detail"]

    def test_transitive_complex_file_tier_2(self, tmp_path):
        """Transitive-only file with high complexity → tier 2."""
        prod_a = _write_file(
            tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13
        )
        prod_b = _write_file(
            tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 18
        )
        test_a = _write_file(
            tmp_path,
            "test_a.py",
            "def test_a():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_a, prod_b, test_a]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": {prod_b}, "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 2},
            test_a: {"imports": {prod_a}},
        }
        cmap = {prod_b: 30}
        entries, _ = detect_test_coverage(
            graph, zone_map, "python", complexity_map=cmap
        )
        trans = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans) == 1
        assert trans[0]["tier"] == 2
        assert trans[0]["detail"]["complexity_score"] == 30

    def test_no_complexity_map_no_upgrade(self, tmp_path):
        """Without complexity_map, no tier upgrade for untested files."""
        prod = _write_file(
            tmp_path, "mod.py", "def run():\n    pass\n" + "# code\n" * 18
        )
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 2}}
        entries, _ = detect_test_coverage(graph, zone_map, "python")
        assert len(entries) == 1
        assert entries[0]["tier"] == 3

    def test_complexity_at_threshold_upgrades(self, tmp_path):
        """Complexity exactly at threshold (20) should upgrade."""
        prod = _write_file(
            tmp_path, "edge.py", "def run():\n    pass\n" + "# code\n" * 18
        )
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 1}}
        cmap = {prod: 20}
        entries, _ = detect_test_coverage(
            graph, zone_map, "python", complexity_map=cmap
        )
        assert len(entries) == 1
        assert entries[0]["tier"] == 2


# ── _has_testable_logic ──────────────────────────────────


class TestHasTestableLogic:
    """Test the non-testable file filter."""

    # ── .d.ts files ──

    def test_dts_file_excluded(self, tmp_path):
        """TypeScript .d.ts type definition files have no runtime behavior."""
        f = _write_file(
            tmp_path, "types.d.ts", "export interface Foo { bar: string; }\n"
        )
        assert _has_testable_logic(f, "typescript") is False

    # ── TypeScript type-only files ──

    def test_ts_type_only_file(self, tmp_path):
        """File with only type/interface declarations and imports."""
        content = (
            "import { BaseType } from './base';\n"
            "\n"
            "export interface Foo {\n"
            "  bar: string;\n"
            "  baz: number;\n"
            "}\n"
            "\n"
            "export type FooId = string;\n"
            "\n"
            "type Internal = {\n"
            "  x: number;\n"
            "  y: number;\n"
            "};\n"
        )
        f = _write_file(tmp_path, "types.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    def test_ts_type_with_runtime_export(self, tmp_path):
        """File with types AND a runtime export has testable logic."""
        content = (
            "export interface Foo { bar: string; }\n"
            "export const DEFAULT_FOO: Foo = { bar: 'hello' };\n"
        )
        f = _write_file(tmp_path, "types.ts", content)
        assert _has_testable_logic(f, "typescript") is True

    def test_ts_type_alias_only(self, tmp_path):
        """File with only type aliases (no braces)."""
        content = (
            "export type Id = string;\n"
            "export type Name = string;\n"
            "type Internal = number | null;\n"
        )
        f = _write_file(tmp_path, "aliases.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    # ── TypeScript barrel/re-export files ──

    def test_ts_barrel_file(self, tmp_path):
        """Barrel file with only re-exports."""
        content = (
            "export { Foo, Bar } from './foo';\n"
            "export { Baz } from './baz';\n"
            "export * from './utils';\n"
        )
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    def test_ts_barrel_with_type_reexports(self, tmp_path):
        """Barrel file with type-only re-exports."""
        content = "export type { Foo } from './foo';\nexport { Bar } from './bar';\n"
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    def test_ts_barrel_multiline_reexport(self, tmp_path):
        """Barrel file with multi-line re-export."""
        content = "export {\n  Foo,\n  Bar,\n  Baz,\n} from './module';\n"
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    def test_ts_barrel_with_runtime_code(self, tmp_path):
        """Barrel file that also has runtime code is testable."""
        content = "export { Foo } from './foo';\nexport const VERSION = '1.0.0';\n"
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is True

    # ── TypeScript files with runtime logic ──

    def test_ts_function_file(self, tmp_path):
        """File with a function definition is testable."""
        content = (
            "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
        )
        f = _write_file(tmp_path, "math.ts", content)
        assert _has_testable_logic(f, "typescript") is True

    def test_ts_const_arrow_function(self, tmp_path):
        """File with a const arrow function is testable."""
        content = "export const add = (a: number, b: number) => a + b;\n"
        f = _write_file(tmp_path, "math.ts", content)
        assert _has_testable_logic(f, "typescript") is True

    def test_ts_class_file(self, tmp_path):
        """File with a class is testable."""
        content = "export class Service {\n  getValue() { return 42; }\n}\n"
        f = _write_file(tmp_path, "service.ts", content)
        assert _has_testable_logic(f, "typescript") is True

    def test_ts_react_component(self, tmp_path):
        """React component file is testable (has runtime JSX)."""
        content = (
            "import React from 'react';\n"
            "\n"
            "export function Badge({ label }: { label: string }) {\n"
            "  return <span>{label}</span>;\n"
            "}\n"
        )
        f = _write_file(tmp_path, "Badge.tsx", content)
        assert _has_testable_logic(f, "typescript") is True

    # ── TypeScript ambient declarations ──

    def test_ts_declare_only(self, tmp_path):
        """File with only ambient declarations (declare module, etc.)."""
        content = (
            "declare module '*.svg' {\n"
            "  const content: string;\n"
            "  export default content;\n"
            "}\n"
            "\n"
            "declare module '*.css' {\n"
            "  const classes: Record<string, string>;\n"
            "  export default classes;\n"
            "}\n"
        )
        f = _write_file(tmp_path, "declarations.d.ts", content)
        assert ts_has_testable_logic(str(f), content) is False

    # ── TypeScript multiline imports ──

    def test_ts_multiline_import_not_testable(self, tmp_path):
        """Multiline import followed by type declarations."""
        content = (
            "import {\n"
            "  TypeA,\n"
            "  TypeB,\n"
            "  TypeC,\n"
            "} from './types';\n"
            "\n"
            "export interface Combined {\n"
            "  a: TypeA;\n"
            "  b: TypeB;\n"
            "}\n"
        )
        f = _write_file(tmp_path, "combined.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    # ── TypeScript block comments ──

    def test_ts_block_comment_ignored(self, tmp_path):
        """Block comments don't count as testable logic."""
        content = "/**\n * This module defines types.\n */\nexport type Id = string;\n"
        f = _write_file(tmp_path, "types.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    # ── Python files ──

    def test_py_file_with_def(self, tmp_path):
        """Python file with function definition is testable."""
        content = "import os\n\ndef compute(x):\n    return x * 2\n"
        f = _write_file(tmp_path, "utils.py", content)
        assert _has_testable_logic(f, "python") is True

    def test_py_file_with_async_def(self, tmp_path):
        """Python file with async function is testable."""
        content = "import asyncio\n\nasync def fetch():\n    pass\n"
        f = _write_file(tmp_path, "async_utils.py", content)
        assert _has_testable_logic(f, "python") is True

    def test_py_file_constants_only(self, tmp_path):
        """Python file with only imports and constants — not testable."""
        content = (
            "from enum import Enum\n"
            "\n"
            "MAX_RETRIES = 3\n"
            "TIMEOUT = 30\n"
            "API_URL = 'https://example.com'\n"
            "\n"
            "# Status codes\n"
            "SUCCESS = 200\n"
            "NOT_FOUND = 404\n"
            "SERVER_ERROR = 500\n"
            "EXTRA_LINE = 'padding'\n"
        )
        f = _write_file(tmp_path, "constants.py", content)
        assert _has_testable_logic(f, "python") is False

    def test_py_init_barrel(self, tmp_path):
        """Python __init__.py barrel with only imports — not testable."""
        content = (
            "from .foo import Foo\n"
            "from .bar import Bar, Baz\n"
            "from .utils import helper\n"
            "\n"
            "__all__ = ['Foo', 'Bar', 'Baz', 'helper']\n"
            "\n"
            "# Re-exports\n"
            "# More padding lines\n"
            "# Even more padding\n"
            "# And more\n"
        )
        f = _write_file(tmp_path, "__init__.py", content)
        assert _has_testable_logic(f, "python") is False

    def test_py_class_with_methods(self, tmp_path):
        """Python file with a class that has methods is testable."""
        content = (
            "class Processor:\n    def process(self, data):\n        return data\n"
        )
        f = _write_file(tmp_path, "processor.py", content)
        assert _has_testable_logic(f, "python") is True

    def test_py_method_inside_class(self, tmp_path):
        """Indented def inside a class counts as testable."""
        content = (
            "import os\n"
            "\n"
            "class Config:\n"
            "    x = 1\n"
            "    y = 2\n"
            "\n"
            "    def validate(self):\n"
            "        return self.x > 0\n"
            "\n"
            "# padding\n"
            "# more padding\n"
        )
        f = _write_file(tmp_path, "config.py", content)
        assert _has_testable_logic(f, "python") is True

    def test_nonexistent_file_not_testable(self):
        """Unreadable file follows the detector's non-testable fallback."""
        assert _has_testable_logic("/no/such/file.py", "python") is False

    # ── Integration: non-testable files excluded from scorable set ──

    def test_type_only_ts_excluded_from_issues(self, tmp_path):
        """Type-only TS file produces no test_coverage issues."""
        type_file = _write_file(
            tmp_path,
            "types.ts",
            "export interface Foo {\n  bar: string;\n  baz: number;\n}\n"
            "export type Id = string;\n"
            "export type Name = string;\n"
            "// padding\n" * 5,
        )
        zone_map = _make_zone_map([type_file])
        graph = {type_file: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "typescript")
        assert entries == []
        assert potential == 0

    def test_barrel_ts_excluded_from_issues(self, tmp_path):
        """Barrel TS file produces no test_coverage issues."""
        barrel = _write_file(
            tmp_path,
            "index.ts",
            "export { Foo } from './foo';\n"
            "export { Bar } from './bar';\n"
            "export * from './utils';\n"
            "// padding\n" * 8,
        )
        zone_map = _make_zone_map([barrel])
        graph = {barrel: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "typescript")
        assert entries == []
        assert potential == 0

    def test_py_constants_excluded_from_issues(self, tmp_path):
        """Python constants-only file produces no test_coverage issues."""
        const_file = _write_file(
            tmp_path,
            "constants.py",
            "MAX_RETRIES = 3\nTIMEOUT = 30\nAPI_URL = 'https://example.com'\n"
            "SUCCESS = 200\nNOT_FOUND = 404\nSERVER_ERROR = 500\n"
            "EXTRA_1 = 'a'\nEXTRA_2 = 'b'\nEXTRA_3 = 'c'\nEXTRA_4 = 'd'\n",
        )
        zone_map = _make_zone_map([const_file])
        graph = {const_file: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert entries == []
        assert potential == 0

    def test_runtime_file_still_produces_issues(self, tmp_path):
        """File with runtime logic still produces issues (not excluded)."""
        prod = _write_file(
            tmp_path,
            "utils.ts",
            "export function add(a: number, b: number) {\n"
            "  return a + b;\n"
            "}\n"
            "// padding\n" * 8,
        )
        zone_map = _make_zone_map([prod])
        graph = {prod: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "typescript")
        assert potential > 0
        assert len(entries) >= 1

    def test_supabase_entrypoint_classified_separately(self, tmp_path):
        """Supabase edge index.ts should use runtime_entrypoint_no_direct_tests."""
        prod = _write_file(
            tmp_path, "supabase/functions/stripe-webhook/index.ts",
            "import { serve } from \"https://deno.land/std/http/server.ts\";\n"
            "serve((_req) => new Response(\"ok\"));\n"
            "// padding\n" * 8,
        )
        zone_map = _make_zone_map([prod])
        graph = {prod: {"imports": set(), "importer_count": 0}}
        entries, _ = detect_test_coverage(graph, zone_map, "typescript")
        assert len(entries) == 1
        assert entries[0]["detail"]["kind"] == "runtime_entrypoint_no_direct_tests"
        assert entries[0]["detail"]["loc_weight"] == 0.0

    def test_deno_serve_file_classified_as_runtime_entrypoint(self, tmp_path):
        """Deno serve entrypoint should not be classified as untested_module."""
        prod = _write_file(
            tmp_path, "edge/handler.ts",
            "import { serve } from \"jsr:@std/http/server\";\n"
            "serve((_req) => new Response(\"ok\"));\n"
            "// padding\n" * 8,
        )
        zone_map = _make_zone_map([prod])
        graph = {prod: {"imports": set(), "importer_count": 0}}
        entries, _ = detect_test_coverage(graph, zone_map, "typescript")
        assert len(entries) == 1
        assert entries[0]["detail"]["kind"] == "runtime_entrypoint_no_direct_tests"
