"""Tests for Dart regex-based function extraction."""

from __future__ import annotations

from desloppify.languages.dart.extractors import extract_dart_functions


def test_extract_dart_functions_ignores_unbalanced_braces_inside_comments(tmp_path):
    source = tmp_path / "lib" / "app.dart"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        """void validateInput() {
  /* Validate against old schema:
     { "type": "required" }
     See ticket #1234 for context }
   */
  if (input.isValid()) {
    return;
  }
  throw StateError("Invalid");
}
""",
        encoding="utf-8",
    )

    functions = extract_dart_functions(str(source))

    assert len(functions) == 1
    func = functions[0]
    assert func.name == "validateInput"
    assert func.end_line == 10
    assert "input.isValid()" in func.body
