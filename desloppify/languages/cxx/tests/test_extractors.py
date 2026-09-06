from __future__ import annotations

import time
from pathlib import Path

import desloppify.languages.cxx.extractors as cxx_extractors
from desloppify.languages.cxx.extractors import (
    extract_all_cxx_functions,
    find_cxx_files,
)


def test_extract_cxx_functions_and_classes(tmp_path):
    source = tmp_path / "widget.cpp"
    source.write_text("class Widget { void run(); }; void helper() {}\n")

    functions = extract_all_cxx_functions([str(source)])

    assert any(f.name == "helper" for f in functions)


def test_extract_cxx_function_ignores_comment_braces(tmp_path):
    source = tmp_path / "widget.cpp"
    source.write_text(
        """
int helper() {
    /* unbalanced } }} braces */
    return 1;
}
"""
    )

    functions = extract_all_cxx_functions([str(source)])

    assert [fn.name for fn in functions] == ["helper"]
    assert "return 1;" in functions[0].body


def test_extract_all_cxx_functions_treats_string_root_as_path(tmp_path):
    source = tmp_path / "widget.cpp"
    source.write_text("int widget() { return 1; }\n")

    functions = extract_all_cxx_functions(str(tmp_path))

    assert [fn.name for fn in functions] == ["widget"]


def test_find_cxx_files_includes_common_header_only_extensions(tmp_path):
    files = [
        tmp_path / "widget.hh",
        tmp_path / "widget.hxx",
        tmp_path / "widget.ipp",
        tmp_path / "widget.inl",
        tmp_path / "widget.tpp",
        tmp_path / "widget.txx",
        tmp_path / "widget.tcc",
    ]
    for path in files:
        path.write_text("// test\n")

    discovered = {
        str(Path(filepath).resolve()) for filepath in find_cxx_files(tmp_path)
    }

    assert discovered == {str(path.resolve()) for path in files}


def test_cxx_extractors_use_local_brace_helper():
    assert (
        cxx_extractors.find_matching_brace.__module__
        == "desloppify.languages.cxx._parse_helpers"
    )


def test_function_extraction_bounds_qualified_name_backtracking(tmp_path):
    source = tmp_path / "adversarial.cpp"
    source.write_text("::".join(["Type"] * 21) + " value = source;\n")

    started = time.perf_counter()
    functions = extract_all_cxx_functions([str(source)])
    elapsed = time.perf_counter() - started

    assert functions == []
    assert elapsed < 0.25
