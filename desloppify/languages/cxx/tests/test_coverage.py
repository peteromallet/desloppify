from __future__ import annotations

from pathlib import Path

import desloppify.languages.cxx.test_coverage as cxx_cov
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine.policy.zones import FileZoneMap, Zone, ZoneRule


def _make_zone_map(file_list: list[str]) -> FileZoneMap:
    rules = [
        ZoneRule(Zone.TEST, ["test_", ".test.", ".spec.", "/tests/", "\\tests\\", "/__tests__/", "\\__tests__\\"]),
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


def test_has_testable_logic_accepts_function_definitions_without_regex_crash():
    assert cxx_cov.has_testable_logic("widget.cpp", "int widget() { return 1; }\n") is True
    assert cxx_cov.has_testable_logic("widget_test.cpp", "int widget() { return 1; }\n") is False


def test_has_testable_logic_excludes_test_prefix_files():
    assert cxx_cov.has_testable_logic("test_widget.cpp", "int widget() { return 1; }\n") is False


def test_map_test_to_source_and_resolve_import_spec(tmp_path):
    source = tmp_path / "src" / "widget.cpp"
    header = tmp_path / "src" / "widget.hpp"
    test_file = tmp_path / "tests" / "widget_test.cpp"

    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("int widget() { return 1; }\n", encoding="utf-8")
    header.write_text("int widget();\n", encoding="utf-8")
    test_file.write_text('#include "../src/widget.hpp"\n', encoding="utf-8")

    production = {str(source.resolve()), str(header.resolve())}

    assert cxx_cov.map_test_to_source(str(test_file), production) == str(source.resolve())
    assert (
        cxx_cov.resolve_import_spec("../src/widget.hpp", str(test_file), production)
        == str(header.resolve())
    )


def test_discover_test_mapping_files_finds_cmakelists_within_test_tree(tmp_path):
    test_file = tmp_path / "tests" / "kernel_parity" / "widget_behavior.cpp"
    cmake_file = tmp_path / "tests" / "CMakeLists.txt"
    nested_cmake = tmp_path / "tests" / "kernel_parity" / "CMakeLists.txt"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("// test\n", encoding="utf-8")
    cmake_file.write_text("add_executable(WidgetBehaviorTest widget_behavior.cpp ../src/widget.cpp)\n", encoding="utf-8")
    nested_cmake.write_text("add_library(ParityHelpers ../src/widget.hpp)\n", encoding="utf-8")

    discovered = cxx_cov.discover_test_mapping_files({str(test_file.resolve())}, set())

    assert discovered == {str(cmake_file.resolve()), str(nested_cmake.resolve())}


def test_detect_test_coverage_uses_cmake_test_sources_for_direct_mapping(tmp_path):
    prod = _write(tmp_path, "src/widget.cpp", "int widget() { return 1; }\n" * 12)
    test_file = _write(
        tmp_path,
        "tests/widget_behavior.cpp",
        '#include <gtest/gtest.h>\n\nTEST(WidgetBehavior, Smoke) {\n    EXPECT_EQ(1, 1);\n}\n',
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
        if entry["file"] == prod and entry["detail"]["kind"] in {"untested_module", "untested_critical"}
    ]
    assert untested == []


def test_unreal_automation_quality_uses_actual_tests_and_assertions():
    import logging
    from types import SimpleNamespace
    from desloppify.engine.detectors.coverage.mapping_analysis import analyze_test_quality

    source = """
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FExample, "Engine.Example", Flags)
bool FExample::RunTest(const FString&) {
    TestTrue(TEXT("true"), true);
    TestEqual<int32>(TEXT("equal"), 2, 2);
    TestFalse(TEXT("false"), false);
    // TestNotNull(TEXT("ignored comment"), Pointer);
    return true;
}
"""
    quality = analyze_test_quality(
        {"example_tests.cpp"}, "cxx",
        load_lang_module=lambda _: cxx_cov,
        read_coverage_file_fn=lambda *_args, **_kwargs: SimpleNamespace(ok=True, content=source),
        logger=logging.getLogger(__name__),
    )["example_tests.cpp"]
    assert quality["test_functions"] == 1
    assert quality["assertions"] == 3
    assert quality["quality"] == "thorough"


def test_unreal_registration_variants_and_google_tests_remain_recognized():
    for macro in ("IMPLEMENT_SIMPLE_AUTOMATION_TEST", "IMPLEMENT_COMPLEX_AUTOMATION_TEST", "IMPLEMENT_NETWORKED_AUTOMATION_TEST", "TEST", "TEST_F", "TEST_P"):
        assert len(cxx_cov.TEST_FUNCTION_RE.findall(f"{macro}(FExample, Name, Flags)")) == 1
    for call in ("TestEqual", "TestNotEqual", "TestTrue", "TestFalse", "TestNull", "TestNotNull", "ASSERT_EQ", "EXPECT_TRUE"):
        assert any(pattern.search(f'{call}("check", Value);') for pattern in cxx_cov.ASSERT_PATTERNS)


def test_unreal_heuristics_do_not_match_similarly_named_helpers():
    source = "TestTrueValue(); FakeTestEqual(); IMPLEMENT_SIMPLE_AUTOMATION_TESTING(Example);"
    assert not cxx_cov.TEST_FUNCTION_RE.search(source)
    assert not any(pattern.search(source) for pattern in cxx_cov.ASSERT_PATTERNS)
