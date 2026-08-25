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


def test_test_module_directories_are_not_production_logic():
    content = "pub async fn bootstrap_fixture() {}\n"
    assert (
        rust_cov.has_testable_logic(
            "src/schema/postgres_tests/bootstrap_access.rs",
            content,
        )
        is False
    )


def test_owner_boundary_promotes_only_its_rust_child_modules():
    direct = {
        "crates/demo/src/domain.rs",
        "crates/demo/src/lib.rs",
    }
    transitive = {
        "crates/demo/src/domain/loading.rs",
        "crates/demo/src/domain/persistence/commit.rs",
        "crates/demo/src/unrelated.rs",
    }

    assert rust_cov.promote_owner_covered_files(direct, transitive) == {
        "crates/demo/src/domain/loading.rs",
        "crates/demo/src/domain/persistence/commit.rs",
    }


def test_declared_siblings_share_their_tested_rust_owner(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-cli"\nversion = "0.1.0"\n',
    )
    main = _write(
        tmp_path,
        "src/main.rs",
        """
#[path = "cli/commands.rs"]
mod commands;
#[path = "cli/transport.rs"]
mod transport;
""",
    )
    commands = _write(tmp_path, "src/cli/commands.rs", "pub fn run() {}\n")
    transport = _write(tmp_path, "src/cli/transport.rs", "pub fn send() {}\n")
    production_files = {
        str(main.resolve()),
        str(commands.resolve()),
        str(transport.resolve()),
    }

    assert rust_cov.promote_owner_covered_files(
        {str(commands.resolve())},
        {str(transport.resolve())},
        production_files,
    ) == {str(transport.resolve())}


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


def test_import_and_barrel_resolution_share_one_production_index(
    tmp_path,
    monkeypatch,
):
    _write(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo-app"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    barrel = _write(tmp_path, "src/lib.rs", "pub mod service;\npub use service::Service;\n")
    source = _write(tmp_path, "src/service.rs", "pub struct Service;\n")
    test_file = _write(tmp_path, "tests/service.rs", "use demo_app::service::Service;\n")
    production_files = {str(barrel.resolve()), str(source.resolve())}

    rust_cov._production_index_for.cache_clear()
    original = rust_cov.build_production_file_index
    calls = 0

    def counting_builder(files):
        nonlocal calls
        calls += 1
        return original(files)

    monkeypatch.setattr(rust_cov, "build_production_file_index", counting_builder)

    resolved = rust_cov.resolve_import_spec(
        "demo_app::service::Service",
        str(test_file.resolve()),
        production_files,
    )
    reexports = rust_cov.resolve_barrel_reexports(
        str(barrel.resolve()),
        production_files,
    )

    assert resolved == str(source.resolve())
    assert str(source.resolve()) in reexports
    assert calls == 1
    rust_cov._production_index_for.cache_clear()
