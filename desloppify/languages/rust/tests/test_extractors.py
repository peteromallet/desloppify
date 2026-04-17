"""Tests for Rust function extraction."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.rust.extractors import (
    extract_functions,
    extract_rust_functions,
    normalize_rust_body,
)


def _write(path: Path, rel_path: str, content: str) -> str:
    target = path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return str(target)


def test_extract_rust_functions_fallback_handles_methods_and_free_functions(tmp_path):
    filepath = _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct Service;

impl Service {
    pub fn run(&self, name: &str) -> String {
        println!("debug {}", name);
        format!("hi {}", name)
    }
}

pub fn helper() -> i32 {
    1 + 1
}
""",
    )
    functions = extract_rust_functions(filepath)
    names = {function.name for function in functions}
    assert names == {"run", "helper"}


def test_extract_functions_falls_back_without_tree_sitter(monkeypatch, tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}
""",
    )
    monkeypatch.setattr("desloppify.languages.rust.extractors.is_available", lambda: False)
    functions = extract_functions(tmp_path)
    assert [function.name for function in functions] == ["add"]


def test_normalize_rust_body_strips_comments_and_logging():
    body = """
pub fn run() {
    // comment
    println!("debug");
    let value = 1;
    value + 1
}
"""
    normalized = normalize_rust_body(body)
    assert "// comment" not in normalized
    assert "println!" not in normalized
    assert "let value = 1;" in normalized


def test_extract_rust_functions_ignores_unbalanced_braces_inside_comments(tmp_path):
    filepath = _write(
        tmp_path,
        "src/lib.rs",
        """
pub fn validate_input() {
    /* Validate against old schema:
       { "type": "required" }
       See ticket #1234 for context }
     */
    if input_is_valid() {
        return;
    }
    panic!("Invalid");
}
""",
    )

    functions = extract_rust_functions(filepath)

    assert len(functions) == 1
    func = functions[0]
    assert func.name == "validate_input"
    assert func.end_line == 11
    assert "input_is_valid()" in func.body
