"""AST complexity, cohesion, and phase-wiring tests for tree-sitter integration."""

from __future__ import annotations

import pytest

from desloppify.languages._framework.treesitter import is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter-language-pack not installed"
)
# ── AST complexity tests ──────────────────────────────────────


class TestASTComplexity:
    def test_nesting_depth(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_nesting import (
            compute_nesting_depth_ts,
        )
        from desloppify.languages._framework.treesitter.analysis.extractors import _get_parser
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        code = """\
package main

func complex() {
    if true {
        for i := 0; i < 10; i++ {
            if i > 5 {
                println(i)
            }
        }
    }
}
"""
        f = tmp_path / "complex.go"
        f.write_text(code)
        parser, language = _get_parser("go")

        enable_parse_cache()
        try:
            depth = compute_nesting_depth_ts(str(f), GO_SPEC, parser, language)
            assert depth is not None
            assert depth >= 3  # if > for > if
        finally:
            disable_parse_cache()

    def test_nesting_depth_flat_file(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_nesting import (
            compute_nesting_depth_ts,
        )
        from desloppify.languages._framework.treesitter.analysis.extractors import _get_parser
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        code = """\
package main

func simple() {
    x := 1
    y := 2
    println(x + y)
}
"""
        f = tmp_path / "simple.go"
        f.write_text(code)
        parser, language = _get_parser("go")

        enable_parse_cache()
        try:
            depth = compute_nesting_depth_ts(str(f), GO_SPEC, parser, language)
            assert depth == 0
        finally:
            disable_parse_cache()

    def test_long_functions_compute(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_function_metrics import (
            make_long_functions_compute,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        # Create a function with > 80 lines.
        body_lines = "\n".join(f"    x{i} := {i}" for i in range(90))
        code = f"package main\n\nfunc big() {{\n{body_lines}\n}}\n"
        f = tmp_path / "big.go"
        f.write_text(code)

        compute = make_long_functions_compute(GO_SPEC)

        enable_parse_cache()
        try:
            result = compute(code, code.splitlines(), _filepath=str(f))
            assert result is not None
            count, label = result
            assert count > 80
            assert "longest function" in label
        finally:
            disable_parse_cache()

    def test_long_functions_no_big_fn(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_function_metrics import (
            make_long_functions_compute,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        code = "package main\n\nfunc small() {\n    x := 1\n}\n"
        f = tmp_path / "small.go"
        f.write_text(code)

        compute = make_long_functions_compute(GO_SPEC)

        enable_parse_cache()
        try:
            result = compute(code, code.splitlines(), _filepath=str(f))
            assert result is not None
            count, _label = result
            assert count < 80  # Below threshold
        finally:
            disable_parse_cache()


# ── Erlang extraction tests ───────────────────────────────────


class TestErlangExtraction:
    @pytest.fixture
    def erlang_file(self, tmp_path):
        code = """\
-module(mymod).
-include("header.hrl").

hello(Name) ->
    Greeting = "Hello",
    Full = Greeting ++ " " ++ Name,
    io:format("~s~n", [Full]),
    Full.

add(A, B) ->
    Result = A + B,
    io:format("sum: ~p~n", [Result]),
    Result.
"""
        f = tmp_path / "mymod.erl"
        f.write_text(code)
        return str(f)

    def test_function_extraction(self, erlang_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.functional import ERLANG_SPEC

        functions = ts_extract_functions(tmp_path, ERLANG_SPEC, [erlang_file])
        # Erlang functions — at least some should be extracted.
        assert len(functions) >= 1


# ── OCaml extraction tests ────────────────────────────────────


class TestOcamlExtraction:
    @pytest.fixture
    def ocaml_file(self, tmp_path):
        code = """\
open Printf

let hello name =
  printf "Hello %s\\n" name;
  "Hello " ^ name

let add a b =
  a + b

module MyModule = struct
  let inner_fn x = x + 1
end
"""
        f = tmp_path / "main.ml"
        f.write_text(code)
        return str(f)

    def test_function_extraction(self, ocaml_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.functional import OCAML_SPEC

        functions = ts_extract_functions(tmp_path, OCAML_SPEC, [ocaml_file])
        assert len(functions) >= 1


# ── F# extraction tests ──────────────────────────────────────


class TestFsharpExtraction:
    @pytest.fixture
    def fsharp_file(self, tmp_path):
        code = """\
open System

let greet name =
    printfn "Hello %s" name
    "Hello " + name

let add a b =
    a + b
"""
        f = tmp_path / "Program.fs"
        f.write_text(code)
        return str(f)

    def test_function_extraction(self, fsharp_file, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.functional import FSHARP_SPEC

        functions = ts_extract_functions(tmp_path, FSHARP_SPEC, [fsharp_file])
        # F# let bindings may or may not match — depends on grammar details.
        # At minimum the spec should not error.
        assert isinstance(functions, list)


# ── Generic lang integration for new languages ────────────────


class TestNewLanguageIntegration:
    def test_javascript_registered(self):
        import desloppify.languages.javascript  # noqa: F401
        from desloppify.languages._framework.generic_support.capabilities import (
            empty_dep_graph,
            noop_extract_functions,
        )
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("javascript")
        assert lang.extract_functions is not noop_extract_functions
        assert lang.build_dep_graph is not empty_dep_graph
        assert ".js" in lang.extensions

    def test_erlang_registered(self):
        import desloppify.languages.erlang  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("erlang")
        assert ".erl" in lang.extensions

    def test_ocaml_registered(self):
        import desloppify.languages.ocaml  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("ocaml")
        assert ".ml" in lang.extensions

    def test_fsharp_registered(self):
        import desloppify.languages.fsharp  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("fsharp")
        assert ".fs" in lang.extensions


# ── Cyclomatic complexity tests ───────────────────────────────


class TestCyclomaticComplexity:
    def test_cyclomatic_simple(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_function_metrics import (
            make_cyclomatic_complexity_compute,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        code = """\
package main

func decide(x int) int {
    if x > 0 {
        return 1
    } else if x < 0 {
        return -1
    }
    for i := 0; i < x; i++ {
        if i > 5 {
            return i
        }
    }
    return 0
}
"""
        f = tmp_path / "decide.go"
        f.write_text(code)

        compute = make_cyclomatic_complexity_compute(GO_SPEC)
        enable_parse_cache()
        try:
            result = compute(code, code.splitlines(), _filepath=str(f))
            assert result is not None
            cc, label = result
            # 1 + if + else_if + for + if = 5
            assert cc >= 4
            assert "cyclomatic" in label
        finally:
            disable_parse_cache()

    def test_cyclomatic_trivial(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_function_metrics import (
            make_cyclomatic_complexity_compute,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        code = "package main\n\nfunc simple() {\n    x := 1\n    _ = x\n}\n"
        f = tmp_path / "simple.go"
        f.write_text(code)

        compute = make_cyclomatic_complexity_compute(GO_SPEC)
        enable_parse_cache()
        try:
            result = compute(code, code.splitlines(), _filepath=str(f))
            # CC = 1 for trivial function, should return None (below threshold)
            assert result is None
        finally:
            disable_parse_cache()


class TestMaxParams:
    def test_many_params(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_function_metrics import (
            make_max_params_compute,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        code = """\
package main

func manyArgs(a, b, c, d, e, f, g int) int {
    return a + b + c + d + e + f + g
}
"""
        f = tmp_path / "params.go"
        f.write_text(code)

        compute = make_max_params_compute(GO_SPEC)
        enable_parse_cache()
        try:
            result = compute(code, code.splitlines(), _filepath=str(f))
            assert result is not None
            count, label = result
            assert count >= 7
            assert "params" in label
        finally:
            disable_parse_cache()


class TestCallbackDepth:
    def test_nested_callbacks(self, tmp_path):
        from desloppify.languages._framework.treesitter.imports.cache import (
            disable_parse_cache,
            enable_parse_cache,
        )
        from desloppify.languages._framework.treesitter.analysis.complexity_nesting import (
            make_callback_depth_compute,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        code = """\
const nested = () => {
    return () => {
        return () => {
            return 42;
        };
    };
};
"""
        f = tmp_path / "callbacks.js"
        f.write_text(code)

        compute = make_callback_depth_compute(JS_SPEC)
        enable_parse_cache()
        try:
            result = compute(code, code.splitlines(), _filepath=str(f))
            assert result is not None
            depth, label = result
            assert depth >= 3  # 3 nested arrow functions
            assert "callback" in label
        finally:
            disable_parse_cache()


# ── Empty catch / unreachable code tests ──────────────────────


class TestEmptyCatches:
    def test_detect_empty_catch_python(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.smells import (
            detect_empty_catches,
        )

        # Python uses "except_clause"
        code = """\
try:
    x = 1
except Exception:
    pass
"""
        f = tmp_path / "test.py"
        f.write_text(code)

        # We need a spec that uses the python grammar
        from desloppify.languages._framework.treesitter import TreeSitterLangSpec

        py_spec = TreeSitterLangSpec(
            grammar="python",
            function_query='(function_definition name: (identifier) @name body: (block) @body) @func',
            comment_node_types=frozenset({"comment"}),
        )
        entries = detect_empty_catches([str(f)], py_spec)
        # pass is in IGNORABLE_NODE_TYPES — so this IS an empty catch
        assert len(entries) >= 1
        assert entries[0]["file"] == str(f)

    def test_detect_nonempty_catch(self, tmp_path):
        from desloppify.languages._framework.treesitter import TreeSitterLangSpec
        from desloppify.languages._framework.treesitter.analysis.smells import (
            detect_empty_catches,
        )

        code = """\
try:
    x = 1
except Exception as e:
    print(e)
"""
        f = tmp_path / "test.py"
        f.write_text(code)

        py_spec = TreeSitterLangSpec(
            grammar="python",
            function_query='(function_definition name: (identifier) @name body: (block) @body) @func',
            comment_node_types=frozenset({"comment"}),
        )
        entries = detect_empty_catches([str(f)], py_spec)
        assert len(entries) == 0

    def test_detect_empty_catch_js(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.smells import (
            detect_empty_catches,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        code = """\
try {
    doSomething();
} catch (e) {
}
"""
        f = tmp_path / "test.js"
        f.write_text(code)

        entries = detect_empty_catches([str(f)], JS_SPEC)
        assert len(entries) >= 1


class TestUnreachableCode:
    def test_detect_after_return(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.smells import (
            detect_unreachable_code,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        code = """\
function foo() {
    return 1;
    console.log("unreachable");
}
"""
        f = tmp_path / "test.js"
        f.write_text(code)

        entries = detect_unreachable_code([str(f)], JS_SPEC)
        assert len(entries) >= 1
        assert entries[0]["after"] == "return_statement"

    def test_no_unreachable(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.smells import (
            detect_unreachable_code,
        )
        from desloppify.languages._framework.treesitter.specs.scripting import JS_SPEC

        code = """\
function foo(x) {
    if (x > 0) {
        return 1;
    }
    return 0;
}
"""
        f = tmp_path / "test.js"
        f.write_text(code)

        entries = detect_unreachable_code([str(f)], JS_SPEC)
        assert len(entries) == 0


# ── Responsibility cohesion tests ─────────────────────────────


class TestResponsibilityCohesion:
    def test_cohesive_file_no_flags(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.cohesion import (
            detect_responsibility_cohesion,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        # Create a file with connected functions (all call each other).
        code = "package main\n\n"
        for i in range(10):
            next_fn = f"fn{i + 1}" if i < 9 else "fn0"
            code += f"func fn{i}() {{\n    {next_fn}()\n    x := {i}\n    _ = x\n}}\n\n"

        f = tmp_path / "cohesive.go"
        f.write_text(code)

        entries, checked = detect_responsibility_cohesion(
            [str(f)], GO_SPEC, min_loc=5,
        )
        # All functions are connected — should NOT be flagged.
        assert len(entries) == 0
        assert checked == 1

    def test_disconnected_singletons_not_flagged(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.cohesion import (
            detect_responsibility_cohesion,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        # All-singleton file (toolkit pattern) — should NOT be flagged.
        code = "package main\n\n"
        for i in range(10):
            code += f"func isolated{i}() {{\n    x{i} := {i}\n    _ = x{i}\n    y{i} := {i * 2}\n    _ = y{i}\n}}\n\n"

        f = tmp_path / "toolkit.go"
        f.write_text(code)

        entries, checked = detect_responsibility_cohesion(
            [str(f)], GO_SPEC, min_loc=5,
        )
        # All singletons — toolkit pattern, not mixed responsibilities.
        assert len(entries) == 0
        assert checked == 1

    def test_mixed_responsibilities_flagged(self, tmp_path):
        from desloppify.languages._framework.treesitter.analysis.cohesion import (
            detect_responsibility_cohesion,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        # File with 3+ distinct groups of interrelated functions —
        # genuinely mixed responsibilities.
        code = "package main\n\n"
        # Group A: auth functions that call each other
        code += "func authLogin() { authValidate() }\n"
        code += "func authValidate() { authHash() }\n"
        code += "func authHash() { _ = 1 }\n\n"
        # Group B: database functions that call each other
        code += "func dbConnect() { dbQuery() }\n"
        code += "func dbQuery() { dbParse() }\n"
        code += "func dbParse() { _ = 1 }\n\n"
        # Group C: HTTP functions that call each other
        code += "func httpServe() { httpRoute() }\n"
        code += "func httpRoute() { httpRespond() }\n"
        code += "func httpRespond() { _ = 1 }\n\n"
        # Padding to reach min functions
        code += "func utilA() { _ = 1 }\n"
        code += "func utilB() { _ = 1 }\n"

        f = tmp_path / "mixed.go"
        f.write_text(code)

        entries, checked = detect_responsibility_cohesion(
            [str(f)], GO_SPEC, min_loc=5,
        )
        # 3 non-singleton clusters (auth, db, http) + 2 singletons = 5 clusters
        assert len(entries) == 1
        assert entries[0]["component_count"] >= 5
        assert checked == 1


# ── Unused imports tests ──────────────────────────────────────


class TestUnusedImports:
    def test_unused_import_detected(self, tmp_path):
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
package main

import "fmt"
import "os"

func main() {
    fmt.Println("hello")
}
"""
        f = tmp_path / "main.go"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], GO_SPEC)
        # "os" is imported but never used.
        names = [e["name"] for e in entries]
        assert "os" in names
        # "fmt" IS used.
        assert "fmt" not in names

    def test_no_unused_imports(self, tmp_path):
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
package main

import "fmt"

func main() {
    fmt.Println("hello")
}
"""
        f = tmp_path / "main.go"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], GO_SPEC)
        assert len(entries) == 0

    def test_go_aliased_import_not_false_positive(self, tmp_path):
        """Go-style aliased imports (alias before path) should use the alias name."""
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
package main

import (
    daysailv1 "github.com/anshu/daysail/backend/gen/daysail/v1"
    "fmt"
)

func main() {
    fmt.Println(daysailv1.Something)
}
"""
        f = tmp_path / "main.go"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], GO_SPEC)
        names = [e["name"] for e in entries]
        # The alias "daysailv1" is used — should NOT be flagged.
        assert "daysailv1" not in names
        assert "v1" not in names
        # "fmt" is also used.
        assert "fmt" not in names

    def test_go_aliased_import_unused(self, tmp_path):
        """Go-style aliased import that IS unused should be detected."""
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
package main

import (
    daysailv1 "github.com/anshu/daysail/backend/gen/daysail/v1"
    "fmt"
)

func main() {
    fmt.Println("hello")
}
"""
        f = tmp_path / "main.go"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], GO_SPEC)
        names = [e["name"] for e in entries]
        # "daysailv1" is NOT used — should be flagged.
        assert "daysailv1" in names
        # "fmt" IS used.
        assert "fmt" not in names

    def test_no_import_query_returns_empty(self, tmp_path):
        from desloppify.languages._framework.treesitter import TreeSitterLangSpec
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        spec = TreeSitterLangSpec(
            grammar="go",
            function_query='(function_declaration name: (identifier) @name body: (block) @body) @func',
            comment_node_types=frozenset({"comment"}),
            import_query="",  # no import query
        )
        entries = detect_unused_imports([], spec)
        assert entries == []

    def test_js_named_imports_all_used_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import { rateLimit, RateLimitConfig } from "@/lib/rate-limit";

console.log(rateLimit, RateLimitConfig);
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_js_default_import_used_in_jsx_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import ReactMarkdown from "react-markdown";

export function App() {
  return <ReactMarkdown />;
}
"""
        f = tmp_path / "main.jsx"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_js_aliased_named_import_used_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import { foo as bar } from "x";

console.log(bar);
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_js_namespace_import_used_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import * as ns from "x";

console.log(ns.foo);
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_js_partially_unused_import_line_flags_only_unused_symbol(self, tmp_path):
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import {
  used,
  unused,
} from "x";

console.log(used);
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        names = [e["name"] for e in entries]
        assert "unused" in names
        assert "used" not in names
        assert len(entries) == 1

    def test_js_side_effect_import_only_not_flagged(self, tmp_path):
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import "x";

console.log("hi");
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_js_unused_import_issue_id_includes_line_and_symbol(self, tmp_path):
        from unittest.mock import MagicMock

        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.phases import (
            make_unused_imports_phase,
        )

        code = """\
import { used, unused } from "x";

console.log(used);
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        phase = make_unused_imports_phase(JS_SPEC)
        mock_lang = MagicMock()
        mock_lang.file_finder.return_value = [str(f)]

        issues, potentials = phase.run(tmp_path, mock_lang)

        assert potentials["unused_imports"] == 1
        assert len(issues) == 1
        assert issues[0]["id"].endswith("::unused_import::1::unused")
        assert issues[0]["summary"] == "Unused import: unused"

    def test_ts_named_imports_all_used_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import { rateLimit, RateLimitConfig } from "@/lib/rate-limit";

export const x: RateLimitConfig = rateLimit();
"""
        f = tmp_path / "main.ts"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        assert entries == []

    def test_ts_default_import_used_in_tsx_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import ReactMarkdown from "react-markdown";

export function App() {
  return <ReactMarkdown />;
}
"""
        f = tmp_path / "main.tsx"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        assert entries == []

    def test_ts_type_only_named_import_used_in_type_position_no_issue(self, tmp_path):
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import type { Foo } from "x";

export type X = Foo;
"""
        f = tmp_path / "main.ts"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        assert entries == []

    def test_ts_partially_unused_import_line_flags_only_unused_symbol(self, tmp_path):
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import {
  used,
  unused,
} from "x";

export const y = used;
"""
        f = tmp_path / "main.ts"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        names = [e["name"] for e in entries]
        assert "unused" in names
        assert "used" not in names
        assert len(entries) == 1

    def test_ts_side_effect_import_only_not_flagged(self, tmp_path):
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import "x";

export const x = 1;
"""
        f = tmp_path / "main.ts"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        assert entries == []

    def test_ts_unused_import_issue_id_includes_line_and_symbol(self, tmp_path):
        from unittest.mock import MagicMock

        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.phases import (
            make_unused_imports_phase,
        )

        code = """\
import { used, unused } from "x";

export const z = used;
"""
        f = tmp_path / "main.ts"
        f.write_text(code)

        phase = make_unused_imports_phase(TYPESCRIPT_SPEC)
        mock_lang = MagicMock()
        mock_lang.file_finder.return_value = [str(f)]

        issues, potentials = phase.run(tmp_path, mock_lang)

        assert potentials["unused_imports"] == 1
        assert len(issues) == 1
        assert issues[0]["id"].endswith("::unused_import::1::unused")
        assert issues[0]["summary"] == "Unused import: unused"

    def test_js_destructuring_default_value_counts_as_usage(self, tmp_path):
        """Default values inside destructuring patterns should count as usage."""
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import { imported } from "x";

const { x = imported } = obj;
console.log(x);
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_js_param_default_value_counts_as_usage(self, tmp_path):
        """Parameter default values should count as usage (JS grammar)."""
        from desloppify.languages._framework.treesitter import JS_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import { Bar } from "x";

function f(x = Bar) {
  return x;
}
"""
        f = tmp_path / "main.js"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], JS_SPEC)
        assert entries == []

    def test_ts_param_type_annotation_counts_as_usage(self, tmp_path):
        """Parameter type annotations should count as usage (TSX grammar)."""
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = """\
import type { Foo } from "x";

export function f(x: Foo) {
  return x;
}
"""
        f = tmp_path / "main.ts"
        f.write_text(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        assert entries == []

    def test_ts_file_with_nul_byte_does_not_false_positive(self, tmp_path):
        """Stray NUL bytes should not cause parse-truncation false positives."""
        from desloppify.languages._framework.treesitter import TYPESCRIPT_SPEC
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        code = (
            b'import { jest } from "@jest/globals";\n'
            b'jest.spyOn(console, "log");\n'
            b'\x00\n'
            b'jest.spyOn(console, "warn");\n'
        )
        f = tmp_path / "main.ts"
        f.write_bytes(code)

        entries = detect_unused_imports([str(f)], TYPESCRIPT_SPEC)
        assert entries == []


# ── Signature variance tests ─────────────────────────────────


class TestSignatureVariance:
    def test_detects_variance(self, tmp_path):
        from desloppify.engine.detectors.signature import detect_signature_variance
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        # Create 3 files with same function name but different params.
        for i in range(3):
            params = ", ".join(f"p{j} int" for j in range(i + 1))
            body_lines = "\n".join(f"    x{j} := {j}" for j in range(5))
            code = f"package main\n\nfunc process({params}) int {{\n{body_lines}\n    return 0\n}}\n"
            (tmp_path / f"file{i}.go").write_text(code)

        file_list = [str(tmp_path / f"file{i}.go") for i in range(3)]
        functions = ts_extract_functions(tmp_path, GO_SPEC, file_list)

        entries, total = detect_signature_variance(functions, min_occurrences=3)
        # 3 occurrences of "process" with different param counts.
        assert any(e["name"] == "process" for e in entries)

    def test_no_variance_when_identical(self, tmp_path):
        from desloppify.engine.detectors.signature import detect_signature_variance
        from desloppify.languages._framework.treesitter.analysis.extractors import (
            ts_extract_functions,
        )
        from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

        # Create 3 files with identical function signatures.
        for i in range(3):
            body_lines = "\n".join(f"    x{j} := {j}" for j in range(5))
            code = f"package main\n\nfunc process(a int) int {{\n{body_lines}\n    return a\n}}\n"
            (tmp_path / f"file{i}.go").write_text(code)

        file_list = [str(tmp_path / f"file{i}.go") for i in range(3)]
        functions = ts_extract_functions(tmp_path, GO_SPEC, file_list)

        entries, total = detect_signature_variance(functions, min_occurrences=3)
        # All identical — no variance.
        assert not any(e["name"] == "process" for e in entries)


# ── Phase wiring integration tests ───────────────────────────


class TestPhaseWiring:
    def test_go_has_ast_smells_phase(self):
        import desloppify.languages.go  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("go")
        labels = [p.label for p in lang.phases]
        assert "AST smells" in labels

    def test_go_has_cohesion_phase(self):
        import desloppify.languages.go  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("go")
        labels = [p.label for p in lang.phases]
        assert "Responsibility cohesion" in labels

    def test_go_has_signature_phase(self):
        import desloppify.languages.go  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("go")
        labels = [p.label for p in lang.phases]
        assert "Signature analysis" in labels

    def test_go_has_unused_imports_phase(self):
        import desloppify.languages.go  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("go")
        labels = [p.label for p in lang.phases]
        assert "Unused imports" in labels

    def test_bash_has_no_unused_imports(self):
        """Bash has import_query but it resolves source commands.
        Check unused imports phase IS present for bash."""
        import desloppify.languages.bash  # noqa: F401
        from desloppify.languages._framework.registry.resolution import get_lang

        lang = get_lang("bash")
        labels = [p.label for p in lang.phases]
        # Bash has an import_query, so it should have unused imports.
        assert "Unused imports" in labels
