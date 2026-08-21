"""Tests for Rust dependency graph resolution."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.languages.rust.detectors.deps import build_dep_graph


def _write(tmp_path: Path, relpath: str, content: str) -> None:
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_build_dep_graph_resolves_mod_and_crate_use(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        "[package]\nname = 'demo-app'\nversion = '0.1.0'\n",
    )
    _write(
        tmp_path,
        "src/lib.rs",
        "mod foo;\npub mod bar;\nuse crate::bar::baz::Thing;\npub use foo::Foo;\n",
    )
    _write(tmp_path, "src/foo.rs", "pub struct Foo;\n")
    _write(tmp_path, "src/bar/mod.rs", "pub mod baz;\n")
    _write(tmp_path, "src/bar/baz.rs", "pub struct Thing;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert graph["src/lib.rs"]["imports"] == {"src/foo.rs", "src/bar/mod.rs", "src/bar/baz.rs"}
    assert "src/lib.rs" in graph["src/foo.rs"]["importers"]
    assert "src/lib.rs" in graph["src/bar/baz.rs"]["importers"]


def test_build_dep_graph_resolves_self_and_super_imports(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        "[package]\nname = 'demo-app'\nversion = '0.1.0'\n",
    )
    _write(tmp_path, "src/lib.rs", "pub mod foo;\npub mod shared;\n")
    _write(tmp_path, "src/shared.rs", "pub struct Shared;\n")
    _write(
        tmp_path,
        "src/foo.rs",
        "mod nested;\nuse self::nested::Helper;\nuse super::shared::Shared;\n",
    )
    _write(tmp_path, "src/foo/nested.rs", "pub struct Helper;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert "src/foo/nested.rs" in graph["src/foo.rs"]["imports"]
    assert "src/shared.rs" in graph["src/foo.rs"]["imports"]


def test_build_dep_graph_resolves_workspace_local_crates(tmp_path):
    _write(tmp_path, "Cargo.toml", "[workspace]\nmembers = ['crates/common']\n")
    _write(
        tmp_path,
        "app/Cargo.toml",
        "[package]\nname = 'demo-app'\nversion = '0.1.0'\n",
    )
    _write(tmp_path, "app/src/lib.rs", "use common_utils::helpers::Thing;\n")
    _write(
        tmp_path,
        "crates/common/Cargo.toml",
        "[package]\nname = 'common-utils'\nversion = '0.1.0'\n",
    )
    _write(tmp_path, "crates/common/src/lib.rs", "pub mod helpers;\n")
    _write(tmp_path, "crates/common/src/helpers.rs", "pub struct Thing;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert "crates/common/src/helpers.rs" in graph["app/src/lib.rs"]["imports"]


def test_build_dep_graph_resolves_workspace_dependency_aliases(tmp_path):
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["app", "support"]\n')
    _write(
        tmp_path,
        "app/Cargo.toml",
        """
[package]
name = "app"
version = "0.1.0"

[dependencies]
support = { package = "support-utils", path = "../support" }
""",
    )
    _write(
        tmp_path,
        "support/Cargo.toml",
        '[package]\nname = "support-utils"\nversion = "0.1.0"\n',
    )
    _write(tmp_path, "support/src/lib.rs", "pub mod helpers;\n")
    _write(tmp_path, "support/src/helpers.rs", "pub struct Thing;\n")
    _write(tmp_path, "app/src/lib.rs", "use support::helpers::Thing;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert "support/src/helpers.rs" in graph["app/src/lib.rs"]["imports"]


def test_build_dep_graph_resolves_custom_path_modules_and_restricted_mod_visibility(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        "[package]\nname = 'demo-app'\nversion = '0.1.0'\n",
    )
    _write(
        tmp_path,
        "src/lib.rs",
        '#[path = "generated/api.rs"]\npub(super) mod api;\n',
    )
    _write(tmp_path, "src/generated/api.rs", "pub struct Api;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert graph["src/lib.rs"]["imports"] == {"src/generated/api.rs"}


def test_build_dep_graph_ignores_external_crates(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        "[package]\nname = 'demo-app'\nversion = '0.1.0'\n",
    )
    _write(tmp_path, "src/lib.rs", "use serde::Deserialize;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert graph["src/lib.rs"]["imports"] == set()


def test_build_dep_graph_can_exclude_mod_edges_for_cycle_analysis(tmp_path):
    _write(
        tmp_path,
        "Cargo.toml",
        "[package]\nname = 'demo-app'\nversion = '0.1.0'\n",
    )
    _write(tmp_path, "src/lib.rs", "mod foo;\npub mod bar;\n")
    _write(tmp_path, "src/foo.rs", "use crate::bar::Thing;\n")
    _write(tmp_path, "src/bar.rs", "use crate::foo::Helper;\npub struct Thing;\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path, include_mod_declarations=False)

    assert graph["src/lib.rs"]["imports"] == set()
    assert graph["src/foo.rs"]["imports"] == {"src/bar.rs"}
    assert graph["src/bar.rs"]["imports"] == {"src/foo.rs"}


def test_build_dep_graph_resolves_literal_include_files(tmp_path):
    _write(tmp_path, "Cargo.toml", "[package]\nname = 'demo-app'\nversion = '0.1.0'\n")
    _write(tmp_path, "src/lib.rs", 'include!("internal/codec.rs");\n')
    _write(tmp_path, "src/internal/codec.rs", "pub fn decode() {}\n")

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        graph = build_dep_graph(tmp_path)

    assert graph["src/lib.rs"]["imports"] == {"src/internal/codec.rs"}
    assert graph["src/internal/codec.rs"]["importers"] == {"src/lib.rs"}
