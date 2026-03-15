"""Tests for Rust support helpers."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.rust.support import (
    build_production_file_index,
    find_workspace_root,
    iter_use_specs,
    match_production_candidate,
    read_text_or_none,
    strip_rust_comments,
)


def _write(tmp_path: Path, relpath: str, content: str) -> Path:
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_strip_rust_comments_removes_comments_but_keeps_string_literals():
    content = """
/// crate docs
fn render() {
    let url = "https://example.com";
    let literal = "// not a comment";
    // real comment
    println!("{}", literal);
}
"""

    stripped = strip_rust_comments(content)

    assert "crate docs" not in stripped
    assert "real comment" not in stripped
    assert "https://example.com" in stripped
    assert '"// not a comment"' in stripped


def test_strip_rust_comments_preserves_line_count_when_requested():
    content = "fn render() {\n    /// docs\n    let value = 1; // trailing\n}\n"

    stripped = strip_rust_comments(content, preserve_lines=True)

    assert stripped.count("\n") == content.count("\n")
    assert "let value = 1;" in stripped


def test_strip_rust_comments_removes_doc_examples_with_markdown_backticks():
    content = (
        "impl<'a> Demo<'a> {\n"
        "    pub fn get(&'a self) -> &'a str {\n"
        '        "value"\n'
        "    }\n"
        "}\n"
        "/// Returns an `Entry`.\n"
        "///\n"
        "/// ```\n"
        "/// match map.entry(\"key\") {\n"
        "///     Entry::Vacant(_) => unimplemented!(),\n"
        "/// }\n"
        "/// ```\n"
        "pub fn run() {}\n"
    )

    stripped = strip_rust_comments(content, preserve_lines=True)

    assert "unimplemented!" not in stripped
    assert "Returns an `Entry`." not in stripped
    assert stripped.count("\n") == content.count("\n")


def test_read_text_or_none_returns_none_for_missing_file(tmp_path):
    assert read_text_or_none(tmp_path / "missing.rs") is None


def test_find_workspace_root_skips_invalid_nested_manifest(tmp_path):
    _write(tmp_path, "Cargo.toml", "[workspace]\nmembers = ['app']\n")
    _write(tmp_path, "app/Cargo.toml", "[package]\nname = 'broken'\ninvalid = [\n")
    source = _write(tmp_path, "app/src/lib.rs", "pub fn run() {}\n")

    assert find_workspace_root(source) == tmp_path.resolve()


def test_iter_use_specs_ignores_use_text_inside_strings():
    content = r'''
fn registry() {
    let description = r#"
    use this wording in docs only; still not an import.
    "#;
}
use crate::real::Thing;
'''

    specs = iter_use_specs(content)

    assert specs == ["crate::real::Thing"]


def test_match_production_candidate_uses_relative_index_key(tmp_path):
    prod = _write(tmp_path, "src/lib.rs", "pub fn run() {}\n")
    production_files = {"src/lib.rs"}

    from desloppify.base.runtime_state import RuntimeContext, runtime_scope

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        index = build_production_file_index(production_files)
        assert match_production_candidate(prod, production_files) == "src/lib.rs"
        assert index.by_relative["src/lib.rs"] == "src/lib.rs"
