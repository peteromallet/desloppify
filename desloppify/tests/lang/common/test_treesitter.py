"""Tests for tree-sitter integration module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from desloppify.languages._framework.treesitter import is_available

# Skip all tests if tree-sitter-language-pack is not installed.
pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter-language-pack not installed"
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def go_file(tmp_path):
    """Create a temp Go file for testing."""
    code = """\
package main

import "fmt"

// Hello greets someone by name.
func Hello(name string) string {
    // This is a comment
    fmt.Println("Hello", name)
    return "Hello " + name
}

// Add adds two numbers.
func Add(a, b int) int {
    return a + b
}

// Tiny function (should be filtered by < 3 lines).
func Tiny() { return }

type MyStruct struct {
    Name string
    Age  int
}
"""
    f = tmp_path / "main.go"
    f.write_text(code)
    return str(f)


@pytest.fixture
def rust_file(tmp_path):
    """Create a temp Rust file for testing."""
    code = """\
use crate::module::Foo;
use std::io::Read;

fn hello(name: &str) -> String {
    // A comment
    println!("Hello {}", name);
    format!("Hello {}", name)
}

fn add(a: i32, b: i32) -> i32 {
    a + b
}

struct MyStruct {
    name: String,
    age: u32,
}
"""
    f = tmp_path / "main.rs"
    f.write_text(code)
    return str(f)


@pytest.fixture
def ruby_file(tmp_path):
    """Create a temp Ruby file for testing."""
    code = """\
class MyClass
  def hello(name)
    puts "Hello #{name}"
    return "Hello " + name
  end

  def self.world
    puts "world"
    return "world"
  end
end
"""
    f = tmp_path / "hello.rb"
    f.write_text(code)
    return str(f)


@pytest.fixture
def java_file(tmp_path):
    """Create a temp Java file for testing."""
    code = """\
import com.example.Foo;

public class MyClass {
    public void hello(String name) {
        System.out.println("Hello " + name);
        return;
    }

    public int add(int a, int b) {
        return a + b;
    }
}
"""
    f = tmp_path / "MyClass.java"
    f.write_text(code)
    return str(f)


@pytest.fixture
def c_file(tmp_path):
    """Create a temp C file for testing."""
    code = """\
#include "local.h"
#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

void hello(const char* name) {
    printf("Hello %s\\n", name);
    return;
}
"""
    f = tmp_path / "main.c"
    f.write_text(code)
    return str(f)


# ── Function extraction tests ────────────────────────────────


class TestGoExtraction:
    def test_extract_functions(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        functions = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        # Tiny() should be filtered (< 3 lines normalized)
        assert len(functions) == 2
        names = [f.name for f in functions]
        assert "Hello" in names
        assert "Add" in names

    def test_function_line_numbers(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        functions = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        hello = next(f for f in functions if f.name == "Hello")
        assert hello.line == 6
        assert hello.end_line == 10

    def test_function_params(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        functions = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        hello = next(f for f in functions if f.name == "Hello")
        assert "name" in hello.params

        add = next(f for f in functions if f.name == "Add")
        assert "a" in add.params
        assert "b" in add.params

    def test_body_hash_deterministic(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        functions1 = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        functions2 = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        for f1, f2 in zip(functions1, functions2, strict=False):
            assert f1.body_hash == f2.body_hash

    def test_normalization_strips_comments(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        functions = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        hello = next(f for f in functions if f.name == "Hello")
        # Comment should be stripped from normalized body.
        assert "// This is a comment" not in hello.normalized
        # But the return statement should still be there.
        assert "return" in hello.normalized

    def test_normalization_strips_log_calls(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        functions = ts_extract_functions(tmp_path, GO_SPEC, [go_file])
        hello = next(f for f in functions if f.name == "Hello")
        assert "fmt.Println" not in hello.normalized


class TestRustExtraction:
    def test_extract_functions(self, rust_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import RUST_SPEC

        functions = ts_extract_functions(tmp_path, RUST_SPEC, [rust_file])
        names = [f.name for f in functions]
        assert "hello" in names

    def test_normalization_strips_println(self, rust_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import RUST_SPEC

        functions = ts_extract_functions(tmp_path, RUST_SPEC, [rust_file])
        hello = next(f for f in functions if f.name == "hello")
        assert "println!" not in hello.normalized


class TestRubyExtraction:
    def test_extract_methods(self, ruby_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import RUBY_SPEC

        functions = ts_extract_functions(tmp_path, RUBY_SPEC, [ruby_file])
        names = [f.name for f in functions]
        assert "hello" in names
        assert "world" in names


class TestJavaExtraction:
    def test_extract_methods(self, java_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import JAVA_SPEC

        functions = ts_extract_functions(tmp_path, JAVA_SPEC, [java_file])
        names = [f.name for f in functions]
        assert "hello" in names
        assert "add" in names


class TestCExtraction:
    def test_extract_functions(self, c_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import C_SPEC

        functions = ts_extract_functions(tmp_path, C_SPEC, [c_file])
        names = [f.name for f in functions]
        assert "add" in names
        assert "hello" in names


# ── Class extraction tests ────────────────────────────────────


class TestClassExtraction:
    def test_go_struct(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_classes,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        classes = ts_extract_classes(tmp_path, GO_SPEC, [go_file])
        names = [c.name for c in classes]
        assert "MyStruct" in names

    def test_rust_struct(self, rust_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_classes,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import RUST_SPEC

        classes = ts_extract_classes(tmp_path, RUST_SPEC, [rust_file])
        names = [c.name for c in classes]
        assert "MyStruct" in names

    def test_java_class(self, java_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_classes,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import JAVA_SPEC

        classes = ts_extract_classes(tmp_path, JAVA_SPEC, [java_file])
        names = [c.name for c in classes]
        assert "MyClass" in names

    def test_ruby_class(self, ruby_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_classes,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import RUBY_SPEC

        classes = ts_extract_classes(tmp_path, RUBY_SPEC, [ruby_file])
        names = [c.name for c in classes]
        assert "MyClass" in names

    def test_no_class_query_returns_empty(self, go_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_classes,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import BASH_SPEC

        classes = ts_extract_classes(tmp_path, BASH_SPEC, [go_file])
        assert classes == []


# ── Import resolution tests ──────────────────────────────────


class TestGoImportResolver:
    def test_stdlib_returns_none(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_go_import,
        )

        assert resolve_go_import("fmt", "/src/main.go", "/src") is None

    def test_external_pkg_returns_none(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_go_import,
        )

        # No go.mod => cannot determine if local.
        assert resolve_go_import("github.com/foo/bar", "/src/main.go", str(tmp_path)) is None

    def test_local_import_resolves(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolver_cache import (
            reset_import_cache,
        )
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_go_import,
        )

        reset_import_cache()

        # Create go.mod and a package directory.
        (tmp_path / "go.mod").write_text("module example.com/myproject\n")
        pkg_dir = tmp_path / "pkg" / "utils"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "utils.go").write_text("package utils\n")

        result = resolve_go_import(
            "example.com/myproject/pkg/utils",
            str(tmp_path / "main.go"),
            str(tmp_path),
        )
        assert result is not None
        assert result.endswith("utils.go")
        reset_import_cache()


class TestRustImportResolver:
    def test_external_crate_returns_none(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_rust_import,
        )

        assert resolve_rust_import("std::io::Read", "/src/main.rs", "/project") is None

    def test_crate_import_resolves(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_rust_import,
        )

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "module.rs").write_text("pub fn foo() {}")

        result = resolve_rust_import("crate::module", "/src/main.rs", str(tmp_path))
        assert result is not None
        assert "module.rs" in result


class TestRubyImportResolver:
    def test_relative_require(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_ruby_import,
        )

        (tmp_path / "helper.rb").write_text("# helper")
        result = resolve_ruby_import(
            "./helper", str(tmp_path / "main.rb"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("helper.rb")

    def test_absolute_require_in_lib(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_ruby_import,
        )

        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "helper.rb").write_text("# helper")

        result = resolve_ruby_import("helper", str(tmp_path / "main.rb"), str(tmp_path))
        assert result is not None
        assert result.endswith("helper.rb")


class TestCxxIncludeResolver:
    def test_relative_include(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_cxx_include,
        )

        (tmp_path / "local.h").write_text("// header")
        result = resolve_cxx_include(
            "local.h", str(tmp_path / "main.c"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("local.h")

    def test_nonexistent_returns_none(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_cxx_include,
        )

        result = resolve_cxx_include(
            "missing.h", str(tmp_path / "main.c"), str(tmp_path)
        )
        assert result is None


# ── Dep graph builder tests ──────────────────────────────────


class TestDepGraphBuilder:
    def test_go_dep_graph(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolver_cache import (
            reset_import_cache,
        )
        from desloppify.languages._framework.treesitter.imports.graph import (
            ts_build_dep_graph,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        reset_import_cache()

        (tmp_path / "go.mod").write_text("module example.com/test\n")
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        main_file = tmp_path / "main.go"
        pkg_file = pkg_dir / "pkg.go"

        main_file.write_text('package main\nimport "example.com/test/pkg"\nfunc main() { pkg.Do() }\n')
        pkg_file.write_text("package pkg\nfunc Do() {}\n")

        graph = ts_build_dep_graph(
            tmp_path, GO_SPEC, [str(main_file), str(pkg_file)]
        )
        assert len(graph) == 2
        # main.go should import pkg.go
        main_imports = graph[str(main_file)]["imports"]
        assert str(pkg_file) in main_imports
        reset_import_cache()

    def test_no_import_query_returns_empty(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.graph import (
            ts_build_dep_graph,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import BASH_SPEC

        graph = ts_build_dep_graph(tmp_path, BASH_SPEC, [])
        assert graph == {}


# ── Normalizer tests ──────────────────────────────────────────


class TestNormalize:
    def test_strips_comments(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            _get_parser,
            _make_query,
            _run_query,
            _unwrap_node,
        )
        from desloppify.languages._framework.treesitter.imports.normalize import normalize_body
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        source = b"""package main
func Hello() string {
    // comment to strip
    x := 1
    /* block comment */
    return "hello"
}
"""
        parser, language = _get_parser("go")
        tree = parser.parse(source)
        query = _make_query(language, GO_SPEC.function_query)
        matches = _run_query(query, tree.root_node)
        _, captures = matches[0]
        func_node = _unwrap_node(captures["func"])

        result = normalize_body(source, func_node, GO_SPEC)
        assert "// comment" not in result
        assert "/* block" not in result
        assert "x := 1" in result
        assert 'return "hello"' in result


# ── Graceful degradation tests ────────────────────────────────


class TestGracefulDegradation:
    def test_is_available_reflects_import(self):
        assert is_available() is True

    def test_is_available_false_when_uninstalled(self):
        with patch.dict("sys.modules", {"tree_sitter_language_pack": None}):
            # Re-importing won't change the cached _AVAILABLE, so test the guard
            import desloppify.languages._framework.treesitter as ts_mod
            saved = ts_mod._AVAILABLE
            ts_mod._AVAILABLE = False
            assert ts_mod.is_available() is False
            ts_mod._AVAILABLE = saved

    def test_generic_lang_stubs_without_treesitter(self):
        """When is_available() is False, generic_lang should use stubs."""
        import desloppify.languages._framework.treesitter as ts_mod
        from desloppify.languages._framework.generic_support.capabilities import (
            empty_dep_graph,
            noop_extract_functions,
        )

        saved = ts_mod._AVAILABLE
        ts_mod._AVAILABLE = False
        try:
            from desloppify.languages._framework.generic_support.core import generic_lang
            from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

            cfg = generic_lang(
                name="_test_no_ts",
                extensions=[".go"],
                tools=[{
                    "label": "dummy",
                    "cmd": "echo ok",
                    "fmt": "gnu",
                    "id": "dummy_check",
                    "tier": 3,
                }],
                treesitter_spec=GO_SPEC,
            )
            assert cfg.extract_functions is noop_extract_functions
            assert cfg.build_dep_graph is empty_dep_graph
        finally:
            ts_mod._AVAILABLE = saved
            # Clean up registry.
            from desloppify.languages._framework.registry import state as registry_state
            registry_state.remove("_test_no_ts")

    def test_file_read_error_skipped(self, tmp_path):
        """Files that can't be read are silently skipped."""
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        bad_path = str(tmp_path / "nonexistent.go")
        functions = ts_extract_functions(tmp_path, GO_SPEC, [bad_path])
        assert functions == []


# ── Integration with generic_lang ─────────────────────────────


class TestGenericLangIntegration:
    def test_go_is_full_plugin(self):
        import desloppify.languages.go  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("go")
        assert lang.extract_functions is not None
        assert lang.integration_depth == "full"

    def test_go_phases_include_structural(self):
        import desloppify.languages.go  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("go")
        phase_labels = [p.label for p in lang.phases]
        assert "Structural analysis" in phase_labels
        assert "Test coverage" in phase_labels
        assert "Security" in phase_labels

    def test_rust_is_full_plugin(self):
        import desloppify.languages.rust  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("rust")
        assert lang.extract_functions is not None
        assert lang.integration_depth == "full"

    def test_rust_phases_include_structural(self):
        import desloppify.languages.rust  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("rust")
        phase_labels = [p.label for p in lang.phases]
        assert "Structural analysis" in phase_labels
        assert "Test coverage" in phase_labels
        assert "Security" in phase_labels



# ── Spec validation tests ─────────────────────────────────────


class TestSpecValidation:
    """Verify that all specs can actually create queries without errors."""

    def _test_spec(self, spec):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            _get_parser,
            _make_query,
        )

        parser, language = _get_parser(spec.grammar)
        # Verify function query compiles.
        if spec.function_query:
            q = _make_query(language, spec.function_query)
            assert q is not None
        # Verify import query compiles.
        if spec.import_query:
            q = _make_query(language, spec.import_query)
            assert q is not None
        # Verify class query compiles.
        if spec.class_query:
            q = _make_query(language, spec.class_query)
            assert q is not None

    def test_go_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC
        self._test_spec(GO_SPEC)

    def test_rust_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import RUST_SPEC
        self._test_spec(RUST_SPEC)

    def test_ruby_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import RUBY_SPEC
        self._test_spec(RUBY_SPEC)

    def test_java_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import JAVA_SPEC
        self._test_spec(JAVA_SPEC)

    def test_kotlin_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import KOTLIN_SPEC
        self._test_spec(KOTLIN_SPEC)

    def test_csharp_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import CSHARP_SPEC
        self._test_spec(CSHARP_SPEC)

    def test_swift_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import SWIFT_SPEC
        self._test_spec(SWIFT_SPEC)

    def test_php_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import PHP_SPEC
        self._test_spec(PHP_SPEC)

    def test_c_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import C_SPEC
        self._test_spec(C_SPEC)

    def test_cpp_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import CPP_SPEC
        self._test_spec(CPP_SPEC)

    def test_scala_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import SCALA_SPEC
        self._test_spec(SCALA_SPEC)

    def test_elixir_spec(self):
        from desloppify.languages._framework.treesitter.specs.functional import ELIXIR_SPEC
        self._test_spec(ELIXIR_SPEC)

    def test_haskell_spec(self):
        from desloppify.languages._framework.treesitter.specs.functional import HASKELL_SPEC
        self._test_spec(HASKELL_SPEC)

    def test_bash_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import BASH_SPEC
        self._test_spec(BASH_SPEC)

    def test_lua_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import LUA_SPEC
        self._test_spec(LUA_SPEC)

    def test_perl_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import PERL_SPEC
        self._test_spec(PERL_SPEC)

    def test_clojure_spec(self):
        from desloppify.languages._framework.treesitter.specs.functional import CLOJURE_SPEC
        self._test_spec(CLOJURE_SPEC)

    def test_zig_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import ZIG_SPEC
        self._test_spec(ZIG_SPEC)

    def test_nim_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import NIM_SPEC
        self._test_spec(NIM_SPEC)

    def test_powershell_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import POWERSHELL_SPEC
        self._test_spec(POWERSHELL_SPEC)

    def test_gdscript_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import GDSCRIPT_SPEC
        self._test_spec(GDSCRIPT_SPEC)

    def test_dart_spec(self):
        from desloppify.languages._framework.treesitter.specs.compiled import DART_SPEC
        self._test_spec(DART_SPEC)

    def test_js_spec(self):
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC
        self._test_spec(JS_SPEC)

    def test_erlang_spec(self):
        from desloppify.languages._framework.treesitter.specs.functional import ERLANG_SPEC
        self._test_spec(ERLANG_SPEC)

    def test_ocaml_spec(self):
        from desloppify.languages._framework.treesitter.specs.functional import OCAML_SPEC
        self._test_spec(OCAML_SPEC)

    def test_fsharp_spec(self):
        from desloppify.languages._framework.treesitter.specs.functional import FSHARP_SPEC
        self._test_spec(FSHARP_SPEC)


# ── Parse tree cache tests ────────────────────────────────────


class TestParseTreeCache:
    def test_cache_hit(self, go_file, tmp_path):
        from desloppify.base.runtime_state import make_runtime_context, runtime_scope
        from desloppify.languages._framework.treesitter.imports.cache import (
            current_parse_tree_cache,
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.extractors import _get_parser

        parser, _language = _get_parser("go")
        with runtime_scope(make_runtime_context()):
            enable_parse_cache()
            try:
                cache = current_parse_tree_cache()
                result1 = cache.get_or_parse(go_file, parser, "go")
                result2 = cache.get_or_parse(go_file, parser, "go")
                assert result1 is not None
                assert result2 is not None
                # Same tree object (cached).
                assert result1[1] is result2[1]
            finally:
                disable_parse_cache()

    def test_cache_disabled(self, go_file, tmp_path):
        from desloppify.base.runtime_state import make_runtime_context, runtime_scope
        from desloppify.languages._framework.treesitter.imports.cache import (
            current_parse_tree_cache,
            disable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.extractors import _get_parser

        with runtime_scope(make_runtime_context()):
            disable_parse_cache()
            parser, _language = _get_parser("go")
            cache = current_parse_tree_cache()
            result1 = cache.get_or_parse(go_file, parser, "go")
            result2 = cache.get_or_parse(go_file, parser, "go")
            assert result1 is not None
            assert result2 is not None
            # Different tree objects (not cached).
            assert result1[1] is not result2[1]

    def test_cache_cleanup(self):
        from desloppify.base.runtime_state import make_runtime_context, runtime_scope
        from desloppify.languages._framework.treesitter.imports.cache import (
            current_parse_tree_cache,
            disable_parse_cache,
            enable_parse_cache,
        )

        with runtime_scope(make_runtime_context()):
            enable_parse_cache()
            cache = current_parse_tree_cache()
            assert cache._enabled
            disable_parse_cache()
            assert not cache._enabled
            assert cache._trees == {}


# ── New import resolver tests ─────────────────────────────────


class TestBashSourceResolver:
    def test_resolve_relative(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_bash_source,
        )

        (tmp_path / "helper.sh").write_text("# helper")
        result = resolve_bash_source(
            "./helper.sh", str(tmp_path / "main.sh"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("helper.sh")

    def test_resolve_with_ext_added(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_bash_source,
        )

        (tmp_path / "lib.sh").write_text("# lib")
        result = resolve_bash_source(
            "./lib", str(tmp_path / "main.sh"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("lib.sh")

    def test_nonexistent_returns_none(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_bash_source,
        )

        result = resolve_bash_source(
            "./missing.sh", str(tmp_path / "main.sh"), str(tmp_path)
        )
        assert result is None


class TestPerlImportResolver:
    def test_local_module(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_perl_import,
        )

        lib_dir = tmp_path / "lib" / "MyApp" / "Model"
        lib_dir.mkdir(parents=True)
        (lib_dir / "User.pm").write_text("package MyApp::Model::User;")

        result = resolve_perl_import(
            "MyApp::Model::User", str(tmp_path / "app.pl"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("User.pm")

    def test_pragma_skipped(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_perl_import,
        )

        assert resolve_perl_import("strict", "/src/app.pl", "/src") is None
        assert resolve_perl_import("warnings", "/src/app.pl", "/src") is None

    def test_stdlib_prefix_skipped(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_perl_import,
        )

        assert resolve_perl_import("File::Basename", "/src/app.pl", "/src") is None
        assert resolve_perl_import("List::Util", "/src/app.pl", "/src") is None


class TestZigImportResolver:
    def test_local_import(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_zig_import,
        )

        (tmp_path / "utils.zig").write_text("pub fn foo() void {}")
        result = resolve_zig_import(
            '"utils.zig"', str(tmp_path / "main.zig"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("utils.zig")

    def test_std_skipped(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_zig_import,
        )

        assert resolve_zig_import('"std"', "/src/main.zig", "/src") is None
        assert resolve_zig_import('"builtin"', "/src/main.zig", "/src") is None


class TestHaskellImportResolver:
    def test_local_module(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_haskell_import,
        )

        src_dir = tmp_path / "src" / "MyApp"
        src_dir.mkdir(parents=True)
        (src_dir / "Module.hs").write_text("module MyApp.Module where")

        result = resolve_haskell_import(
            "MyApp.Module", str(tmp_path / "src" / "Main.hs"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("Module.hs")

    def test_stdlib_skipped(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_haskell_import,
        )

        assert resolve_haskell_import("Data.List", "/src/Main.hs", "/src") is None
        assert resolve_haskell_import("Control.Monad", "/src/Main.hs", "/src") is None
        assert resolve_haskell_import("System.IO", "/src/Main.hs", "/src") is None


class TestErlangIncludeResolver:
    def test_relative_include(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_erlang_include,
        )

        (tmp_path / "header.hrl").write_text("-record(my_record, {}).")
        result = resolve_erlang_include(
            '"header.hrl"', str(tmp_path / "main.erl"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("header.hrl")

    def test_include_dir(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_erlang_include,
        )

        inc_dir = tmp_path / "include"
        inc_dir.mkdir()
        (inc_dir / "defs.hrl").write_text("-define(X, 1).")

        result = resolve_erlang_include(
            '"defs.hrl"', str(tmp_path / "src" / "main.erl"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("defs.hrl")


class TestOcamlImportResolver:
    def test_local_module(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_ocaml_import,
        )

        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "mymodule.ml").write_text("let foo = 1")

        result = resolve_ocaml_import(
            "Mymodule", str(tmp_path / "main.ml"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("mymodule.ml")

    def test_stdlib_skipped(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_ocaml_import,
        )

        assert resolve_ocaml_import("List", "/src/main.ml", "/src") is None
        assert resolve_ocaml_import("Printf", "/src/main.ml", "/src") is None


class TestFsharpImportResolver:
    def test_local_module(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_fsharp_import,
        )

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "MyModule.fs").write_text("module MyModule")

        result = resolve_fsharp_import(
            "MyModule", str(tmp_path / "src" / "Program.fs"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("MyModule.fs")

    def test_stdlib_skipped(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_functional import (
            resolve_fsharp_import,
        )

        assert resolve_fsharp_import("System.IO", "/src/main.fs", "/src") is None
        assert resolve_fsharp_import("Microsoft.FSharp", "/src/main.fs", "/src") is None


class TestSwiftImportResolver:
    def test_local_module_path(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_swift_import,
        )

        target = tmp_path / "Sources" / "MyApp" / "Networking" / "Client.swift"
        target.parent.mkdir(parents=True)
        target.write_text("import Foundation\n")

        result = resolve_swift_import(
            "MyApp.Networking.Client",
            str(tmp_path / "Sources" / "MyApp" / "App.swift"),
            str(tmp_path),
        )
        assert result is not None
        assert result.endswith("Client.swift")

    def test_external_module_returns_none(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
            resolve_swift_import,
        )

        assert resolve_swift_import("Foundation", "/src/App.swift", "/src") is None


class TestJsImportResolver:
    def test_relative_import(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_js_import,
        )

        (tmp_path / "utils.js").write_text("export function foo() {}")
        result = resolve_js_import(
            "./utils", str(tmp_path / "main.js"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("utils.js")

    def test_npm_package_returns_none(self):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_js_import,
        )

        assert resolve_js_import("react", "/src/main.js", "/src") is None
        assert resolve_js_import("lodash/fp", "/src/main.js", "/src") is None

    def test_jsx_extension(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_js_import,
        )

        (tmp_path / "App.jsx").write_text("export default function App() {}")
        result = resolve_js_import(
            "./App", str(tmp_path / "index.js"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("App.jsx")

    def test_index_resolution(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
            resolve_js_import,
        )

        comp_dir = tmp_path / "components"
        comp_dir.mkdir()
        (comp_dir / "index.js").write_text("export const Button = () => {}")
        result = resolve_js_import(
            "./components", str(tmp_path / "app.js"), str(tmp_path)
        )
        assert result is not None
        assert result.endswith("index.js")


# ── JavaScript extraction tests ───────────────────────────────


class TestJavaScriptExtraction:
    @pytest.fixture
    def js_file(self, tmp_path):
        code = """\
import { foo } from './utils';

function greet(name) {
    console.log("Hello " + name);
    return "Hello " + name;
}

const add = (a, b) => {
    return a + b;
};

class Calculator {
    multiply(a, b) {
        return a * b;
    }
}
"""
        f = tmp_path / "app.js"
        f.write_text(code)
        return str(f)

    def test_function_extraction(self, js_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        functions = ts_extract_functions(tmp_path, JS_SPEC, [js_file])
        names = [f.name for f in functions]
        assert "greet" in names
        assert "add" in names
        assert "multiply" in names

    def test_class_extraction(self, js_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_classes,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        classes = ts_extract_classes(tmp_path, JS_SPEC, [js_file])
        names = [c.name for c in classes]
        assert "Calculator" in names

    def test_normalization_strips_console(self, js_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        functions = ts_extract_functions(tmp_path, JS_SPEC, [js_file])
        greet = next(f for f in functions if f.name == "greet")
        assert "console.log" not in greet.normalized
        assert "return" in greet.normalized


# ── R extraction tests ─────────────────────────────────────────


class TestRExtraction:
    @pytest.fixture
    def r_file(self, tmp_path):
        code = """\
# Named function assigned with <-
my_func <- function(x, y) {
    result <- x + y
    return(result)
}

# Anonymous function inside lapply
result <- lapply(items, function(i) {
    value <- process(i)
    transform(value)
    return(value)
})
"""
        f = tmp_path / "analysis.R"
        f.write_text(code)
        return str(f)

    def test_named_function_extraction(self, r_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import R_SPEC

        functions = ts_extract_functions(tmp_path, R_SPEC, [r_file])
        names = [f.name for f in functions]
        assert "my_func" in names

    def test_anonymous_function_extraction(self, r_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import R_SPEC

        functions = ts_extract_functions(tmp_path, R_SPEC, [r_file])
        names = [f.name for f in functions]
        assert "<anonymous>" in names, (
            "Anonymous functions in lapply() should be extracted with "
            "synthesized <anonymous> name"
        )

    def test_anonymous_function_has_correct_metadata(self, r_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import R_SPEC

        functions = ts_extract_functions(tmp_path, R_SPEC, [r_file])
        anon_fns = [f for f in functions if f.name == "<anonymous>"]
        assert len(anon_fns) >= 1
        fn = anon_fns[0]
        assert fn.file == r_file
        assert fn.line > 0
        assert fn.body_hash is not None


# ── ESLint parser tests ───────────────────────────────────────


class TestEslintParser:
    def test_parse_eslint_output(self):
        from pathlib import Path

        from desloppify.languages._framework.generic_support.core import parse_eslint

        output = """[
            {
                "filePath": "/src/app.js",
                "messages": [
                    {"ruleId": "no-unused-vars", "line": 3, "message": "x is not used"},
                    {"ruleId": "semi", "line": 7, "message": "Missing semicolon"}
                ]
            },
            {
                "filePath": "/src/utils.js",
                "messages": [
                    {"ruleId": "no-console", "line": 1, "message": "console.log not allowed"}
                ]
            }
        ]"""
        entries = parse_eslint(output, Path("/src"))
        assert len(entries) == 3
        assert entries[0]["file"] == "/src/app.js"
        assert entries[0]["line"] == 3
        assert entries[0]["message"] == "x is not used"
        assert entries[2]["file"] == "/src/utils.js"

    def test_parse_invalid_json(self):
        from pathlib import Path

        import pytest

        from desloppify.languages._framework.generic_support.core import parse_eslint
        from desloppify.languages._framework.generic_parts.parsers import (
            ToolParserError,
        )

        with pytest.raises(ToolParserError):
            parse_eslint("not json", Path("/src"))

    def test_parse_empty_messages(self):
        from pathlib import Path

        from desloppify.languages._framework.generic_support.core import parse_eslint

        output = '[{"filePath": "/src/clean.js", "messages": []}]'
        assert parse_eslint(output, Path("/src")) == []
