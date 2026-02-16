"""Tests for desloppify.detectors.test_coverage — test coverage gap detection."""

from __future__ import annotations

import os

import pytest

from desloppify.detectors.test_coverage import (
    _file_loc,
    _has_testable_logic,
    detect_test_coverage,
)
from desloppify.detectors.test_coverage_mapping import (
    _analyze_test_quality,
    _infer_lang_name,
    _import_based_mapping,
    _map_test_to_source,
    _naming_based_mapping,
    _parse_test_imports,
    _resolve_barrel_reexports,
    _resolve_import,
    _strip_py_comment,
    _strip_test_markers,
    _transitive_coverage,
)
from desloppify.lang.typescript.test_coverage import has_testable_logic as ts_has_testable_logic
from desloppify.zones import FileZoneMap, Zone, ZoneRule


# ── Helpers ────────────────────────────────────────────────


def _make_zone_map(file_list: list[str]) -> FileZoneMap:
    """Build a minimal FileZoneMap with standard test-detection rules."""
    rules = [ZoneRule(Zone.TEST, ["test_", ".test.", ".spec.", "/tests/", "/__tests__/"])]
    return FileZoneMap(file_list, rules)


def _write_file(tmp_path, relpath: str, content: str = "") -> str:
    """Write a file under tmp_path and return its absolute path."""
    p = tmp_path / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(p)


# ── _strip_test_markers ───────────────────────────────────


class TestStripTestMarkers:
    def test_python_test_prefix(self):
        assert _strip_test_markers("test_utils.py", "python") == "utils.py"

    def test_python_test_suffix(self):
        assert _strip_test_markers("utils_test.py", "python") == "utils.py"

    def test_python_no_marker(self):
        assert _strip_test_markers("utils.py", "python") is None

    def test_typescript_test_marker(self):
        assert _strip_test_markers("utils.test.ts", "typescript") == "utils.ts"

    def test_typescript_spec_tsx(self):
        assert _strip_test_markers("utils.spec.tsx", "typescript") == "utils.tsx"

    def test_typescript_no_marker(self):
        assert _strip_test_markers("utils.ts", "typescript") is None

    def test_typescript_spec_ts(self):
        assert _strip_test_markers("helpers.spec.ts", "typescript") == "helpers.ts"

    def test_python_test_prefix_nested(self):
        # Only basename is passed, so nested name shouldn't matter
        assert _strip_test_markers("test_deep_module.py", "python") == "deep_module.py"


# ── _infer_lang_name ──────────────────────────────────────


class TestInferLangName:
    def test_prefers_language_with_matching_extensions(self):
        result = _infer_lang_name({"tests/test_utils.py"}, {"src/utils.py"})
        assert result == "python"

    def test_returns_none_when_no_languages_available(self, monkeypatch):
        monkeypatch.setattr("desloppify.lang.available_langs", lambda: [])
        result = _infer_lang_name(set(), set())
        assert result is None

    def test_returns_none_when_paths_have_no_known_extensions(self):
        result = _infer_lang_name({"docs/test_notes.txt"}, {"docs/notes.txt"})
        assert result is None


# ── _map_test_to_source ──────────────────────────────────


class TestMapTestToSource:
    def test_python_test_prefix_same_dir(self):
        prod_set = {"src/utils.py"}
        result = _map_test_to_source("src/test_utils.py", prod_set, "python")
        assert result == "src/utils.py"

    def test_python_test_prefix_parent_dir(self):
        prod_set = {"src/utils.py"}
        result = _map_test_to_source("src/tests/test_utils.py", prod_set, "python")
        assert result == "src/utils.py"

    def test_python_test_suffix(self):
        prod_set = {"src/utils.py"}
        result = _map_test_to_source("src/utils_test.py", prod_set, "python")
        assert result == "src/utils.py"

    def test_typescript_test_marker(self):
        prod_set = {"src/utils.ts"}
        result = _map_test_to_source("src/utils.test.ts", prod_set, "typescript")
        assert result == "src/utils.ts"

    def test_typescript_spec_marker(self):
        prod_set = {"src/utils.tsx"}
        result = _map_test_to_source("src/utils.spec.tsx", prod_set, "typescript")
        assert result == "src/utils.tsx"

    def test_typescript_tests_dir(self):
        prod_set = {"src/utils.ts"}
        result = _map_test_to_source("src/__tests__/utils.ts", prod_set, "typescript")
        assert result == "src/utils.ts"

    def test_no_match_returns_none(self):
        prod_set = {"src/other.py"}
        result = _map_test_to_source("src/test_utils.py", prod_set, "python")
        assert result is None

    def test_no_match_typescript(self):
        prod_set = {"src/other.ts"}
        result = _map_test_to_source("src/utils.test.ts", prod_set, "typescript")
        assert result is None


# ── _file_loc ─────────────────────────────────────────────


class TestFileLoc:
    def test_counts_lines(self, tmp_path):
        path = _write_file(tmp_path, "sample.py", "line1\nline2\nline3\n")
        assert _file_loc(path) == 3

    def test_empty_file(self, tmp_path):
        path = _write_file(tmp_path, "empty.py", "")
        assert _file_loc(path) == 0

    def test_nonexistent_file(self):
        assert _file_loc("/nonexistent/path/file.py") == 0

    def test_single_line_no_newline(self, tmp_path):
        path = _write_file(tmp_path, "one.py", "hello")
        assert _file_loc(path) == 1


# ── _import_based_mapping ────────────────────────────────


class TestImportBasedMapping:
    def test_test_imports_production(self):
        graph = {
            "tests/test_foo.py": {"imports": {"src/foo.py", "src/bar.py"}},
        }
        test_files = {"tests/test_foo.py"}
        production_files = {"src/foo.py", "src/bar.py", "src/baz.py"}
        result = _import_based_mapping(graph, test_files, production_files)
        assert result == {"src/foo.py", "src/bar.py"}

    def test_test_imports_non_production_excluded(self):
        graph = {
            "tests/test_foo.py": {"imports": {"external_lib"}},
        }
        test_files = {"tests/test_foo.py"}
        production_files = {"src/foo.py"}
        result = _import_based_mapping(graph, test_files, production_files)
        assert result == set()

    def test_test_not_in_graph_skipped(self):
        graph = {}
        test_files = {"tests/test_foo.py"}
        production_files = {"src/foo.py"}
        # The test file isn't in graph, so it falls through to _parse_test_imports
        # which tries to read the file — nonexistent file returns empty set
        result = _import_based_mapping(graph, test_files, production_files)
        assert result == set()

    def test_external_test_file_parsed(self, tmp_path):
        """External test files not in graph are parsed from source.

        _import_based_mapping builds prod_by_module from absolute paths, so
        the test import must reference the last component of the production
        module name (basename without extension) which is also indexed.
        """
        prod_file = _write_file(tmp_path, "src/utils.py", "# production code\n" * 15)
        # Import "utils" — _import_based_mapping indexes basename "utils" → prod_file
        test_file = _write_file(
            tmp_path, "external_tests/test_utils.py",
            "import utils\n\ndef test_it():\n    assert True\n",
        )
        graph = {}
        test_files = {test_file}
        production_files = {prod_file}
        result = _import_based_mapping(graph, test_files, production_files)
        assert prod_file in result

    def test_multiple_test_files(self):
        graph = {
            "tests/test_a.py": {"imports": {"src/a.py"}},
            "tests/test_b.py": {"imports": {"src/b.py"}},
        }
        test_files = {"tests/test_a.py", "tests/test_b.py"}
        production_files = {"src/a.py", "src/b.py", "src/c.py"}
        result = _import_based_mapping(graph, test_files, production_files)
        assert result == {"src/a.py", "src/b.py"}


# ── _parse_test_imports ──────────────────────────────────


class TestParseTestImports:
    def test_python_from_import(self, tmp_path):
        tf = _write_file(tmp_path, "test_x.py", "from mymod import func\n")
        prod = {str(tmp_path / "mymod.py")}
        prod_by_module = {"mymod": str(tmp_path / "mymod.py")}
        result = _parse_test_imports(tf, prod, prod_by_module)
        assert str(tmp_path / "mymod.py") in result

    def test_python_import_statement(self, tmp_path):
        tf = _write_file(tmp_path, "test_x.py", "import mymod\n")
        prod = {str(tmp_path / "mymod.py")}
        prod_by_module = {"mymod": str(tmp_path / "mymod.py")}
        result = _parse_test_imports(tf, prod, prod_by_module)
        assert str(tmp_path / "mymod.py") in result

    def test_ts_import(self, tmp_path):
        tf = _write_file(tmp_path, "test_x.ts", 'import { foo } from "./utils"\n')
        prod = {str(tmp_path / "utils.ts")}
        prod_by_module = {"utils": str(tmp_path / "utils.ts")}
        result = _parse_test_imports(tf, prod, prod_by_module)
        assert str(tmp_path / "utils.ts") in result

    def test_nonexistent_file(self):
        result = _parse_test_imports("/no/such/file.py", set(), {})
        assert result == set()

    def test_dotted_python_import(self, tmp_path):
        tf = _write_file(tmp_path, "test_x.py", "from pkg.sub.mod import func\n")
        prod_path = "pkg/sub/mod.py"
        prod = {prod_path}
        prod_by_module = {
            "pkg.sub.mod": prod_path,
            "pkg.sub": "pkg/sub/__init__.py",
            "mod": prod_path,
        }
        result = _parse_test_imports(tf, prod, prod_by_module)
        assert prod_path in result


# ── _transitive_coverage ─────────────────────────────────


class TestTransitiveCoverage:
    def test_bfs_chain(self):
        """A→B→C: if A is directly tested, B and C are transitively tested."""
        graph = {
            "a.py": {"imports": {"b.py"}},
            "b.py": {"imports": {"c.py"}},
            "c.py": {"imports": set()},
        }
        production = {"a.py", "b.py", "c.py"}
        directly_tested = {"a.py"}
        result = _transitive_coverage(directly_tested, graph, production)
        assert result == {"b.py", "c.py"}

    def test_stops_at_non_production(self):
        """BFS stops at files not in production set."""
        graph = {
            "a.py": {"imports": {"b.py", "vendor/lib.py"}},
            "b.py": {"imports": set()},
        }
        production = {"a.py", "b.py"}
        directly_tested = {"a.py"}
        result = _transitive_coverage(directly_tested, graph, production)
        assert "vendor/lib.py" not in result
        assert result == {"b.py"}

    def test_excludes_directly_tested(self):
        """Directly tested files should NOT appear in transitive result."""
        graph = {
            "a.py": {"imports": {"b.py"}},
            "b.py": {"imports": set()},
        }
        production = {"a.py", "b.py"}
        directly_tested = {"a.py"}
        result = _transitive_coverage(directly_tested, graph, production)
        assert "a.py" not in result
        assert result == {"b.py"}

    def test_empty_graph(self):
        result = _transitive_coverage({"a.py"}, {}, {"a.py", "b.py"})
        assert result == set()

    def test_diamond_dependency(self):
        """A→B, A→C, B→D, C→D: D should only appear once."""
        graph = {
            "a.py": {"imports": {"b.py", "c.py"}},
            "b.py": {"imports": {"d.py"}},
            "c.py": {"imports": {"d.py"}},
            "d.py": {"imports": set()},
        }
        production = {"a.py", "b.py", "c.py", "d.py"}
        directly_tested = {"a.py"}
        result = _transitive_coverage(directly_tested, graph, production)
        assert result == {"b.py", "c.py", "d.py"}

    def test_no_directly_tested(self):
        """Empty directly_tested → empty transitive."""
        graph = {"a.py": {"imports": {"b.py"}}}
        result = _transitive_coverage(set(), graph, {"a.py", "b.py"})
        assert result == set()


# ── _analyze_test_quality ────────────────────────────────


class TestAnalyzeTestQuality:
    # Python test function counting uses MULTILINE and should count all test defs.

    def test_python_thorough(self, tmp_path):
        # Single test function with many assertions → thorough
        content = (
            "def test_a():\n"
            "    assert 1 == 1\n"
            "    assert 2 == 2\n"
            "    assert 3 == 3\n"
            "    assert 4 == 4\n"
        )
        tf = _write_file(tmp_path, "test_thorough.py", content)
        result = _analyze_test_quality({tf}, "python")
        assert tf in result
        assert result[tf]["quality"] == "thorough"
        assert result[tf]["assertions"] >= 4
        assert result[tf]["test_functions"] == 1

    def test_python_adequate(self, tmp_path):
        content = (
            "def test_a():\n"
            "    assert 1 == 1\n"
            "    assert 2 == 2\n"
        )
        tf = _write_file(tmp_path, "test_adequate.py", content)
        result = _analyze_test_quality({tf}, "python")
        assert result[tf]["quality"] in ("thorough", "adequate")

    def test_python_assertion_free(self, tmp_path):
        content = (
            "def test_a():\n"
            "    pass\n"
        )
        tf = _write_file(tmp_path, "test_noassert.py", content)
        result = _analyze_test_quality({tf}, "python")
        assert result[tf]["quality"] == "assertion_free"
        assert result[tf]["assertions"] == 0
        assert result[tf]["test_functions"] == 1

    def test_python_over_mocked(self, tmp_path):
        content = (
            "def test_a(m1, m2, m3):\n"
            "    assert True\n"
            "\n"
            "# mocks scattered in setup\n"
            "@mock.patch('module.thing')\n"
            "@mock.patch('module.other')\n"
            "@mock.patch('module.third')\n"
        )
        tf = _write_file(tmp_path, "test_mocked.py", content)
        result = _analyze_test_quality({tf}, "python")
        assert result[tf]["quality"] == "over_mocked"
        assert result[tf]["mocks"] > result[tf]["assertions"]

    def test_python_counts_multiple_test_functions(self, tmp_path):
        content = (
            "def test_a():\n"
            "    assert True\n"
            "\n"
            "def test_b():\n"
            "    pass\n"
            "\n"
            "def test_c():\n"
            "    pass\n"
        )
        tf = _write_file(tmp_path, "test_multi.py", content)
        result = _analyze_test_quality({tf}, "python")
        assert result[tf]["test_functions"] == 3
        assert result[tf]["quality"] == "smoke"

    def test_typescript_snapshot_heavy(self, tmp_path):
        content = (
            'it("renders", () => {\n'
            "  expect(component).toMatchSnapshot();\n"
            "  expect(component).toMatchSnapshot();\n"
            "  expect(component).toMatchSnapshot();\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "utils.test.ts", content)
        result = _analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] == "snapshot_heavy"
        assert result[tf]["snapshots"] >= 3

    def test_python_smoke(self, tmp_path):
        """TS test function count supports smoke classification (<1 assertion per test)."""
        content = (
            'it("a", () => {});\n'
            'it("b", () => {});\n'
            'it("c", () => {});\n'
            "expect(foo).toBe(1);\n"
        )
        tf = _write_file(tmp_path, "smoke.test.ts", content)
        result = _analyze_test_quality({tf}, "typescript")
        # 1 assertion across 3 test functions → ratio < 1 → smoke
        assert result[tf]["quality"] == "smoke"

    def test_no_test_functions(self, tmp_path):
        content = "# just a comment\nprint('hello')\n"
        tf = _write_file(tmp_path, "test_empty.py", content)
        result = _analyze_test_quality({tf}, "python")
        assert result[tf]["quality"] == "no_tests"

    def test_nonexistent_file_skipped(self):
        result = _analyze_test_quality({"/no/such/file.py"}, "python")
        assert "/no/such/file.py" not in result

    def test_typescript_adequate(self, tmp_path):
        content = (
            'test("does thing", () => {\n'
            "  expect(foo).toBe(1);\n"
            "  expect(bar).toBe(2);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "foo.test.ts", content)
        result = _analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] in ("thorough", "adequate")


# ── detect_test_coverage (integration) ───────────────────


class TestDetectTestCoverage:
    def test_zero_production_files(self, tmp_path):
        """No production files → empty results, potential=0."""
        test_f = _write_file(tmp_path, "test_foo.py", "def test_x():\n    assert True\n")
        zone_map = _make_zone_map([test_f])
        graph = {}
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert entries == []
        assert potential == 0

    def test_zero_test_files_with_production(self, tmp_path):
        """Production files but no tests → untested_module findings."""
        prod_f = _write_file(tmp_path, "app.py", "def main():\n    pass\n" + "# code\n" * 13)
        zone_map = _make_zone_map([prod_f])
        graph = {prod_f: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        # Potential is LOC-weighted: round(sqrt(15)) = round(3.87) = 4
        assert potential > 0
        assert len(entries) >= 1
        assert entries[0]["detail"]["kind"] == "untested_module"
        assert "loc_weight" in entries[0]["detail"]

    def test_production_with_direct_test(self, tmp_path):
        """Production file with a direct test → no untested finding."""
        prod_f = _write_file(tmp_path, "utils.py", "def foo():\n    return 1\n" * 10)
        test_f = _write_file(
            tmp_path, "test_utils.py",
            "def test_foo():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_f, test_f]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": {prod_f}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential > 0
        # Should not have any untested_module or untested_critical findings
        untested = [e for e in entries if e["detail"]["kind"] in ("untested_module", "untested_critical")]
        assert untested == []

    def test_transitive_only_finding(self, tmp_path):
        """Production file covered only transitively → transitive_only finding."""
        prod_a = _write_file(tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13)
        prod_b = _write_file(tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13)
        test_a = _write_file(
            tmp_path, "test_a.py",
            "def test_a():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_a, prod_b, test_a]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": {prod_b}, "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 1},
            test_a: {"imports": {prod_a}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential > 0
        trans_entries = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans_entries) == 1
        assert trans_entries[0]["file"] == prod_b
        assert "loc_weight" in trans_entries[0]["detail"]

    def test_untested_critical_high_importers(self, tmp_path):
        """Untested file with >=10 importers → untested_critical (tier 2).

        Must have at least one test file to enter _generate_findings path
        (otherwise _no_tests_findings is used, which always emits untested_module).
        """
        prod_f = _write_file(tmp_path, "core.py", "def process():\n    pass\n" + "# critical code\n" * 13)
        other_prod = _write_file(tmp_path, "other.py", "def run():\n    pass\n" + "# other\n" * 13)
        test_other = _write_file(
            tmp_path, "test_other.py",
            "def test_other():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_f, other_prod, test_other]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_f: {"imports": set(), "importer_count": 15},
            other_prod: {"imports": set(), "importer_count": 0},
            test_other: {"imports": {other_prod}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential > 0
        critical = [e for e in entries if e["detail"]["kind"] == "untested_critical"]
        assert len(critical) == 1
        assert critical[0]["file"] == prod_f
        assert critical[0]["tier"] == 2
        assert "loc_weight" in critical[0]["detail"]

    def test_untested_module_low_importers(self, tmp_path):
        """Untested file with low importer count → untested_module (tier 3)."""
        prod_f = _write_file(tmp_path, "helper.py", "def helper():\n    pass\n" + "# helper code\n" * 13)
        zone_map = _make_zone_map([prod_f])
        graph = {prod_f: {"imports": set(), "importer_count": 2}}
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential > 0
        assert len(entries) >= 1
        assert entries[0]["detail"]["kind"] == "untested_module"
        assert entries[0]["tier"] == 3

    def test_extra_test_files(self, tmp_path):
        """extra_test_files parameter adds external test files to coverage."""
        prod_f = _write_file(tmp_path, "src/utils.py", "def foo():\n    return 1\n" * 10)
        # External test file outside the zone map
        ext_test = _write_file(
            tmp_path, "external/test_utils.py",
            "def test_foo():\n    assert True\n    assert True\n    assert True\n",
        )
        # Only production file in zone map
        zone_map = _make_zone_map([prod_f])
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            ext_test: {"imports": {prod_f}},
        }
        entries, potential = detect_test_coverage(
            graph, zone_map, "python", extra_test_files={ext_test},
        )
        assert potential > 0
        # prod_f should be directly tested via ext_test
        untested = [e for e in entries if e["detail"]["kind"] in ("untested_module", "untested_critical")]
        assert untested == []

    def test_loc_weighted_potential(self, tmp_path):
        """Potential is LOC-weighted: sum of sqrt(loc) capped at 50."""
        import math
        # 100-LOC file: sqrt(100) = 10
        prod_big = _write_file(tmp_path, "big.py", "def run():\n    pass\n" + "x = 1\n" * 98)
        # 25-LOC file: sqrt(25) = 5
        prod_small = _write_file(tmp_path, "small.py", "def run():\n    pass\n" + "x = 1\n" * 23)
        zone_map = _make_zone_map([prod_big, prod_small])
        graph = {
            prod_big: {"imports": set(), "importer_count": 0},
            prod_small: {"imports": set(), "importer_count": 0},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        expected = round(math.sqrt(100) + math.sqrt(25))  # 10 + 5 = 15
        assert potential == expected

    def test_small_files_excluded(self, tmp_path):
        """Files below _MIN_LOC threshold are not scorable."""
        tiny = _write_file(tmp_path, "tiny.py", "x = 1\n")
        zone_map = _make_zone_map([tiny])
        graph = {tiny: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential == 0
        assert entries == []

    def test_quality_finding_assertion_free(self, tmp_path):
        """Directly tested file with assertion-free test → quality finding."""
        prod_f = _write_file(tmp_path, "utils.py", "def foo():\n    return 1\n" * 10)
        test_f = _write_file(
            tmp_path, "test_utils.py",
            "def test_foo():\n    pass\n",
        )
        all_files = [prod_f, test_f]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": {prod_f}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential > 0
        qual_entries = [e for e in entries if e["detail"]["kind"] == "assertion_free_test"]
        assert len(qual_entries) == 1
        assert qual_entries[0]["file"] == prod_f

    def test_naming_convention_mapping(self, tmp_path):
        """Test file matched by naming convention (no graph import edge)."""
        prod_f = _write_file(tmp_path, "utils.py", "def foo():\n    return 1\n" * 10)
        test_f = _write_file(
            tmp_path, "test_utils.py",
            "def test_foo():\n    assert True\n    assert True\n    assert True\n",
        )
        all_files = [prod_f, test_f]
        zone_map = _make_zone_map(all_files)
        # Test file does NOT import production file via graph
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": set()},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert potential > 0
        # Should be matched by naming convention, not untested
        untested = [e for e in entries if e["detail"]["kind"] in ("untested_module", "untested_critical")]
        assert untested == []


# ── _naming_based_mapping ────────────────────────────────


class TestNamingBasedMapping:
    def test_python_test_prefix(self):
        test_files = {"src/test_utils.py"}
        production_files = {"src/utils.py"}
        result = _naming_based_mapping(test_files, production_files, "python")
        assert result == {"src/utils.py"}

    def test_python_test_suffix(self):
        test_files = {"src/utils_test.py"}
        production_files = {"src/utils.py"}
        result = _naming_based_mapping(test_files, production_files, "python")
        assert result == {"src/utils.py"}

    def test_typescript_test_marker(self):
        test_files = {"src/utils.test.ts"}
        production_files = {"src/utils.ts"}
        result = _naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/utils.ts"}

    def test_typescript_spec_marker(self):
        test_files = {"src/utils.spec.tsx"}
        production_files = {"src/utils.tsx"}
        result = _naming_based_mapping(test_files, production_files, "typescript")
        assert result == {"src/utils.tsx"}

    def test_no_match(self):
        test_files = {"src/test_foo.py"}
        production_files = {"src/bar.py"}
        result = _naming_based_mapping(test_files, production_files, "python")
        assert result == set()

    def test_fuzzy_basename_fallback(self):
        """Fuzzy basename matching when _map_test_to_source fails (different dir)."""
        test_files = {"completely/different/test_utils.py"}
        production_files = {"src/deep/utils.py"}
        result = _naming_based_mapping(test_files, production_files, "python")
        # _strip_test_markers("test_utils.py") → "utils.py"
        # prod_by_basename["utils.py"] → "src/deep/utils.py"
        assert result == {"src/deep/utils.py"}


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
        """@/components/Button resolves via SRC_PATH."""
        import desloppify.lang.typescript.test_coverage as ts_cov
        monkeypatch.setattr(ts_cov, "SRC_PATH", tmp_path / "src")
        prod = _write_file(tmp_path, "src/components/Button.tsx", "export default function Button() {}\n")
        result = _resolve_import("@/components/Button", "/any/test.ts", {prod}, "typescript")
        assert result == prod

    def test_alias_tilde(self, tmp_path, monkeypatch):
        """~/utils resolves via SRC_PATH."""
        import desloppify.lang.typescript.test_coverage as ts_cov
        monkeypatch.setattr(ts_cov, "SRC_PATH", tmp_path / "src")
        prod = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        result = _resolve_import("~/utils", "/any/test.ts", {prod}, "typescript")
        assert result == prod

    def test_index_ts_extension_probing(self, tmp_path):
        """Bare directory import resolves to index.ts."""
        prod = _write_file(tmp_path, "src/components/index.ts", "export * from './Button';\n")
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
            tmp_path, "src/index.ts",
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
            tmp_path, "src/index.ts",
            "export * from './utils';\nexport { y } from './helpers';\n",
        )
        test = _write_file(
            tmp_path, "src/__tests__/test.ts",
            "import { x, y } from '../index';\n",
        )
        production = {utils, helpers, barrel}
        graph = {}
        result = _import_based_mapping(graph, {test}, production)
        assert barrel in result
        assert utils in result
        assert helpers in result


# ── Comment stripping in assertion counting ──────────────


class TestCommentStripping:
    def test_ts_comment_not_counted(self, tmp_path):
        """Assertions in TS // comments should not be counted."""
        content = (
            'it("a", () => {\n'
            "  // expect(foo).toBe(1);\n"
            "  expect(bar).toBe(2);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "foo.test.ts", content)
        result = _analyze_test_quality({tf}, "typescript")
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
        result = _analyze_test_quality({tf}, "typescript")
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
        result = _analyze_test_quality({tf}, "python")
        assert result[tf]["assertions"] == 3

    def test_py_comment_in_string_not_stripped(self):
        """# inside strings should NOT be treated as comments."""
        assert _strip_py_comment('x = "has # in string"') == 'x = "has # in string"'
        assert _strip_py_comment("x = 'has # in string'") == "x = 'has # in string'"

    def test_py_comment_strips_after_code(self):
        """# after code should be stripped."""
        assert _strip_py_comment("x = 1  # comment").rstrip() == "x = 1"


# ── RTL assertion patterns ───────────────────────────────


class TestRTLPatterns:
    def test_getby_counted(self, tmp_path):
        content = (
            'it("renders", () => {\n'
            "  screen.getByText('hello');\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "comp.test.tsx", content)
        result = _analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] >= 1

    def test_findby_counted(self, tmp_path):
        content = (
            'it("finds", async () => {\n'
            "  await screen.findByRole('button');\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "comp2.test.tsx", content)
        result = _analyze_test_quality({tf}, "typescript")
        assert result[tf]["assertions"] >= 1

    def test_waitfor_counted(self, tmp_path):
        content = (
            'it("waits", async () => {\n'
            "  await waitFor(() => {});\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "comp3.test.tsx", content)
        result = _analyze_test_quality({tf}, "typescript")
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
        result = _analyze_test_quality({tf}, "typescript")
        # Each line matches at least one pattern; any() per line → 4
        assert result[tf]["assertions"] == 4

    def test_no_double_counting(self, tmp_path):
        """expect(el).toBeVisible() should count as 1, not 2."""
        content = (
            'it("check", () => {\n'
            "  expect(el).toBeVisible();\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "dbl.test.tsx", content)
        result = _analyze_test_quality({tf}, "typescript")
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
        result = _analyze_test_quality({tf}, "typescript")
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
        result = _analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] in ("adequate", "thorough")


# ── Transitive coverage semantics ────────────────────────


class TestTransitiveSemantics:
    def test_transitive_high_importers_tier_2(self, tmp_path):
        """Transitive-only file with >=10 importers gets tier 2."""
        prod_a = _write_file(tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13)
        prod_b = _write_file(tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13)
        test_a = _write_file(
            tmp_path, "test_a.py",
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
        prod_a = _write_file(tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13)
        prod_b = _write_file(tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13)
        test_a = _write_file(
            tmp_path, "test_a.py",
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
        """Transitive finding summary has clarified text."""
        prod_a = _write_file(tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13)
        prod_b = _write_file(tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 13)
        test_a = _write_file(
            tmp_path, "test_a.py",
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
        prod = _write_file(tmp_path, "complex.py", "def process():\n    pass\n" + "# code\n" * 18)
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 1}}
        # Complexity score above threshold (20)
        cmap = {prod: 25}
        entries, _ = detect_test_coverage(graph, zone_map, "python", complexity_map=cmap)
        assert len(entries) == 1
        assert entries[0]["tier"] == 2
        assert entries[0]["detail"]["kind"] == "untested_critical"
        assert entries[0]["detail"]["complexity_score"] == 25

    def test_untested_simple_file_stays_tier_3(self, tmp_path):
        """Untested file without high complexity stays at tier 3."""
        prod = _write_file(tmp_path, "simple.py", "def run():\n    pass\n" + "# code\n" * 18)
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 1}}
        # Complexity score below threshold
        cmap = {prod: 15}
        entries, _ = detect_test_coverage(graph, zone_map, "python", complexity_map=cmap)
        assert len(entries) == 1
        assert entries[0]["tier"] == 3
        assert entries[0]["detail"]["kind"] == "untested_module"
        assert "complexity_score" not in entries[0]["detail"]

    def test_transitive_complex_file_tier_2(self, tmp_path):
        """Transitive-only file with high complexity → tier 2."""
        prod_a = _write_file(tmp_path, "a.py", "import b\ndef run():\n    pass\n" + "# code\n" * 13)
        prod_b = _write_file(tmp_path, "b.py", "def helper():\n    pass\n" + "# code\n" * 18)
        test_a = _write_file(
            tmp_path, "test_a.py",
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
        entries, _ = detect_test_coverage(graph, zone_map, "python", complexity_map=cmap)
        trans = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans) == 1
        assert trans[0]["tier"] == 2
        assert trans[0]["detail"]["complexity_score"] == 30

    def test_no_complexity_map_no_upgrade(self, tmp_path):
        """Without complexity_map, no tier upgrade for untested files."""
        prod = _write_file(tmp_path, "mod.py", "def run():\n    pass\n" + "# code\n" * 18)
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 2}}
        entries, _ = detect_test_coverage(graph, zone_map, "python")
        assert len(entries) == 1
        assert entries[0]["tier"] == 3

    def test_complexity_at_threshold_upgrades(self, tmp_path):
        """Complexity exactly at threshold (20) should upgrade."""
        prod = _write_file(tmp_path, "edge.py", "def run():\n    pass\n" + "# code\n" * 18)
        all_files = [prod]
        zone_map = _make_zone_map(all_files)
        graph = {prod: {"imports": set(), "importer_count": 1}}
        cmap = {prod: 20}
        entries, _ = detect_test_coverage(graph, zone_map, "python", complexity_map=cmap)
        assert len(entries) == 1
        assert entries[0]["tier"] == 2


# ── _has_testable_logic ──────────────────────────────────


class TestHasTestableLogic:
    """Test the non-testable file filter."""

    # ── .d.ts files ──

    def test_dts_file_excluded(self, tmp_path):
        """TypeScript .d.ts type definition files have no runtime behavior."""
        f = _write_file(tmp_path, "types.d.ts", "export interface Foo { bar: string; }\n")
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
        content = (
            "export type { Foo } from './foo';\n"
            "export { Bar } from './bar';\n"
        )
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    def test_ts_barrel_multiline_reexport(self, tmp_path):
        """Barrel file with multi-line re-export."""
        content = (
            "export {\n"
            "  Foo,\n"
            "  Bar,\n"
            "  Baz,\n"
            "} from './module';\n"
        )
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    def test_ts_barrel_with_runtime_code(self, tmp_path):
        """Barrel file that also has runtime code is testable."""
        content = (
            "export { Foo } from './foo';\n"
            "export const VERSION = '1.0.0';\n"
        )
        f = _write_file(tmp_path, "index.ts", content)
        assert _has_testable_logic(f, "typescript") is True

    # ── TypeScript files with runtime logic ──

    def test_ts_function_file(self, tmp_path):
        """File with a function definition is testable."""
        content = (
            "export function add(a: number, b: number): number {\n"
            "  return a + b;\n"
            "}\n"
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
        content = (
            "export class Service {\n"
            "  getValue() { return 42; }\n"
            "}\n"
        )
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
        content = (
            "/**\n"
            " * This module defines types.\n"
            " */\n"
            "export type Id = string;\n"
        )
        f = _write_file(tmp_path, "types.ts", content)
        assert _has_testable_logic(f, "typescript") is False

    # ── Python files ──

    def test_py_file_with_def(self, tmp_path):
        """Python file with function definition is testable."""
        content = (
            "import os\n"
            "\n"
            "def compute(x):\n"
            "    return x * 2\n"
        )
        f = _write_file(tmp_path, "utils.py", content)
        assert _has_testable_logic(f, "python") is True

    def test_py_file_with_async_def(self, tmp_path):
        """Python file with async function is testable."""
        content = (
            "import asyncio\n"
            "\n"
            "async def fetch():\n"
            "    pass\n"
        )
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
            "class Processor:\n"
            "    def process(self, data):\n"
            "        return data\n"
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

    def test_nonexistent_file_assumed_testable(self):
        """Unreadable file is assumed testable (conservative)."""
        assert _has_testable_logic("/no/such/file.py", "python") is True

    # ── Integration: non-testable files excluded from scorable set ──

    def test_type_only_ts_excluded_from_findings(self, tmp_path):
        """Type-only TS file produces no test_coverage findings."""
        type_file = _write_file(
            tmp_path, "types.ts",
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

    def test_barrel_ts_excluded_from_findings(self, tmp_path):
        """Barrel TS file produces no test_coverage findings."""
        barrel = _write_file(
            tmp_path, "index.ts",
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

    def test_py_constants_excluded_from_findings(self, tmp_path):
        """Python constants-only file produces no test_coverage findings."""
        const_file = _write_file(
            tmp_path, "constants.py",
            "MAX_RETRIES = 3\nTIMEOUT = 30\nAPI_URL = 'https://example.com'\n"
            "SUCCESS = 200\nNOT_FOUND = 404\nSERVER_ERROR = 500\n"
            "EXTRA_1 = 'a'\nEXTRA_2 = 'b'\nEXTRA_3 = 'c'\nEXTRA_4 = 'd'\n",
        )
        zone_map = _make_zone_map([const_file])
        graph = {const_file: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "python")
        assert entries == []
        assert potential == 0

    def test_runtime_file_still_produces_findings(self, tmp_path):
        """File with runtime logic still produces findings (not excluded)."""
        prod = _write_file(
            tmp_path, "utils.ts",
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
