from __future__ import annotations

from pathlib import Path

import desloppify.languages.cxx.test_coverage as cxx_cov
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine.policy.zones import FileZoneMap, Zone, ZoneRule


def _make_zone_map(file_list: list[str]) -> FileZoneMap:
    rules = [
        ZoneRule(
            Zone.TEST,
            [
                "test_",
                ".test.",
                ".spec.",
                "/tests/",
                "\\tests\\",
                "/__tests__/",
                "\\__tests__\\",
            ],
        ),
    ]
    return FileZoneMap(file_list, rules)


def _write(tmp_path: Path, rel_path: str, content: str) -> str:
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


def test_strip_test_markers_for_cxx():
    assert cxx_cov.strip_test_markers("widget_test.cpp") == "widget.cpp"
    assert cxx_cov.strip_test_markers("test_widget.cpp") == "widget.cpp"
    assert cxx_cov.strip_test_markers("widget.cpp") is None


def test_parse_test_import_specs_extracts_includes():
    content = '#include "widget.hpp"\n#include <gtest/gtest.h>\n'
    assert cxx_cov.parse_test_import_specs(content) == ["widget.hpp", "gtest/gtest.h"]


def test_parse_test_import_specs_extracts_cmake_sources():
    content = """
add_executable(WidgetBehaviorTest
    widget_behavior.cpp
    ../src/widget.cpp
    ../src/widget.hpp
)
"""
    assert cxx_cov.parse_test_import_specs(content) == [
        "widget_behavior.cpp",
        "../src/widget.cpp",
        "../src/widget.hpp",
    ]


def test_parse_test_import_specs_extracts_qt_cmake_sources():
    content = """
qt_add_executable(WidgetBehaviorTest
    widget_behavior.cpp
    ../src/widget.cpp
)
qt6_add_library(WidgetFixture STATIC ../src/widget_fixture.cpp)
"""
    assert cxx_cov.parse_test_import_specs(content) == [
        "widget_behavior.cpp",
        "../src/widget.cpp",
        "../src/widget_fixture.cpp",
    ]


def test_catch2_test_and_assertion_patterns():
    content = """
TEST_CASE("widget value", "[widget]") {
    REQUIRE(widget() == 1);
    CHECK_FALSE(widget() == 2);
}
"""

    assert len(cxx_cov.TEST_FUNCTION_RE.findall(content)) == 1
    assert (
        sum(
            1
            for line in content.splitlines()
            if any(pattern.search(line) for pattern in cxx_cov.ASSERT_PATTERNS)
        )
        == 2
    )


def test_has_testable_logic_accepts_function_definitions_without_regex_crash():
    assert (
        cxx_cov.has_testable_logic("widget.cpp", "int widget() { return 1; }\n") is True
    )
    assert (
        cxx_cov.has_testable_logic("widget_test.cpp", "int widget() { return 1; }\n")
        is False
    )


def test_has_testable_logic_rejects_long_non_function_token_sequence():
    content = ("TypeName " * 10_000) + "value;\n"

    assert cxx_cov.has_testable_logic("widget.cpp", content) is False


def test_has_testable_logic_excludes_test_prefix_files():
    assert (
        cxx_cov.has_testable_logic("test_widget.cpp", "int widget() { return 1; }\n")
        is False
    )


def test_map_test_to_source_and_resolve_import_spec(tmp_path):
    source = tmp_path / "src" / "widget.cpp"
    header = tmp_path / "src" / "widget.hpp"
    test_file = tmp_path / "tests" / "widget_test.cpp"

    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("int widget() { return 1; }\n", encoding="utf-8")
    header.write_text("int widget();\n", encoding="utf-8")
    test_file.write_text(
        '#include "../src/widget.hpp"\nint use_widget() { return widget(); }\n',
        encoding="utf-8",
    )

    production = {str(source.resolve()), str(header.resolve())}

    assert cxx_cov.map_test_to_source(str(test_file), production) == str(
        source.resolve()
    )
    assert cxx_cov.resolve_import_spec(
        "../src/widget.hpp", str(test_file), production
    ) == str(source.resolve())


def test_match_candidate_uses_case_normalized_lexical_paths(tmp_path, monkeypatch):
    expected = _write(tmp_path, "include/widget.hpp", "int widget();\n")
    monkeypatch.setattr(cxx_cov.os.path, "normcase", lambda value: value.lower())

    resolved = cxx_cov._match_candidate(Path(expected.upper()), {expected})

    assert resolved == expected


def test_resolve_import_spec_does_not_guess_between_same_stem_sources(tmp_path):
    header = _write(tmp_path, "include/widget.hpp", "int widget();\n")
    source_a = _write(tmp_path, "src/a/widget.cpp", "int widget() { return 1; }\n")
    source_b = _write(tmp_path, "src/b/widget.cpp", "int widget() { return 2; }\n")
    test_file = _write(
        tmp_path,
        "tests/widget_behavior.cpp",
        "#include <widget.hpp>\nint value = widget();\n",
    )

    resolved = cxx_cov.resolve_import_spec(
        "widget.hpp",
        test_file,
        {header, source_a, source_b},
    )

    assert resolved == header


def test_resolve_import_spec_keeps_unused_header_as_header(tmp_path):
    header = _write(tmp_path, "include/widget.hpp", "int widget();\n")
    source = _write(tmp_path, "src/widget.cpp", "int widget() { return 1; }\n")
    test_file = _write(tmp_path, "tests/other_behavior.cpp", "#include <widget.hpp>\n")

    resolved = cxx_cov.resolve_import_spec(
        "widget.hpp",
        test_file,
        {header, source},
    )

    assert resolved == header


def test_discover_test_mapping_files_finds_cmakelists_within_test_tree(tmp_path):
    test_file = tmp_path / "tests" / "kernel_parity" / "widget_behavior.cpp"
    cmake_file = tmp_path / "tests" / "CMakeLists.txt"
    nested_cmake = tmp_path / "tests" / "kernel_parity" / "CMakeLists.txt"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("// test\n", encoding="utf-8")
    cmake_file.write_text(
        "add_executable(WidgetBehaviorTest widget_behavior.cpp ../src/widget.cpp)\n",
        encoding="utf-8",
    )
    nested_cmake.write_text(
        "add_library(ParityHelpers ../src/widget.hpp)\n", encoding="utf-8"
    )

    discovered = cxx_cov.discover_test_mapping_files({str(test_file.resolve())}, set())

    assert discovered == {str(cmake_file.resolve()), str(nested_cmake.resolve())}


def test_detect_test_coverage_uses_cmake_test_sources_for_direct_mapping(tmp_path):
    prod = _write(tmp_path, "src/widget.cpp", "int widget() { return 1; }\n" * 12)
    test_file = _write(
        tmp_path,
        "tests/widget_behavior.cpp",
        "#include <gtest/gtest.h>\n\nTEST(WidgetBehavior, Smoke) {\n    EXPECT_EQ(1, 1);\n}\n",
    )
    _write(
        tmp_path,
        "tests/CMakeLists.txt",
        "add_executable(WidgetBehaviorTest\n"
        "    widget_behavior.cpp\n"
        "    ../src/widget.cpp\n"
        ")\n",
    )

    zone_map = _make_zone_map([prod, test_file])
    graph = {
        prod: {"imports": set(), "importer_count": 0},
        test_file: {"imports": set(), "importer_count": 0},
    }

    entries, potential = detect_test_coverage(graph, zone_map, "cxx")

    assert potential > 0
    untested = [
        entry
        for entry in entries
        if entry["file"] == prod
        and entry["detail"]["kind"] in {"untested_module", "untested_critical"}
    ]
    assert untested == []


def test_detect_test_coverage_maps_public_header_to_implementation_and_internal_header(
    tmp_path,
):
    public_header = _write(tmp_path, "include/widget.hpp", "int widget();\n")
    internal_header = _write(
        tmp_path, "src/widget_internal.hpp", "int widget_value();\n"
    )
    source = _write(
        tmp_path,
        "src/widget.cpp",
        '#include "../include/widget.hpp"\n#include "widget_internal.hpp"\n'
        "int widget() { return widget_value(); }\n" * 12,
    )
    test_file = _write(
        tmp_path,
        "tests/widget_behavior.cpp",
        '#include <widget.hpp>\n\nTEST_CASE("widget value") {\n    REQUIRE(widget() == 1);\n}\n',
    )

    files = [public_header, internal_header, source, test_file]
    zone_map = _make_zone_map(files)
    graph = {
        public_header: {"imports": set(), "importer_count": 2},
        internal_header: {"imports": set(), "importer_count": 1},
        source: {"imports": {public_header, internal_header}, "importer_count": 0},
        test_file: {"imports": {public_header}, "importer_count": 0},
    }

    entries, potential = detect_test_coverage(graph, zone_map, "cxx")

    assert potential > 0
    uncovered = {
        entry["file"]
        for entry in entries
        if entry["detail"]["kind"] in {"untested_module", "untested_critical"}
    }
    assert source not in uncovered
    assert public_header not in uncovered
    assert internal_header not in uncovered
