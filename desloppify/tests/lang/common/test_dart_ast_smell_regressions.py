"""Parser-backed regressions for Dart tree-sitter smell node shapes."""

from __future__ import annotations

from desloppify.languages._framework.treesitter import TreeSitterLangSpec
from desloppify.languages._framework.treesitter.analysis.smells import (
    detect_empty_catches,
    detect_unreachable_code,
)
from desloppify.languages._framework.treesitter.specs.compiled import DART_SPEC
from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC


def test_dart_empty_catches_use_the_sibling_handler_block(tmp_path) -> None:
    source = """\
void handlers() {
  try { work(); } catch (error) {}
  try { work(); } on FormatException catch (error) { return; }
  try { work(); } catch (error) { print(error); }
  try { work(); } catch (error) { // comments do not make a handler non-empty
  }
}
"""
    path = tmp_path / "handlers.dart"
    path.write_text(source)

    entries = detect_empty_catches([str(path)], DART_SPEC)

    assert [(entry["line"], entry["type"]) for entry in entries] == [
        (2, "catch_clause"),
        (5, "catch_clause"),
    ]


def test_dart_yields_resume_but_return_still_terminates(tmp_path) -> None:
    source = """\
Iterable<int> syncValues() sync* {
  yield 1;
  yield 2;
}
Stream<int> asyncValues() async* {
  yield 1;
  yield 2;
}
void unreachableAfterReturn() {
  return;
  print('unreachable');
}
"""
    path = tmp_path / "generators.dart"
    path.write_text(source)

    entries = detect_unreachable_code([str(path)], DART_SPEC)

    assert [(entry["line"], entry["after"]) for entry in entries] == [
        (11, "return_statement"),
    ]


def test_dart_throw_statement_is_terminal_but_throw_expressions_are_not(
    tmp_path,
) -> None:
    source = """\
Never unsupported() => throw UnsupportedError('stub');
void unreachableAfterThrow() {
  throw StateError('stop');
  print('unreachable');
}
bool conditionalThrow(bool shouldThrow) =>
    shouldThrow ? throw StateError('branch') : true;
"""
    path = tmp_path / "throws.dart"
    path.write_text(source)

    entries = detect_unreachable_code([str(path)], DART_SPEC)

    assert [(entry["line"], entry["after"]) for entry in entries] == [
        (4, "throw_expression"),
    ]


def test_python_and_javascript_yield_do_not_terminate_generators(tmp_path) -> None:
    python_source = """\
def values():
    yield 1
    yield 2
    return
"""
    python_path = tmp_path / "generator.py"
    python_path.write_text(python_source)
    python_spec = TreeSitterLangSpec(
        grammar="python",
        function_query=(
            "(function_definition name: (identifier) @name body: (block) @body) @func"
        ),
        comment_node_types=frozenset({"comment"}),
    )

    js_source = """\
function* values() {
  yield 1;
  yield 2;
  return;
}
"""
    js_path = tmp_path / "generator.js"
    js_path.write_text(js_source)

    assert detect_unreachable_code([str(python_path)], python_spec) == []
    assert detect_unreachable_code([str(js_path)], JS_SPEC) == []


def test_existing_javascript_return_unreachable_detection_is_preserved(
    tmp_path,
) -> None:
    path = tmp_path / "return.js"
    path.write_text("function stop() {\n  return;\n  console.log('unreachable');\n}\n")

    entries = detect_unreachable_code([str(path)], JS_SPEC)

    assert [(entry["line"], entry["after"]) for entry in entries] == [
        (3, "return_statement"),
    ]


def test_existing_javascript_empty_and_nonempty_catches_are_preserved(tmp_path) -> None:
    path = tmp_path / "catch.js"
    path.write_text(
        "function handlers() {\n"
        "  try { work(); } catch (error) {}\n"
        "  try { work(); } catch (error) { console.log(error); }\n"
        "}\n"
    )

    entries = detect_empty_catches([str(path)], JS_SPEC)

    assert [(entry["line"], entry["type"]) for entry in entries] == [
        (2, "catch_clause"),
    ]
