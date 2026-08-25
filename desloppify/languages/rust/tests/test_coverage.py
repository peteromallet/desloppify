"""Tests for Rust coverage hooks."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.languages.rust import test_coverage as rust_cov


def _write(tmp_path: Path, relpath: str, content: str) -> str:
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


def test_has_inline_tests_recognizes_cfg_test():
    content = (
        "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"
        "#[cfg(test)]\nmod tests {\n"
        "    #[test]\n    fn it_adds() { assert_eq!(4, 2 + 2); }\n}\n"
    )
    assert rust_cov.has_inline_tests("src/lib.rs", content) is True


def test_assertion_patterns_recognize_delegated_assertion_helpers():
    line = "assert_active_openapi_surface(&document);"

    assert any(pattern.search(line) for pattern in rust_cov.ASSERT_PATTERNS)


def test_map_test_to_source_matches_src_file_and_mod(tmp_path):
    _write(tmp_path, "Cargo.toml", "[package]\nname = 'demo-app'\nversion = '0.1.0'\n")
    test_file = _write(tmp_path, "tests/http.rs", "use demo_app::http::Client;\n")
    source_file = _write(tmp_path, "src/http.rs", "pub struct Client;\n")
    mod_file = _write(tmp_path, "src/api/mod.rs", "pub struct Api;\n")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        assert rust_cov.map_test_to_source(test_file, {source_file, mod_file}) == source_file
        assert rust_cov.map_test_to_source(
            _write(tmp_path, "tests/api.rs", "use demo_app::api::Api;\n"),
            {mod_file},
        ) == mod_file


def test_resolve_import_spec_matches_workspace_local_crate(tmp_path):
    _write(tmp_path, "Cargo.toml", "[workspace]\nmembers = ['crates/common']\n")
    _write(tmp_path, "app/Cargo.toml", "[package]\nname = 'demo-app'\nversion = '0.1.0'\n")
    test_file = _write(tmp_path, "app/tests/http.rs", "use common_utils::helpers::Thing;\n")
    target = _write(tmp_path, "crates/common/Cargo.toml", "[package]\nname = 'common-utils'\nversion = '0.1.0'\n")
    del target
    helper = _write(tmp_path, "crates/common/src/helpers.rs", "pub struct Thing;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        resolved = rust_cov.resolve_import_spec(
            "common_utils::helpers::Thing",
            test_file,
            {"crates/common/src/helpers.rs"},
        )

    assert resolved == "crates/common/src/helpers.rs"
    assert helper


def test_resolve_barrel_reexports_expands_pub_use(tmp_path):
    _write(tmp_path, "Cargo.toml", "[package]\nname = 'demo-app'\nversion = '0.1.0'\n")
    lib_file = _write(tmp_path, "src/lib.rs", "pub mod api;\npub use api::Client;\n")
    api_file = _write(tmp_path, "src/api.rs", "pub struct Client;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        expanded = rust_cov.resolve_barrel_reexports(
            lib_file,
            {"src/lib.rs", "src/api.rs"},
        )

    assert api_file
    assert expanded == {"src/api.rs"}


def test_parse_test_import_specs_expands_grouped_use():
    content = "use demo_app::{api::Client, util::{self, parse}};\n"
    specs = rust_cov.parse_test_import_specs(content)
    assert specs == ["demo_app::api::Client", "demo_app::util", "demo_app::util::parse"]
