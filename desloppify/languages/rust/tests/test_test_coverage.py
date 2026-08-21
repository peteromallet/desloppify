"""Tests for Rust test-coverage hooks."""

from __future__ import annotations

from pathlib import Path

import desloppify.languages.rust.test_coverage as rust_cov


def _write(path: Path, rel_path: str, content: str) -> Path:
    target = path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_has_inline_tests_detects_cfg_test_and_test_attrs():
    content = """
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert_eq!(2, add(1, 1));
    }
}
"""
    assert rust_cov.has_inline_tests("src/lib.rs", content) is True


def test_strip_test_markers_for_rust():
    assert rust_cov.strip_test_markers("test_helper.rs") == "helper.rs"
    assert rust_cov.strip_test_markers("helper_test.rs") == "helper.rs"
    assert rust_cov.strip_test_markers("helper.rs") is None


def test_parse_test_import_specs_expands_use_trees():
    content = "use demo_app::{service::run, util::{self, parse}};\n"
    assert rust_cov.parse_test_import_specs(content) == [
        "demo_app::service::run",
        "demo_app::util",
        "demo_app::util::parse",
    ]


def test_map_test_to_source_prefers_src_peer_for_integration_tests(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    source = _write(tmp_path, "src/service.rs", "pub fn run() {}\n")
    test_file = _write(tmp_path, "tests/service.rs", "use demo_app::service::run;\n")

    mapped = rust_cov.map_test_to_source(str(test_file.resolve()), {str(source.resolve())})
    assert mapped == str(source.resolve())


def test_resolve_import_spec_uses_local_crate_name(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(tmp_path, "src/lib.rs", "pub mod service;\n")
    source = _write(tmp_path, "src/service.rs", "pub struct Service;\n")
    test_file = _write(tmp_path, "tests/service.rs", "use demo_app::service::Service;\n")

    resolved = rust_cov.resolve_import_spec(
        "demo_app::service::Service",
        str(test_file.resolve()),
        {str(source.resolve())},
    )
    assert resolved == str(source.resolve())


def test_resolve_import_spec_uses_custom_lib_name(tmp_path):
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
    _write(tmp_path, "src/lib.rs", "pub mod service;\n")
    source = _write(tmp_path, "src/service.rs", "pub struct Service;\n")
    test_file = _write(tmp_path, "tests/service.rs", "use demo_core::service::Service;\n")

    resolved = rust_cov.resolve_import_spec(
        "demo_core::service::Service",
        str(test_file.resolve()),
        {str(source.resolve())},
    )
    assert resolved == str(source.resolve())


def test_resolve_import_spec_uses_workspace_local_crates(tmp_path):
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["app", "support"]\n')
    _write(
        tmp_path,
        "app/Cargo.toml",
        '[package]\nname = "app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    _write(
        tmp_path,
        "support/Cargo.toml",
        '[package]\nname = "support-utils"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    source = _write(tmp_path, "support/src/helpers.rs", "pub struct Thing;\n")
    _write(tmp_path, "support/src/lib.rs", "pub mod helpers;\n")
    test_file = _write(
        tmp_path,
        "app/tests/helpers.rs",
        "use support_utils::helpers::Thing;\n",
    )

    resolved = rust_cov.resolve_import_spec(
        "support_utils::helpers::Thing",
        str(test_file.resolve()),
        {str(source.resolve())},
    )
    assert resolved == str(source.resolve())


def test_resolve_import_spec_uses_workspace_dependency_alias(tmp_path):
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["app", "support"]\n')
    _write(
        tmp_path,
        "app/Cargo.toml",
        """
[package]
name = "app"
version = "0.1.0"
edition = "2021"

[dependencies]
support = { package = "support-utils", path = "../support" }
""",
    )
    _write(
        tmp_path,
        "support/Cargo.toml",
        '[package]\nname = "support-utils"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    source = _write(tmp_path, "support/src/helpers.rs", "pub struct Thing;\n")
    _write(tmp_path, "support/src/lib.rs", "pub mod helpers;\n")
    test_file = _write(
        tmp_path,
        "app/tests/helpers.rs",
        "use support::helpers::Thing;\n",
    )

    resolved = rust_cov.resolve_import_spec(
        "support::helpers::Thing",
        str(test_file.resolve()),
        {str(source.resolve())},
    )
    assert resolved == str(source.resolve())


def test_direct_test_targets_expand_through_recursive_literal_includes(tmp_path):
    owner = _write(tmp_path, "src/lib.rs", 'include!("internal.rs");\n')
    internal = _write(tmp_path, "src/internal.rs", 'include!("nested/codec.rs");\n')
    codec = _write(tmp_path, "src/nested/codec.rs", "pub fn decode() {}\n")
    production = {str(owner.resolve()), str(internal.resolve()), str(codec.resolve())}

    expanded = rust_cov.expand_direct_test_targets({str(owner.resolve())}, production)

    assert expanded == {str(internal.resolve()), str(codec.resolve())}
