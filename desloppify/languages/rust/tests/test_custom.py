"""Tests for Rust-specific policy detectors and fixers."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.languages import get_lang
from desloppify.languages.rust._fixers import (
    fix_crate_imports,
    fix_missing_features,
    fix_readme_doctests,
)
from desloppify.languages.rust.detectors.api import (
    detect_error_boundaries,
    detect_future_proofing,
    detect_import_hygiene,
    detect_public_api_conventions,
    detect_thread_safety_contracts,
)
from desloppify.languages.rust.detectors.cargo_policy import (
    detect_doctest_hygiene,
    detect_feature_hygiene,
)
from desloppify.languages.rust.detectors.safety import (
    detect_async_locking,
    detect_drop_safety,
    detect_unsafe_api_usage,
)
from desloppify.languages.rust.phases import phase_signature


def _write(path: Path, rel_path: str, content: str) -> Path:
    target = path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_detect_import_hygiene_and_fix_rewrites_same_crate_paths(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    source = _write(
        tmp_path,
        "src/lib.rs",
        "use demo_app::support::Thing;\npub fn run() {}\n",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_import_hygiene(tmp_path)
        assert [entry["name"] for entry in entries] == ["crate_import::1"]
        result = fix_crate_imports(entries, dry_run=False)

    assert result.entries[0]["file"] == "src/lib.rs"
    assert source.read_text() == "use crate::support::Thing;\npub fn run() {}\n"


def test_detect_import_hygiene_uses_custom_lib_name(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        """
[package]
name = "demo-app"
version = "0.1.0"
edition = "2021"

[lib]
name = "demo_core"
""",
    )
    source = _write(
        tmp_path,
        "src/lib.rs",
        "use demo_core::support::Thing;\npub fn run() {}\n",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_import_hygiene(tmp_path)
        assert [entry["name"] for entry in entries] == ["crate_import::1"]
        result = fix_crate_imports(entries, dry_run=False)

    assert result.entries[0]["file"] == "src/lib.rs"
    assert source.read_text() == "use crate::support::Thing;\npub fn run() {}\n"


def test_detect_import_hygiene_ignores_doctest_imports(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        '/// ```rust\n/// use demo_app::support::Thing;\n/// ```\npub fn run() {}\n',
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_import_hygiene(tmp_path)

    assert entries == []


def test_detect_import_hygiene_ignores_crate_segment_inside_crate_paths(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "bytes"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        "mod bytes;\npub use crate::bytes::Bytes;\n",
    )
    _write(tmp_path, "src/bytes.rs", "pub struct Bytes;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_import_hygiene(tmp_path)

    assert entries == []


def test_detect_feature_hygiene_and_fix_adds_missing_features(tmp_path):
    manifest = _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        '#[cfg(feature = "experimental")]\npub fn experiment() {}\n',
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_feature_hygiene(tmp_path)
        assert [entry["name"] for entry in entries] == ["experimental"]
        result = fix_missing_features(entries, dry_run=False)

    assert result.entries[0]["file"] == "Cargo.toml"
    assert "[features]\nexperimental = []\n" in manifest.read_text()


def test_detect_feature_hygiene_ignores_optional_dependency_features(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        """
[package]
name = "demo-app"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", optional = true }
""",
    )
    _write(
        tmp_path,
        "src/lib.rs",
        '#[cfg(feature = "serde")]\npub fn encode() {}\n',
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_feature_hygiene(tmp_path)

    assert entries == []


def test_detect_doctest_hygiene_and_fix_adds_readme_harness(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    lib_rs = _write(tmp_path, "src/lib.rs", "//! Demo crate.\npub fn run() {}\n")
    _write(tmp_path, "README.md", "```rust\nuse demo_app::run;\n```\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_doctest_hygiene(tmp_path)
        assert [entry["name"] for entry in entries] == ["readme_doctests"]
        result = fix_readme_doctests(entries, dry_run=False)

    assert result.entries[0]["file"] == "src/lib.rs"
    assert "include_str!(\"../README.md\")" in lib_rs.read_text()


def test_detect_doctest_hygiene_skips_when_lib_already_has_examples(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        '//! ```rust\n//! use demo_app::run;\n//! ```\npub fn run() {}\n',
    )
    _write(tmp_path, "README.md", "```rust\nuse demo_app::run;\n```\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_doctest_hygiene(tmp_path)

    assert entries == []


def test_detect_doctest_hygiene_treats_plain_doc_fences_as_rust_examples(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        '//! ```\n//! let answer = 42;\n//! assert_eq!(answer, 42);\n//! ```\npub fn run() {}\n',
    )
    _write(tmp_path, "README.md", "```rust\nuse demo_app::run;\n```\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_doctest_hygiene(tmp_path)

    assert entries == []


def test_detect_public_api_convention_flags_getter_and_into_borrow(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct User;

impl User {
    pub fn get_name(&self) -> &str { "name" }
    pub fn into_name(&self) -> String { "name".to_string() }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_public_api_conventions(tmp_path)

    assert {entry["name"] for entry in entries} == {"getter::get_name", "into_ref::into_name"}


def test_detect_public_api_convention_ignores_lookup_methods_and_pyo3_getters(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct User;

impl User {
    #[getter]
    pub fn get_name(&self) -> &str { "name" }

    pub fn get_template(&self, name: &str) -> Option<&str> { Some(name) }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_public_api_conventions(tmp_path)

    assert entries == []


def test_detect_public_api_convention_ignores_wrapper_get_ref_and_get_mut(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct Wrapper<T> {
    inner: T,
}

impl<T> Wrapper<T> {
    pub fn get_ref(&self) -> &T { &self.inner }
    pub fn get_mut(&mut self) -> &mut T { &mut self.inner }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_public_api_conventions(tmp_path)

    assert entries == []


def test_detect_error_boundaries_flags_anyhow_and_panic_paths(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub fn parse() -> anyhow::Result<()> {
    panic!("nope");
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_error_boundaries(tmp_path)

    assert {entry["name"] for entry in entries} == {"error_type::parse", "panic_path::parse"}


def test_detect_error_boundaries_ignores_infallible_write_unwrap(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::fmt::Write;

pub fn format_name() -> String {
    let mut value = String::new();
    write!(&mut value, "demo").unwrap();
    value
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_error_boundaries(tmp_path)

    assert entries == []


def test_detect_future_proofing_flags_public_struct_shape(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct Config {
    pub host: String,
    pub port: u16,
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert [entry["name"] for entry in entries] == ["struct::Config"]


def test_detect_future_proofing_skips_private_package(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "private-app"\nversion = "0.1.0"\npublish = false\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct Config {
    pub host: String,
    pub port: u16,
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert entries == []


def test_detect_future_proofing_honors_private_workspace_package(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        """
[workspace]
members = ["crates/private-api"]

[workspace.package]
publish = false
""",
    )
    _write(
        tmp_path,
        "crates/private-api/Cargo.toml",
        """
[package]
name = "private-api"
version = "0.1.0"
publish.workspace = true
""",
    )
    _write(
        tmp_path,
        "crates/private-api/src/lib.rs",
        """
pub struct Config {
    pub host: String,
    pub port: u16,
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert entries == []


def test_detect_future_proofing_skips_ffi_and_unstable_docs(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
/// This is unstable machinery.
#[repr(C)]
pub struct ApiConfig {
    pub host: String,
    pub port: u16,
    pub tls: bool,
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert entries == []


def test_detect_future_proofing_ignores_public_error_types(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct ParseError {
    pub requested: usize,
    pub available: usize,
}

impl core::fmt::Display for ParseError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> Result<(), core::fmt::Error> {
        write!(f, "{} {}", self.requested, self.available)
    }
}

impl std::error::Error for ParseError {}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert entries == []


def test_detect_future_proofing_ignores_small_scalar_records(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct Position {
    pub line: usize,
    pub column: usize,
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert entries == []


def test_detect_future_proofing_ignores_documented_public_enums(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
/// Public API enum with intentionally documented variants.
pub enum Value {
    Null,
    Bool(bool),
    Number(u64),
    String(String),
    Array(Vec<Value>),
    Object(String),
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_future_proofing(tmp_path)

    assert entries == []


def test_detect_thread_safety_contracts_flags_manual_send_without_assertions(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::cell::RefCell;

pub struct SharedState {
    inner: RefCell<String>,
}

unsafe impl Send for SharedState {}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_thread_safety_contracts(tmp_path)

    assert [entry["name"] for entry in entries] == ["thread_contract::SharedState"]


def test_detect_thread_safety_contracts_ignores_repr_c_ffi_structs(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
#[repr(C)]
pub struct SharedState {
    pub raw: *mut u8,
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_thread_safety_contracts(tmp_path)

    assert entries == []


def test_detect_async_locking_flags_std_guard_and_async_guard_patterns(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::sync::Mutex;
use tokio::sync::RwLock;

async fn hold_std_guard(state: &Mutex<String>) {
    let guard = state.lock().unwrap();
    consume().await;
    drop(guard);
}

async fn hold_async_guard(state: &RwLock<String>) {
    let guard = state.read().await;
    consume().await;
    drop(guard);
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_async_locking(tmp_path)

    assert {entry["name"] for entry in entries} == {
        "std_guard::hold_std_guard",
        "async_guard::hold_async_guard",
    }


def test_detect_async_locking_ignores_explicit_drop_before_await(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use tokio::sync::Mutex;

async fn release_before_wait(state: &Mutex<String>) {
    let guard = state.lock().await;
    drop(guard);
    consume().await;
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_async_locking(tmp_path)

    assert entries == []


def test_detect_async_locking_ignores_std_guard_drop_before_await(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::sync::RwLock;

async fn release_before_wait(state: &RwLock<String>) {
    let guard = state.read().unwrap();
    drop(guard);
    consume().await;
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_async_locking(tmp_path)

    assert entries == []


def test_detect_async_locking_ignores_std_guard_block_scope_before_await(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::sync::RwLock;

async fn block_scope_before_wait(state: &RwLock<String>) {
    {
        let guard = state.read().unwrap();
        consume_guard(&guard);
    }
    consume().await;
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_async_locking(tmp_path)

    assert entries == []


def test_detect_async_locking_flags_blocking_std_lock_without_extra_await(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::sync::Mutex;

async fn lock_now(state: &Mutex<String>) -> usize {
    let guard = state.lock().unwrap();
    guard.len()
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_async_locking(tmp_path)

    assert [entry["name"] for entry in entries] == ["blocking_lock::lock_now"]


def test_detect_drop_safety_flags_panic_and_unwrap_in_drop(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
struct Guard;

impl Drop for Guard {
    fn drop(&mut self) {
        let value = Some("done");
        value.unwrap();
        panic!("boom");
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_drop_safety(tmp_path)

    assert {entry["name"] for entry in entries} == {
        "drop_panic::Guard",
        "drop_unwrap::Guard",
    }


def test_detect_drop_safety_ignores_non_drop_cleanup_methods(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
struct Guard;

impl Guard {
    fn cleanup(&mut self) {
        panic!("boom");
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_drop_safety(tmp_path)

    assert entries == []


def test_detect_drop_safety_ignores_local_abort_sentinels_inside_functions(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
fn abort() -> ! {
    struct Abort;

    impl Drop for Abort {
        fn drop(&mut self) {
            panic!();
        }
    }

    let _guard = Abort;
    panic!("abort");
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_drop_safety(tmp_path)

    assert entries == []


def test_detect_drop_safety_ignores_infallible_layout_unwrap(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use alloc::alloc::{dealloc, Layout};

struct Guard {
    ptr: *mut u8,
    cap: usize,
}

impl Drop for Guard {
    fn drop(&mut self) {
        unsafe { dealloc(self.ptr, Layout::from_size_align(self.cap, 1).unwrap()) }
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_drop_safety(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_flags_unchecked_calls(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::mem;

fn decode(bytes: &[u8], index: usize, ptr: *const u8, len: usize) {
    let _ = unsafe { mem::transmute::<*const u8, usize>(ptr) };
    let _ = unsafe { bytes.get_unchecked(index) };
    let _ = unsafe { std::slice::from_raw_parts(ptr, len) };
    let _ = unsafe { std::str::from_utf8_unchecked(bytes) };
    let _ = Some(index).unwrap_unchecked();
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert {entry["name"].split("::", 1)[0] for entry in entries} >= {
        "transmute",
        "get_unchecked",
        "from_raw_parts",
        "from_utf8_unchecked",
        "unwrap_unchecked",
    }


def test_detect_unsafe_api_usage_ignores_comment_mentions(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
// transmute(ptr)
// std::slice::from_raw_parts(ptr, len)
fn helper() {}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_ignores_safe_zeroed_method_names(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct Buffer;

impl Buffer {
    pub fn zeroed(len: usize) -> Buffer {
        let _ = len;
        Buffer
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_preserves_line_numbers_through_doc_comments(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
/// Safety docs.
fn decode(ptr: *const u8, len: usize) {
    // Keep the reported line stable.
    let _ = unsafe { std::slice::from_raw_parts(ptr, len) };
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert [entry["line"] for entry in entries] == [5]


def test_detect_unsafe_api_usage_ignores_local_safety_rationale(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::{hint, str};

fn render(bytes: &[u8]) -> &str {
    // Safety: bytes are known valid UTF-8 from the parser.
    unsafe { str::from_utf8_unchecked(bytes) }
}

fn classify(tag: u8) -> u8 {
    match tag {
        0 => 0,
        // Safety: only 0 is reachable at this point.
        _ => unsafe { hint::unreachable_unchecked() },
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_ignores_utf8_invariant_comment_block(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::str;

fn decode(bytes: &[u8]) -> &str {
    // The parser input came in as &str with a UTF-8 guarantee,
    // and escapes are validated along the way, so do not need to
    // check here.
    unsafe { str::from_utf8_unchecked(bytes) }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_ignores_repr_transparent_transmute(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::mem;

#[repr(transparent)]
pub struct RawValue {
    json: str,
}

impl RawValue {
    pub fn from_borrowed(json: &str) -> &Self {
        unsafe { mem::transmute::<&str, &RawValue>(json) }
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_ignores_wrapper_type_from_raw_parts_calls(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
pub struct UninitSlice;

impl UninitSlice {
    pub unsafe fn from_raw_parts_mut(ptr: *mut u8, len: usize) -> &'static mut Self {
        let _ = (ptr, len);
        loop {}
    }
}

fn extend(ptr: *mut u8, len: usize) {
    unsafe { UninitSlice::from_raw_parts_mut(ptr, len) };
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_ignores_from_raw_parts_wrapper_impl(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use core::mem::MaybeUninit;

pub struct UninitSlice;

impl UninitSlice {
    pub unsafe fn from_raw_parts_mut(ptr: *mut u8, len: usize) -> &'static mut Self {
        let maybe_init: &mut [MaybeUninit<u8>] =
            core::slice::from_raw_parts_mut(ptr as *mut _, len);
        let _ = maybe_init;
        loop {}
    }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_detect_unsafe_api_usage_ignores_documented_vec_rebuilds(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
fn rebuild(ptr: *mut u8, len: usize, cap: usize) -> Vec<u8> {
    // The ptr + len always represents the end of that buffer.
    // Thus, we can safely reconstruct a Vec from it without leaking memory.
    let _unused = len;
    unsafe { Vec::from_raw_parts(ptr, len, cap) }
}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        entries, _ = detect_unsafe_api_usage(tmp_path)

    assert entries == []


def test_public_api_detectors_ignore_restricted_visibility_items(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "src/lib.rs",
        """
use std::cell::RefCell;

pub(crate) struct SharedState {
    pub inner: RefCell<String>,
    pub ready: bool,
}

impl SharedState {
    pub(crate) fn get_name(&self) -> &str { "name" }
}

pub(crate) fn parse() -> anyhow::Result<()> {
    panic!("nope");
}

unsafe impl Send for SharedState {}
""",
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        api_entries, _ = detect_public_api_conventions(tmp_path)
        error_entries, _ = detect_error_boundaries(tmp_path)
        future_entries, _ = detect_future_proofing(tmp_path)
        thread_entries, _ = detect_thread_safety_contracts(tmp_path)

    assert api_entries == []
    assert error_entries == []
    assert future_entries == []
    assert thread_entries == []


def test_phase_signature_skips_common_rust_constructors(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    for index in range(4):
        _write(
            tmp_path,
            f"src/module_{index}.rs",
            f"""
pub struct Service{index};

impl Service{index} {{
    pub fn new(value: i32) -> Self {{
        Self
    }}
}}
""",
        )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        issues, potentials = phase_signature(tmp_path, get_lang("rust"))

    assert issues == []
    assert potentials == {}
