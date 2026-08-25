"""Direct coverage tests for coverage mapping analysis helpers."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import desloppify.engine.detectors.coverage.mapping_analysis as analysis_mod


class _ReadResult:
    def __init__(self, ok: bool, content: str = "") -> None:
        self.ok = ok
        self.content = content


def test_transitive_coverage_walks_only_production_imports() -> None:
    directly_tested = {"src/a.ts"}
    graph = {
        "src/a.ts": {"imports": {"src/b.ts", "tests/helper.ts"}},
        "src/b.ts": {"imports": {"src/c.ts"}},
        "src/c.ts": {"imports": set()},
    }
    production = {"src/a.ts", "src/b.ts", "src/c.ts"}

    transitive = analysis_mod.transitive_coverage(directly_tested, graph, production)

    assert transitive == {"src/b.ts", "src/c.ts"}


def test_analyze_test_quality_classifies_multiple_quality_buckets() -> None:
    contents = {
        "tests/thorough.test.ts": (
            "test('x', () => {\n"
            "  expect(1).toBe(1);\n"
            "  expect(2).toBe(2);\n"
            "  expect(3).toBe(3);\n"
            "})"
        ),
        "tests/mocked.test.ts": (
            "test('x', () => {\n"
            "  jest.mock('a');\n"
            "  vi.mock('b');\n"
            "  expect(true).toBe(true);\n"
            "})"
        ),
        "tests/empty.test.ts": "const x = 1;",
    }

    def load_lang_module(_lang):
        return SimpleNamespace(
            ASSERT_PATTERNS=[re.compile(r"\bexpect\(")],
            MOCK_PATTERNS=[re.compile(r"\b(?:jest|vi)\.mock\(")],
            SNAPSHOT_PATTERNS=[re.compile(r"toMatchSnapshot\(")],
            TEST_FUNCTION_RE=re.compile(r"\b(?:test|it)\s*\("),
            strip_comments=lambda text: text,
            is_placeholder_test=lambda _content, *, assertions, test_functions: (
                assertions == 0 and test_functions > 0
            ),
        )

    def read_file(path, context):
        assert context == "coverage_quality_analysis"
        return _ReadResult(True, contents[path])

    quality = analysis_mod.analyze_test_quality(
        set(contents),
        "typescript",
        load_lang_module=load_lang_module,
        read_coverage_file_fn=read_file,
        logger=logging.getLogger(__name__),
    )

    assert quality["tests/thorough.test.ts"]["quality"] == "thorough"
    assert quality["tests/mocked.test.ts"]["quality"] == "over_mocked"
    assert quality["tests/empty.test.ts"]["quality"] == "no_tests"


def test_analyze_test_quality_tolerates_placeholder_typeerror() -> None:
    def load_lang_module(_lang):
        return SimpleNamespace(
            ASSERT_PATTERNS=[re.compile(r"expect\(")],
            MOCK_PATTERNS=[],
            SNAPSHOT_PATTERNS=[],
            TEST_FUNCTION_RE=re.compile(r"\btest\s*\("),
            strip_comments=lambda text: text,
            is_placeholder_test=lambda content: bool(content),
        )

    quality = analysis_mod.analyze_test_quality(
        {"tests/a.test.ts"},
        "typescript",
        load_lang_module=load_lang_module,
        read_coverage_file_fn=lambda _path, context: _ReadResult(True, "test('x', () => {})"),
        logger=logging.getLogger(__name__),
    )

    assert quality["tests/a.test.ts"]["quality"] == "assertion_free"
    assert quality["tests/a.test.ts"]["placeholder"] is False


def test_get_test_files_for_prod_uses_graph_parsed_imports_and_fallbacks() -> None:
    prod = "/repo/src/a.ts"
    test_files = {
        "/repo/tests/a.test.ts",
        "/repo/tests/b.test.ts",
        "/repo/tests/c.test.ts",
    }
    graph = {
        "/repo/tests/a.test.ts": {"imports": {prod}},
        "/repo/tests/b.test.ts": {"imports": set()},
        "/repo/tests/c.test.ts": {"imports": set()},
    }
    parsed_imports_by_test = {
        "/repo/tests/b.test.ts": {prod},
    }

    parse_calls: list[str] = []

    def parse_test_imports(test_path, production_files, prod_by_module, lang_name):
        parse_calls.append(test_path)
        assert production_files == {prod}
        assert lang_name == "typescript"
        assert "a" in prod_by_module
        return set()

    def map_test_to_source(test_path, production_files, lang_name):
        assert production_files == {prod}
        assert lang_name == "typescript"
        if test_path.endswith("c.test.ts"):
            return prod
        return None

    matched = analysis_mod.get_test_files_for_prod(
        prod,
        test_files,
        graph,
        "typescript",
        parsed_imports_by_test,
        parse_test_imports_fn=parse_test_imports,
        map_test_to_source_fn=map_test_to_source,
        project_root="/repo",
    )

    assert set(matched) == test_files
    assert "/repo/tests/c.test.ts" in parse_calls


def test_build_test_import_index_passes_module_lookup_map() -> None:
    captures: list[dict[str, str]] = []

    def parse_test_imports(test_path, production_files, prod_by_module, lang_name):
        assert test_path in {"/repo/tests/a.test.py", "/repo/tests/b.test.py"}
        assert production_files == {"/repo/pkg/__init__.py", "/repo/pkg/util.py"}
        assert lang_name == "python"
        captures.append(dict(prod_by_module))
        return {"/repo/pkg/util.py"}

    index = analysis_mod.build_test_import_index(
        {"/repo/tests/a.test.py", "/repo/tests/b.test.py"},
        {"/repo/pkg/__init__.py", "/repo/pkg/util.py"},
        "python",
        parse_test_imports_fn=parse_test_imports,
        project_root="/repo",
    )

    assert set(index.keys()) == {"/repo/tests/a.test.py", "/repo/tests/b.test.py"}
    assert all(value == {"/repo/pkg/util.py"} for value in index.values())
    assert captures
    assert "pkg" in captures[0]
    assert "util" in captures[0]


def test_build_test_import_index_drops_ambiguous_basename_aliases() -> None:
    captures: list[dict[str, str]] = []

    def parse_test_imports(_test_path, _production_files, prod_by_module, _lang_name):
        captures.append(dict(prod_by_module))
        return set()

    analysis_mod.build_test_import_index(
        {"/repo/tests/a.test.py"},
        {"/repo/pkg/util.py", "/repo/services/util.py"},
        "python",
        parse_test_imports_fn=parse_test_imports,
        project_root="/repo",
    )

    assert captures
    assert "pkg.util" in captures[0]
    assert "services.util" in captures[0]
    assert "util" not in captures[0]


def test_build_production_test_index_resolves_each_test_once() -> None:
    tests = {"tests/by_graph.rs", "tests/by_import.rs", "tests/by_name.rs"}
    production = {"src/graph.rs", "src/imported.rs", "src/named.rs"}
    graph = {"tests/by_graph.rs": {"imports": {"src/graph.rs"}}}
    parsed = {"tests/by_import.rs": {"src/imported.rs"}}
    calls: list[str] = []

    def map_test(test_path, candidates, _lang_name):
        calls.append(test_path)
        assert candidates == production
        return "src/named.rs" if test_path == "tests/by_name.rs" else None

    index = analysis_mod.build_production_test_index(
        tests,
        production,
        graph,
        "rust",
        parsed,
        map_test_to_source_fn=map_test,
    )

    assert index == {
        "src/graph.rs": ["tests/by_graph.rs"],
        "src/imported.rs": ["tests/by_import.rs"],
        "src/named.rs": ["tests/by_name.rs"],
    }
    assert sorted(calls) == sorted(tests)
