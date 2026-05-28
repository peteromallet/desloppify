"""Direct coverage for grouped tree-sitter import helper modules."""

from __future__ import annotations

import json
import builtins
from pathlib import Path
from types import SimpleNamespace

import desloppify.languages._framework.treesitter.imports.graph as graph_mod
import desloppify.languages._framework.treesitter.imports.normalize as normalize_mod
import desloppify.languages._framework.treesitter.imports.resolver_cache as resolver_cache_mod
import desloppify.languages._framework.treesitter.imports.resolvers_backend as backend_mod
import desloppify.languages._framework.treesitter.imports.resolvers_functional as functional_mod
import desloppify.languages._framework.treesitter.imports.resolvers_scripts as scripts_mod


class FakeNode:
    def __init__(
        self,
        type_: str,
        *,
        text: str = "",
        children: list["FakeNode"] | None = None,
        start_byte: int = 0,
        end_byte: int = 0,
    ) -> None:
        self.type = type_
        self.text = text.encode("utf-8")
        self.children = children or []
        self.child_count = len(self.children)
        self.start_byte = start_byte
        self.end_byte = end_byte


def test_graph_helpers_build_internal_edges_and_builder(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "src" / "main.php"
    dep_file = tmp_path / "src" / "support.php"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("<?php\n", encoding="utf-8")
    dep_file.write_text("<?php\n", encoding="utf-8")
    file_list = [str(source_file), str(dep_file)]

    monkeypatch.setattr(graph_mod, "_get_parser", lambda _grammar: ("parser", "language"))
    monkeypatch.setattr(graph_mod, "_make_query", lambda _language, source: source)
    monkeypatch.setattr(
        graph_mod,
        "get_or_parse_tree",
        lambda filepath, *_a, **_k: (b"", SimpleNamespace(root_node=filepath)),
    )
    matches = {
        str(source_file): [
            (0, {"path": FakeNode("string", text="'Thing'"), "prefix": FakeNode("identifier", text="App")}),
            (0, {"path": FakeNode("string", text="'external'")}),
            (0, {"other": FakeNode("identifier", text="ignored")}),
        ],
        str(dep_file): [],
    }
    monkeypatch.setattr(graph_mod, "_run_query", lambda _query, root: matches[root])
    monkeypatch.setattr(graph_mod, "_unwrap_node", lambda node: node)

    spec = SimpleNamespace(
        grammar="php",
        import_query="imports",
        resolve_import=lambda text, *_a: (
            str(dep_file.relative_to(tmp_path)) if text == "App\\Thing" else "/outside/file.php"
        ),
    )

    graph = graph_mod.ts_build_dep_graph(tmp_path, spec, file_list)
    assert graph[str(source_file)]["imports"] == {str(dep_file)}
    assert graph[str(dep_file)]["importers"] == {str(source_file)}
    assert graph[str(source_file)]["import_count"] == 1
    assert graph[str(dep_file)]["importer_count"] == 1

    builder = graph_mod.make_ts_dep_builder(spec, lambda _path: file_list)
    assert builder(tmp_path)[str(source_file)]["imports"] == {str(dep_file)}
    assert graph_mod.ts_build_dep_graph(
        tmp_path,
        SimpleNamespace(import_query=None, resolve_import=None),
        file_list,
    ) == {}


def test_graph_records_framework_files_as_importers(
    monkeypatch, tmp_path: Path, set_project_root
) -> None:
    """``.astro``/``.svelte``/``.vue`` files contribute importer edges to the
    host-language graph without becoming graph nodes themselves.

    Regression for a class of false positives that used to flag every JS
    module imported only from an Astro page/component as orphaned.
    """
    del set_project_root  # PROJECT_ROOT scoped to tmp_path via fixture

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target = src_dir / "config.js"
    target.write_text("export const X = 1;\n", encoding="utf-8")

    astro = src_dir / "Page.astro"
    astro.write_text(
        "---\nimport { X } from './config';\n---\n<html>{X}</html>\n",
        encoding="utf-8",
    )
    svelte = src_dir / "Widget.svelte"
    svelte.write_text(
        "<script>\nimport { X } from './config';\n</script>\n<div>{X}</div>\n",
        encoding="utf-8",
    )

    # Stub the tree-sitter pass so .js files alone produce no edges — the
    # importer edges in this test must come from the framework-file pass.
    monkeypatch.setattr(graph_mod, "_get_parser", lambda _grammar: ("parser", "language"))
    monkeypatch.setattr(graph_mod, "_make_query", lambda _language, source: source)
    monkeypatch.setattr(graph_mod, "get_or_parse_tree", lambda *_a, **_k: None)

    target_abs = str(target.resolve())

    def fake_resolve(text: str, _source_file: str, _scan_path: str) -> str | None:
        return target_abs if text == "./config" else None

    spec = SimpleNamespace(
        grammar="javascript",
        import_query="imports",
        resolve_import=fake_resolve,
    )
    file_list = [target_abs]

    graph = graph_mod.ts_build_dep_graph(
        tmp_path,
        spec,
        file_list,
        framework_extensions=(".astro", ".svelte"),
    )

    astro_abs = str(astro.resolve())
    svelte_abs = str(svelte.resolve())
    assert astro_abs in graph[target_abs]["importers"]
    assert svelte_abs in graph[target_abs]["importers"]
    assert graph[target_abs]["importer_count"] == 2
    # Framework files themselves are not graph nodes — they must not show
    # up in orphan or coupling reports.
    assert astro_abs not in graph
    assert svelte_abs not in graph


def test_graph_framework_pass_is_opt_in(
    monkeypatch, tmp_path: Path, set_project_root
) -> None:
    """Without ``framework_extensions``, framework files are ignored entirely."""
    del set_project_root

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target = src_dir / "config.js"
    target.write_text("export const X = 1;\n", encoding="utf-8")

    astro = src_dir / "Page.astro"
    astro.write_text(
        "---\nimport { X } from './config';\n---\n<html />\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(graph_mod, "_get_parser", lambda _grammar: ("parser", "language"))
    monkeypatch.setattr(graph_mod, "_make_query", lambda _language, source: source)
    monkeypatch.setattr(graph_mod, "get_or_parse_tree", lambda *_a, **_k: None)

    spec = SimpleNamespace(
        grammar="javascript",
        import_query="imports",
        resolve_import=lambda *_a, **_k: str(target.resolve()),
    )
    target_abs = str(target.resolve())

    graph = graph_mod.ts_build_dep_graph(tmp_path, spec, [target_abs])
    assert graph[target_abs]["importer_count"] == 0


def _make_fw_test_setup(monkeypatch, tmp_path: Path):
    """Build a minimal JS target file + stubbed tree-sitter pass.

    Returns ``(target_abs, src_dir, spec)`` for tests that want to drive
    ``ts_build_dep_graph``'s framework pass without exercising the host
    language's tree-sitter pipeline.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target = src_dir / "config.js"
    target.write_text("export const X = 1;\n", encoding="utf-8")

    monkeypatch.setattr(graph_mod, "_get_parser", lambda _grammar: ("parser", "language"))
    monkeypatch.setattr(graph_mod, "_make_query", lambda _language, source: source)
    monkeypatch.setattr(graph_mod, "get_or_parse_tree", lambda *_a, **_k: None)

    target_abs = str(target.resolve())

    def fake_resolve(text: str, _source_file: str, _scan_path: str) -> str | None:
        return target_abs if text == "./config" else None

    spec = SimpleNamespace(
        grammar="javascript",
        import_query="imports",
        resolve_import=fake_resolve,
    )
    return target_abs, src_dir, spec


def test_framework_pass_ignores_commented_imports(
    monkeypatch, tmp_path: Path, set_project_root
) -> None:
    """Commented-out imports (``//``, ``/* */``, ``<!-- -->``) must not create
    importer edges — they're the orphan detector's primary false-positive mode.
    """
    del set_project_root

    target_abs, src_dir, spec = _make_fw_test_setup(monkeypatch, tmp_path)

    (src_dir / "JsLine.astro").write_text(
        "---\n// import { X } from './config';\n---\n<html />\n",
        encoding="utf-8",
    )
    (src_dir / "JsBlock.astro").write_text(
        "---\n/* import { X } from './config'; */\n---\n<html />\n",
        encoding="utf-8",
    )
    (src_dir / "HtmlComment.vue").write_text(
        "<template><!-- import { X } from './config' --></template>\n",
        encoding="utf-8",
    )

    graph = graph_mod.ts_build_dep_graph(
        tmp_path,
        spec,
        [target_abs],
        framework_extensions=(".astro", ".vue"),
    )

    assert graph[target_abs]["importer_count"] == 0


def test_framework_pass_supports_vue_and_type_imports(
    monkeypatch, tmp_path: Path, set_project_root
) -> None:
    """Vue ``<script>`` blocks and ``import type`` qualifiers both contribute edges.

    ``.vue`` was in the default framework tuple from day one but only ``.astro``
    and ``.svelte`` had test coverage. Type-only imports are common in TS-backed
    framework projects and must not be dropped by the regex extractor.
    """
    del set_project_root

    target_abs, src_dir, spec = _make_fw_test_setup(monkeypatch, tmp_path)

    vue = src_dir / "Widget.vue"
    vue.write_text(
        "<script setup lang=\"ts\">\n"
        "import { X } from './config';\n"
        "</script>\n"
        "<template><div>{{ X }}</div></template>\n",
        encoding="utf-8",
    )
    type_only = src_dir / "Types.astro"
    type_only.write_text(
        "---\nimport type { X } from './config';\n---\n<html />\n",
        encoding="utf-8",
    )

    graph = graph_mod.ts_build_dep_graph(
        tmp_path,
        spec,
        [target_abs],
        framework_extensions=(".astro", ".vue"),
    )

    vue_abs = str(vue.resolve())
    type_only_abs = str(type_only.resolve())
    assert vue_abs in graph[target_abs]["importers"]
    assert type_only_abs in graph[target_abs]["importers"]
    assert graph[target_abs]["importer_count"] == 2


def test_framework_file_finder_honors_caller_supplied_exclusions(
    monkeypatch, tmp_path: Path, set_project_root
) -> None:
    """When ``framework_file_finder`` is provided, only the files it returns
    contribute importer edges — proving exclude-aware finders can suppress
    framework files in user-excluded directories (e.g. ``examples/``).
    """
    del set_project_root

    target_abs, src_dir, spec = _make_fw_test_setup(monkeypatch, tmp_path)

    included = src_dir / "Real.astro"
    included.write_text(
        "---\nimport { X } from './config';\n---\n<html />\n",
        encoding="utf-8",
    )
    excluded_dir = tmp_path / "examples"
    excluded_dir.mkdir()
    excluded = excluded_dir / "Demo.astro"
    excluded.write_text(
        "---\nimport { X } from './config';\n---\n<html />\n",
        encoding="utf-8",
    )

    def fw_finder(_path: Path) -> list[str]:
        return [str(included)]

    graph = graph_mod.ts_build_dep_graph(
        tmp_path,
        spec,
        [target_abs],
        framework_extensions=(".astro",),
        framework_file_finder=fw_finder,
    )

    assert graph[target_abs]["importer_count"] == 1
    assert str(included.resolve()) in graph[target_abs]["importers"]
    assert str(excluded.resolve()) not in graph[target_abs]["importers"]


def test_import_normalize_helpers_strip_comments_and_log_lines() -> None:
    cached = normalize_mod._get_log_patterns((r"logger\.",))
    assert cached is normalize_mod._get_log_patterns((r"logger\.",))

    source = b"def sample():\n    # comment\n    logger.info('x')\n    keep()\n"
    comment_start = source.index(b"# comment")
    comment_end = comment_start + len(b"# comment")
    func_node = FakeNode(
        "function_definition",
        children=[FakeNode("comment", start_byte=comment_start, end_byte=comment_end)],
        start_byte=0,
        end_byte=len(source),
    )
    spec = SimpleNamespace(
        comment_node_types=frozenset({"comment"}),
        log_patterns=(r"logger\.",),
    )

    comment_ranges = normalize_mod._collect_comment_ranges(
        func_node, spec.comment_node_types
    )
    assert comment_ranges == [(comment_start, comment_end)]
    assert normalize_mod._remove_byte_ranges(b"abc", []) == "abc"
    assert normalize_mod.normalize_body(source, func_node, spec) == "def sample():\n    keep()"


def test_resolver_cache_reads_module_path_and_reset_clears_cache(tmp_path: Path) -> None:
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module example.com/one\n", encoding="utf-8")

    assert resolver_cache_mod.read_go_module_path(str(go_mod)) == "example.com/one"
    go_mod.write_text("module example.com/two\n", encoding="utf-8")
    assert resolver_cache_mod.read_go_module_path(str(go_mod)) == "example.com/one"

    resolver_cache_mod.reset_import_cache()
    assert resolver_cache_mod.read_go_module_path(str(go_mod)) == "example.com/two"
    assert resolver_cache_mod.read_go_module_path(str(tmp_path / "missing.go.mod")) == ""


def test_backend_import_resolvers_cover_language_specific_paths(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    go_dir = tmp_path / "pkg" / "util"
    go_dir.mkdir(parents=True)
    go_file = go_dir / "util.go"
    go_file.write_text("package util\n", encoding="utf-8")
    assert (
        backend_mod.resolve_go_import(
            "example.com/demo/pkg/util", str(tmp_path / "main.go"), str(tmp_path)
        )
        == str(go_file)
    )
    assert backend_mod.resolve_go_import("fmt", str(tmp_path / "main.go"), str(tmp_path)) is None

    rust_dir = tmp_path / "src" / "nested"
    rust_dir.mkdir(parents=True)
    rust_mod = rust_dir / "mod.rs"
    rust_mod.write_text("pub fn ok() {}\n", encoding="utf-8")
    rust_leaf = tmp_path / "src" / "leaf.rs"
    rust_leaf.write_text("pub fn leaf() {}\n", encoding="utf-8")
    assert backend_mod.resolve_rust_import("crate::nested::Thing", "", str(tmp_path)) == str(rust_mod)
    assert backend_mod.resolve_rust_import("crate::leaf", "", str(tmp_path)) == str(rust_leaf)

    java_file = tmp_path / "src" / "main" / "java" / "com" / "acme" / "App.java"
    java_file.parent.mkdir(parents=True)
    java_file.write_text("class App {}\n", encoding="utf-8")
    assert backend_mod.resolve_java_import("com.acme.App", "", str(tmp_path)) == str(java_file)
    assert backend_mod.resolve_java_import("com.acme.*", "", str(tmp_path)) is None

    kotlin_file = tmp_path / "src" / "main" / "kotlin" / "com" / "acme" / "Feature.kt"
    kotlin_file.parent.mkdir(parents=True, exist_ok=True)
    kotlin_file.write_text("class Feature\n", encoding="utf-8")
    assert backend_mod.resolve_kotlin_import("com.acme.Feature", "", str(tmp_path)) == str(kotlin_file)

    include_file = tmp_path / "include" / "shared.h"
    include_file.parent.mkdir(parents=True)
    include_file.write_text("// header\n", encoding="utf-8")
    local_header = tmp_path / "src" / "local.h"
    local_header.parent.mkdir(parents=True, exist_ok=True)
    local_header.write_text("// local\n", encoding="utf-8")
    assert backend_mod.resolve_cxx_include("local.h", str(tmp_path / "src" / "main.c"), str(tmp_path)) == str(local_header)
    assert backend_mod.resolve_cxx_include("shared.h", str(tmp_path / "src" / "main.c"), str(tmp_path)) == str(include_file)

    csharp_file = tmp_path / "src" / "Demo" / "Widget.cs"
    csharp_file.parent.mkdir(parents=True, exist_ok=True)
    csharp_file.write_text("class Widget {}\n", encoding="utf-8")
    assert backend_mod.resolve_csharp_import("Demo.Widget", "", str(tmp_path)) == str(csharp_file)

    dart_file = tmp_path / "lib" / "src" / "utils.dart"
    dart_file.parent.mkdir(parents=True)
    dart_file.write_text("void util() {}\n", encoding="utf-8")
    assert backend_mod.resolve_dart_import("package:demo/src/utils.dart", "", str(tmp_path)) == str(dart_file)

    scala_file = tmp_path / "src" / "main" / "scala" / "com" / "acme" / "Thing.scala"
    scala_file.parent.mkdir(parents=True)
    scala_file.write_text("object Thing\n", encoding="utf-8")
    assert backend_mod.resolve_scala_import("com.acme.Thing", "", str(tmp_path)) == str(scala_file)

    swift_file = tmp_path / "Sources" / "Core" / "Core.swift"
    swift_file.parent.mkdir(parents=True)
    swift_file.write_text("struct Core {}\n", encoding="utf-8")
    assert backend_mod.resolve_swift_import("Core", str(tmp_path / "App.swift"), str(tmp_path)) == str(swift_file)


def test_functional_import_resolvers_cover_common_conventions(tmp_path: Path) -> None:
    assert functional_mod._camel_to_snake("MyHTTPClient") == "my_http_client"

    elixir_file = tmp_path / "lib" / "my_app" / "worker.ex"
    elixir_file.parent.mkdir(parents=True)
    elixir_file.write_text("defmodule MyApp.Worker do\nend\n", encoding="utf-8")
    assert functional_mod.resolve_elixir_import("MyApp.Worker", "", str(tmp_path)) == str(elixir_file)

    zig_dir = tmp_path / "src"
    zig_dir.mkdir(exist_ok=True)
    zig_file = zig_dir / "util.zig"
    zig_file.write_text("pub fn ok() void {}\n", encoding="utf-8")
    assert functional_mod.resolve_zig_import("util", str(zig_dir / "main.zig"), str(tmp_path)) == str(zig_file)
    assert functional_mod.resolve_zig_import("std", str(zig_dir / "main.zig"), str(tmp_path)) is None

    haskell_file = tmp_path / "src" / "Demo" / "Feature.hs"
    haskell_file.parent.mkdir(parents=True)
    haskell_file.write_text("module Demo.Feature where\n", encoding="utf-8")
    assert functional_mod.resolve_haskell_import("Demo.Feature", "", str(tmp_path)) == str(haskell_file)
    assert functional_mod.resolve_haskell_import("Data.List", "", str(tmp_path)) is None

    erlang_file = tmp_path / "include" / "demo.hrl"
    erlang_file.parent.mkdir(parents=True, exist_ok=True)
    erlang_file.write_text("-define(OK, true).\n", encoding="utf-8")
    assert functional_mod.resolve_erlang_include("demo.hrl", str(tmp_path / "src" / "demo.erl"), str(tmp_path)) == str(erlang_file)

    ocaml_file = tmp_path / "lib" / "worker.ml"
    ocaml_file.parent.mkdir(parents=True, exist_ok=True)
    ocaml_file.write_text("let run () = ()\n", encoding="utf-8")
    assert functional_mod.resolve_ocaml_import("MyApp.Worker", "", str(tmp_path)) == str(ocaml_file)
    assert functional_mod.resolve_ocaml_import("Stdlib.List", "", str(tmp_path)) is None

    fsharp_file = tmp_path / "src" / "Demo" / "Worker.fs"
    fsharp_file.parent.mkdir(parents=True, exist_ok=True)
    fsharp_file.write_text("module Demo.Worker\n", encoding="utf-8")
    assert functional_mod.resolve_fsharp_import("Demo.Worker", "", str(tmp_path)) == str(fsharp_file)
    assert functional_mod.resolve_fsharp_import("System.IO", "", str(tmp_path)) is None


def test_functional_import_resolver_returns_none_when_umbrella_listing_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    def _boom(_path: str) -> list[str]:
        raise OSError("boom")

    monkeypatch.setattr(functional_mod.os, "listdir", _boom)
    assert functional_mod.resolve_elixir_import("MyApp.Worker", "", str(tmp_path)) is None


def test_script_import_resolvers_cover_cached_paths_and_extensions(tmp_path: Path) -> None:
    ruby_file = tmp_path / "lib" / "helper.rb"
    ruby_file.parent.mkdir(parents=True)
    ruby_file.write_text("module Helper\nend\n", encoding="utf-8")
    assert scripts_mod.resolve_ruby_import("helper", str(tmp_path / "main.rb"), str(tmp_path)) == str(ruby_file)

    scripts_mod._PHP_FILE_CACHE.clear()
    scripts_mod._PHP_COMPOSER_CACHE.clear()
    composer = tmp_path / "composer.json"
    composer.write_text(
        json.dumps({"autoload": {"psr-4": {"App\\\\": "app/"}}}),
        encoding="utf-8",
    )
    php_file = tmp_path / "app" / "Models" / "User.php"
    php_file.parent.mkdir(parents=True)
    php_file.write_text("<?php\n", encoding="utf-8")
    assert scripts_mod._read_composer_psr4(str(tmp_path)) == {"App\\\\": "app/"}
    assert scripts_mod.resolve_php_import("App\\Models\\User", "", str(tmp_path)) == str(php_file)
    assert scripts_mod.resolve_php_import("User", "", str(tmp_path)) == str(php_file)

    lua_dir = tmp_path / "pkg"
    lua_dir.mkdir(exist_ok=True)
    init_lua = lua_dir / "init.lua"
    init_lua.write_text("return {}\n", encoding="utf-8")
    assert scripts_mod.resolve_lua_import("pkg", "", str(tmp_path)) == str(init_lua)

    js_dir = tmp_path / "src" / "ui"
    js_dir.mkdir(parents=True, exist_ok=True)
    js_file = js_dir / "index.js"
    js_file.write_text("export const ok = true;\n", encoding="utf-8")
    assert scripts_mod.resolve_js_import("./ui", str(tmp_path / "src" / "main.js"), str(tmp_path)) == str(js_file)

    bash_file = tmp_path / "scripts" / "shared.sh"
    bash_file.parent.mkdir(parents=True)
    bash_file.write_text("echo ok\n", encoding="utf-8")
    assert scripts_mod.resolve_bash_source("scripts/shared", str(tmp_path / "run.sh"), str(tmp_path)) == str(bash_file)

    perl_file = tmp_path / "lib" / "Demo" / "Worker.pm"
    perl_file.parent.mkdir(parents=True)
    perl_file.write_text("package Demo::Worker;\n1;\n", encoding="utf-8")
    assert scripts_mod.resolve_perl_import("Demo::Worker", "", str(tmp_path)) == str(perl_file)
    assert scripts_mod.resolve_perl_import("strict", "", str(tmp_path)) is None

    r_dir = tmp_path / "R"
    r_dir.mkdir(exist_ok=True)
    r_file = r_dir / "helpers.R"
    r_file.write_text("print('ok')\n", encoding="utf-8")
    assert scripts_mod.resolve_r_import("helpers.R", str(tmp_path / "analysis.R"), str(tmp_path)) == str(r_file)


def test_script_import_resolver_returns_empty_psr4_mapping_on_read_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    scripts_mod._PHP_COMPOSER_CACHE.clear()

    def _boom(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr(builtins, "open", _boom)
    assert scripts_mod._read_composer_psr4(str(tmp_path)) == {}


def test_script_import_cache_reset_invalidates_php_lookup_state(tmp_path: Path) -> None:
    scripts_mod.reset_script_import_caches()

    first_file = tmp_path / "app" / "User.php"
    first_file.parent.mkdir(parents=True, exist_ok=True)
    first_file.write_text("<?php\n", encoding="utf-8")
    assert scripts_mod.resolve_php_import("User", "", str(tmp_path)) == str(first_file)

    first_file.unlink()
    second_file = tmp_path / "lib" / "User.php"
    second_file.parent.mkdir(parents=True, exist_ok=True)
    second_file.write_text("<?php\n", encoding="utf-8")

    scripts_mod.reset_script_import_caches(str(tmp_path))

    assert scripts_mod.resolve_php_import("User", "", str(tmp_path)) == str(second_file)
