"""Direct behavioral tests for shared Rust detector heuristics."""

from __future__ import annotations

import desloppify.languages.rust.detectors._shared as rust_shared_mod


def test_iter_public_functions_captures_metadata_and_receiver() -> None:
    content = """
/// Helpful docs
#[inline]
pub fn value(&self) -> usize {
    self.value
}
"""

    blocks = rust_shared_mod._iter_public_functions(content)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.name == "value"
    assert block.line == 4
    assert block.receiver == "&self"
    assert "/// Helpful docs" in block.attrs
    assert "#[inline]" in block.attrs
    assert block.body.strip() == "{\n    self.value\n}"


def test_iter_public_functions_handles_strings_containing_braces() -> None:
    """Functions with strings containing braces should have complete bodies."""
    content = """
pub fn example() {
    let s = "}";
    panic!("error");
}
"""

    blocks = rust_shared_mod._iter_public_functions(content)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.name == "example"
    assert "panic!" in block.body, f"Body was truncated: {repr(block.body)}"


def test_iter_public_functions_handles_raw_strings_containing_braces() -> None:
    """Raw strings with braces should not terminate the function body early."""
    content = r'''
pub fn regex() {
    let pattern = r"\{[^}]*\}";
    panic!("still here");
}
'''

    blocks = rust_shared_mod._iter_public_functions(content)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.name == "regex"
    assert "panic!" in block.body, f"Body was truncated: {repr(block.body)}"


def test_iter_drop_methods_extracts_drop_impl_body() -> None:
    content = """
pub struct Demo;

impl Drop for Demo {
    fn drop(&mut self) {
        panic!("boom");
    }
}
"""

    methods = rust_shared_mod._iter_drop_methods(content)

    assert methods == [
        (
            "Demo",
            4,
            '{\n        panic!("boom");\n    }',
        )
    ]


def test_has_inline_rust_doc_examples_accepts_supported_tags_only() -> None:
    rust_docs = """
/// Example
/// ```rust
/// assert_eq!(2, 1 + 1);
/// ```
"""
    text_docs = """
/// Example
/// ```text
/// not rust
/// ```
"""

    assert rust_shared_mod._has_inline_rust_doc_examples(rust_docs) is True
    assert rust_shared_mod._has_inline_rust_doc_examples(text_docs) is False


def test_holds_lock_guard_across_await_requires_guard_to_survive() -> None:
    held_body = """
async fn demo() {
    let guard = state.lock().await;
    work().await;
    drop(guard);
}
"""
    dropped_body = """
async fn demo() {
    let guard = state.lock().await;
    drop(guard);
    work().await;
}
"""

    assert rust_shared_mod._holds_lock_guard_across_await(
        held_body,
        rust_shared_mod._ASYNC_GUARD_ACQUIRE_RE,
    ) is True
    assert rust_shared_mod._holds_lock_guard_across_await(
        dropped_body,
        rust_shared_mod._ASYNC_GUARD_ACQUIRE_RE,
    ) is False


def test_should_skip_unsafe_api_match_respects_documented_local_invariants() -> None:
    vec_rebuild = """
fn rebuild_vec(ptr: *mut u8, len: usize, cap: usize) -> Vec<u8> {
    // safely reconstruct a vec without leaking memory
    unsafe { Vec::from_raw_parts(ptr, len, cap) }
}
"""
    transmute_wrapper = """
#[repr(transparent)]
pub struct Wrapper(u32);

fn cast(value: u32) -> Wrapper {
    unsafe { std::mem::transmute::<u32, Wrapper>(value) }
}
"""

    vec_offset = vec_rebuild.index("Vec::from_raw_parts")
    transmute_offset = transmute_wrapper.index("transmute")

    assert rust_shared_mod._should_skip_unsafe_api_match(
        "from_raw_parts",
        vec_rebuild,
        vec_offset,
    ) is True
    assert rust_shared_mod._should_skip_unsafe_api_match(
        "transmute",
        transmute_wrapper,
        transmute_offset,
    ) is True
