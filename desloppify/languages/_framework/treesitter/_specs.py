"""Per-language TreeSitterLangSpec instances.

Each spec defines the tree-sitter grammar name, S-expression queries for
function/class/import extraction, comment node types, and optional import
resolver for dep-graph construction.
"""

from __future__ import annotations

from desloppify.languages._framework.treesitter import TreeSitterLangSpec

from ._imports import (
    resolve_bash_source,
    resolve_csharp_import,
    resolve_cxx_include,
    resolve_dart_import,
    resolve_elixir_import,
    resolve_erlang_include,
    resolve_fsharp_import,
    resolve_go_import,
    resolve_haskell_import,
    resolve_java_import,
    resolve_js_import,
    resolve_kotlin_import,
    resolve_lua_import,
    resolve_ocaml_import,
    resolve_perl_import,
    resolve_php_import,
    resolve_r_import,
    resolve_ruby_import,
    resolve_rust_import,
    resolve_scala_import,
    resolve_zig_import,
)

# ── Go ────────────────────────────────────────────────────────

GO_SPEC = TreeSitterLangSpec(
    grammar="go",
    function_query="""
        (function_declaration
            name: (identifier) @name
            body: (block) @body) @func
        (method_declaration
            name: (field_identifier) @name
            body: (block) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (import_spec
            path: (interpreted_string_literal) @path) @import
    """,
    resolve_import=resolve_go_import,
    class_query="""
        (type_declaration
            (type_spec
                name: (type_identifier) @name
                type: (struct_type) @body)) @class
    """,
    log_patterns=(
        r"^\s*(?:fmt\.Print|fmt\.Fprint|log\.)",
    ),
)

# ── Rust ──────────────────────────────────────────────────────

RUST_SPEC = TreeSitterLangSpec(
    grammar="rust",
    function_query="""
        (function_item
            name: (identifier) @name
            body: (block) @body) @func
    """,
    comment_node_types=frozenset({"line_comment", "block_comment"}),
    import_query="""
        (use_declaration
            argument: (_) @path) @import
    """,
    resolve_import=resolve_rust_import,
    class_query="""
        (struct_item
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:println!|eprintln!|dbg!|tracing::)",
    ),
)

# ── Ruby ──────────────────────────────────────────────────────

RUBY_SPEC = TreeSitterLangSpec(
    grammar="ruby",
    function_query="""
        (method
            name: (identifier) @name) @func
        (singleton_method
            name: (identifier) @name) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (call
            method: (identifier) @_method
            arguments: (argument_list
                (string
                    (string_content) @path)))
    """,
    resolve_import=resolve_ruby_import,
    class_query="""
        (class
            name: (constant) @name) @class
    """,
    log_patterns=(
        r"^\s*(?:puts |p |pp |Rails\.logger)",
    ),
)

# ── Java ──────────────────────────────────────────────────────

JAVA_SPEC = TreeSitterLangSpec(
    grammar="java",
    function_query="""
        (method_declaration
            name: (identifier) @name
            body: (block) @body) @func
        (constructor_declaration
            name: (identifier) @name
            body: (constructor_body) @body) @func
    """,
    comment_node_types=frozenset({"line_comment", "block_comment"}),
    import_query="""
        (import_declaration
            (scoped_identifier) @path) @import
    """,
    resolve_import=resolve_java_import,
    class_query="""
        (class_declaration
            name: (identifier) @name
            body: (class_body) @body) @class
        (interface_declaration
            name: (identifier) @name
            body: (interface_body) @body) @class
        (enum_declaration
            name: (identifier) @name
            body: (enum_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:System\.out\.|System\.err\.|Logger\.|log\.)",
    ),
)

# ── Kotlin ────────────────────────────────────────────────────

KOTLIN_SPEC = TreeSitterLangSpec(
    grammar="kotlin",
    function_query="""
        (function_declaration
            (simple_identifier) @name
            (function_body) @body) @func
    """,
    comment_node_types=frozenset({"line_comment", "multiline_comment"}),
    import_query="""
        (import_header
            (identifier) @path) @import
    """,
    resolve_import=resolve_kotlin_import,
    class_query="""
        (class_declaration
            (type_identifier) @name
            (class_body) @body) @class
        (object_declaration
            (type_identifier) @name
            (class_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:println\(|print\(|Logger\.|log\.)",
    ),
)

# ── C# ────────────────────────────────────────────────────────

CSHARP_SPEC = TreeSitterLangSpec(
    grammar="csharp",
    function_query="""
        (method_declaration
            name: (identifier) @name
            body: (block) @body) @func
        (constructor_declaration
            name: (identifier) @name
            body: (block) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (using_directive
            (identifier) @path) @import
    """,
    resolve_import=resolve_csharp_import,
    class_query="""
        (class_declaration
            name: (identifier) @name
            body: (declaration_list) @body) @class
        (interface_declaration
            name: (identifier) @name
            body: (declaration_list) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:Console\.Write|Debug\.Log|Logger\.)",
    ),
)

# ── Swift ─────────────────────────────────────────────────────

SWIFT_SPEC = TreeSitterLangSpec(
    grammar="swift",
    function_query="""
        (function_declaration
            name: (simple_identifier) @name
            body: (function_body) @body) @func
    """,
    comment_node_types=frozenset({"comment", "multiline_comment"}),
    class_query="""
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @class
        (protocol_declaration
            name: (type_identifier) @name
            body: (protocol_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:print\(|NSLog|os_log|Logger\.)",
    ),
)

# ── PHP ───────────────────────────────────────────────────────

PHP_SPEC = TreeSitterLangSpec(
    grammar="php",
    function_query="""
        (function_definition
            name: (name) @name
            body: (compound_statement) @body) @func
        (method_declaration
            name: (name) @name
            body: (compound_statement) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (namespace_use_declaration
            (namespace_use_clause
                (qualified_name) @path)) @import
        (namespace_use_declaration
            (namespace_name) @prefix
            (namespace_use_group
                (namespace_use_clause
                    (name) @path))) @import
        (use_declaration
            (qualified_name) @path) @import
        (use_declaration
            (name) @path) @import
    """,
    resolve_import=resolve_php_import,
    class_query="""
        (class_declaration
            name: (name) @name
            body: (declaration_list) @body) @class
        (interface_declaration
            name: (name) @name
            body: (declaration_list) @body) @class
        (trait_declaration
            name: (name) @name
            body: (declaration_list) @body) @class
        (enum_declaration
            name: (name) @name
            body: (enum_declaration_list) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:echo |print |var_dump|error_log|Log::)",
    ),
)

# ── Dart ──────────────────────────────────────────────────────

DART_SPEC = TreeSitterLangSpec(
    grammar="dart",
    function_query="""
        (function_signature
            name: (identifier) @name) @func
        (method_signature
            (function_signature
                name: (identifier) @name)) @func
    """,
    comment_node_types=frozenset({"comment", "documentation_comment"}),
    import_query="""
        (import_or_export
            (library_import
                (import_specification
                    (configurable_uri
                        (uri
                            (string_literal) @path))))) @import
    """,
    resolve_import=resolve_dart_import,
    class_query="""
        (class_definition
            name: (identifier) @name
            body: (class_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:print\(|debugPrint|log\.)",
    ),
)

# ── C ─────────────────────────────────────────────────────────

C_SPEC = TreeSitterLangSpec(
    grammar="c",
    function_query="""
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @name)
            body: (compound_statement) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (preproc_include
            path: (string_literal) @path) @import
    """,
    resolve_import=resolve_cxx_include,
    class_query="""
        (struct_specifier
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:printf\(|fprintf\(|perror\()",
    ),
)

# ── C++ ───────────────────────────────────────────────────────

CPP_SPEC = TreeSitterLangSpec(
    grammar="cpp",
    function_query="""
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @name)
            body: (compound_statement) @body) @func
        (function_definition
            declarator: (function_declarator
                declarator: (qualified_identifier) @name)
            body: (compound_statement) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (preproc_include
            path: (string_literal) @path) @import
    """,
    resolve_import=resolve_cxx_include,
    class_query="""
        (class_specifier
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @class
        (struct_specifier
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:std::cout|std::cerr|printf\(|fprintf\()",
    ),
)

# ── Scala ─────────────────────────────────────────────────────

SCALA_SPEC = TreeSitterLangSpec(
    grammar="scala",
    function_query="""
        (function_definition
            name: (identifier) @name
            body: (_) @body) @func
    """,
    comment_node_types=frozenset({"comment", "block_comment"}),
    import_query="""
        (import_declaration
            path: (identifier) @path) @import
    """,
    resolve_import=resolve_scala_import,
    class_query="""
        (class_definition
            name: (identifier) @name
            body: (template_body) @body) @class
        (object_definition
            name: (identifier) @name
            body: (template_body) @body) @class
        (trait_definition
            name: (identifier) @name
            body: (template_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:println\(|print\(|Logger\.|log\.)",
    ),
)

# ── Elixir ────────────────────────────────────────────────────

ELIXIR_SPEC = TreeSitterLangSpec(
    grammar="elixir",
    function_query="""
        (call
            target: (identifier) @_kind
            (arguments
                (call
                    target: (identifier) @name))) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (call
            target: (identifier) @_directive
            (arguments
                (alias) @path)) @import
    """,
    resolve_import=resolve_elixir_import,
    log_patterns=(
        r"^\s*(?:IO\.puts|IO\.inspect|Logger\.)",
    ),
)

# ── Haskell ───────────────────────────────────────────────────

HASKELL_SPEC = TreeSitterLangSpec(
    grammar="haskell",
    function_query="""
        (function
            name: (variable) @name
            match: (match) @body) @func
    """,
    comment_node_types=frozenset({"comment", "haddock"}),
    import_query="""
        (import module: (module) @path) @import
    """,
    resolve_import=resolve_haskell_import,
    log_patterns=(
        r"^\s*(?:putStrLn |print |hPutStrLn |traceShow)",
    ),
)

# ── Bash ──────────────────────────────────────────────────────

BASH_SPEC = TreeSitterLangSpec(
    grammar="bash",
    function_query="""
        (function_definition
            name: (word) @name
            body: (compound_statement) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (command
            name: (command_name) @_cmd
            argument: (word) @path) @import
    """,
    resolve_import=resolve_bash_source,
    log_patterns=(
        r"^\s*(?:echo |printf )",
    ),
)

# ── Lua ───────────────────────────────────────────────────────

LUA_SPEC = TreeSitterLangSpec(
    grammar="lua",
    function_query="""
        (function_declaration
            name: (identifier) @name
            body: (block) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (function_call
            name: (identifier) @_fn
            arguments: (arguments
                (string) @path)) @import
    """,
    resolve_import=resolve_lua_import,
    log_patterns=(
        r"^\s*(?:print\(|io\.write)",
    ),
)

# ── Perl ──────────────────────────────────────────────────────

PERL_SPEC = TreeSitterLangSpec(
    grammar="perl",
    function_query="""
        (subroutine_declaration_statement
            name: (bareword) @name
            body: (block) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (use_statement (package) @path) @import
    """,
    resolve_import=resolve_perl_import,
    log_patterns=(
        r"^\s*(?:print |say |warn )",
    ),
)

# ── Clojure ───────────────────────────────────────────────────

CLOJURE_SPEC = TreeSitterLangSpec(
    grammar="clojure",
    function_query="""
        (list_lit
            (sym_lit) @_keyword
            (sym_lit) @name) @func
    """,
    comment_node_types=frozenset({"comment"}),
    log_patterns=(
        r"^\s*\(println ",
    ),
)

# ── Zig ───────────────────────────────────────────────────────

ZIG_SPEC = TreeSitterLangSpec(
    grammar="zig",
    function_query="""
        (Decl
            (FnProto
                function: (IDENTIFIER) @name)
            (Block) @body) @func
    """,
    comment_node_types=frozenset({"line_comment"}),
    import_query="""
        (SuffixExpr
            (BUILTINIDENTIFIER) @_bi
            (FnCallArguments
                (ErrorUnionExpr
                    (SuffixExpr
                        (STRINGLITERALSINGLE) @path)))) @import
    """,
    resolve_import=resolve_zig_import,
    log_patterns=(
        r"^\s*(?:std\.debug\.print|std\.log\.)",
    ),
)

# ── Nim ───────────────────────────────────────────────────────

NIM_SPEC = TreeSitterLangSpec(
    grammar="nim",
    function_query="""
        (proc_declaration
            name: (identifier) @name
            body: (statement_list) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    log_patterns=(
        r"^\s*(?:echo |debugEcho )",
    ),
)

# ── PowerShell ────────────────────────────────────────────────

POWERSHELL_SPEC = TreeSitterLangSpec(
    grammar="powershell",
    function_query="""
        (function_statement
            (function_name) @name
            (script_block) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    log_patterns=(
        r"^\s*(?:Write-Host|Write-Output|Write-Debug|Write-Verbose)",
    ),
)

# ── GDScript ──────────────────────────────────────────────────

GDSCRIPT_SPEC = TreeSitterLangSpec(
    grammar="gdscript",
    function_query="""
        (function_definition
            name: (name) @name
            body: (body) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    class_query="""
        (class_definition
            name: (name) @name
            body: (class_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:print\(|push_error\(|push_warning\()",
    ),
)


# ── R ────────────────────────────────────────────────────────

R_SPEC = TreeSitterLangSpec(
    grammar="r",
    function_query="""
        (binary_operator
            (identifier) @name
            (function_definition
                (parameters) @params
                body: (braced_expression) @body)) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (call
            function: (identifier) @fn
            arguments: (arguments
                (argument) @path)) @import
    """,
    resolve_import=resolve_r_import,
    log_patterns=(
        r"^\s*(?:print\(|cat\(|message\(|browser\(|debug\()",
    ),
)


# ── Erlang ────────────────────────────────────────────────────

ERLANG_SPEC = TreeSitterLangSpec(
    grammar="erlang",
    function_query="""
        (fun_decl
            (function_clause
                (atom) @name
                (clause_body) @body)) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (pp_include (string) @path) @import
    """,
    resolve_import=resolve_erlang_include,
    log_patterns=(
        r"^\s*(?:io:format|error_logger:)",
    ),
)

# ── OCaml ─────────────────────────────────────────────────────

OCAML_SPEC = TreeSitterLangSpec(
    grammar="ocaml",
    function_query="""
        (value_definition
            (let_binding
                (value_name) @name)) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (open_module (module_path) @path) @import
    """,
    resolve_import=resolve_ocaml_import,
    class_query="""
        (module_definition
            (module_binding
                (module_name) @name)) @class
    """,
    log_patterns=(
        r"^\s*(?:Printf\.printf|print_endline|print_string|Format\.printf)",
    ),
)

# ── F# ───────────────────────────────────────────────────────

FSHARP_SPEC = TreeSitterLangSpec(
    grammar="fsharp",
    function_query="""
        (function_or_value_defn
            (function_declaration_left
                (identifier) @name)) @func
    """,
    comment_node_types=frozenset({"comment", "block_comment"}),
    import_query="""
        (import_decl (long_identifier) @path) @import
    """,
    resolve_import=resolve_fsharp_import,
    log_patterns=(
        r"^\s*(?:printfn |printf |eprintfn )",
    ),
)

# ── JavaScript ────────────────────────────────────────────────

JS_SPEC = TreeSitterLangSpec(
    grammar="javascript",
    function_query="""
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @func
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @func
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function
                body: (statement_block) @body)) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (import_statement
            source: (string (string_fragment) @path)) @import
    """,
    resolve_import=resolve_js_import,
    class_query="""
        (class_declaration
            name: (identifier) @name
            body: (class_body) @body) @class
    """,
    log_patterns=(r"^\s*console\.",),
)

# ── TypeScript ────────────────────────────────────────────────

# Uses the "tsx" grammar to handle both .ts and .tsx files.
# TS-specific node types differ slightly from JS (e.g. type annotations).
TYPESCRIPT_SPEC = TreeSitterLangSpec(
    grammar="tsx",
    function_query="""
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @func
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @func
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function
                body: (statement_block) @body)) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (import_statement
            source: (string (string_fragment) @path)) @import
    """,
    resolve_import=resolve_js_import,
    class_query="""
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @class
    """,
    log_patterns=(r"^\s*console\.",),
)

# ── Registry of all specs by language name ────────────────────

TREESITTER_SPECS: dict[str, TreeSitterLangSpec] = {
    "go": GO_SPEC,
    "rust": RUST_SPEC,
    "ruby": RUBY_SPEC,
    "java": JAVA_SPEC,
    "kotlin": KOTLIN_SPEC,
    "csharp": CSHARP_SPEC,
    "swift": SWIFT_SPEC,
    "php": PHP_SPEC,
    "dart": DART_SPEC,
    "c": C_SPEC,
    "cpp": CPP_SPEC,
    "scala": SCALA_SPEC,
    "elixir": ELIXIR_SPEC,
    "erlang": ERLANG_SPEC,
    "fsharp": FSHARP_SPEC,
    "haskell": HASKELL_SPEC,
    "javascript": JS_SPEC,
    "typescript": TYPESCRIPT_SPEC,
    "bash": BASH_SPEC,
    "lua": LUA_SPEC,
    "ocaml": OCAML_SPEC,
    "perl": PERL_SPEC,
    "clojure": CLOJURE_SPEC,
    "zig": ZIG_SPEC,
    "nim": NIM_SPEC,
    "powershell": POWERSHELL_SPEC,
    "gdscript": GDSCRIPT_SPEC,
    "r": R_SPEC,
}



__all__ = [
    "BASH_SPEC",
    "CLOJURE_SPEC",
    "CPP_SPEC",
    "CSHARP_SPEC",
    "C_SPEC",
    "DART_SPEC",
    "ELIXIR_SPEC",
    "ERLANG_SPEC",
    "FSHARP_SPEC",
    "GDSCRIPT_SPEC",
    "GO_SPEC",
    "HASKELL_SPEC",
    "JAVA_SPEC",
    "JS_SPEC",
    "KOTLIN_SPEC",
    "LUA_SPEC",
    "NIM_SPEC",
    "OCAML_SPEC",
    "PERL_SPEC",
    "PHP_SPEC",
    "POWERSHELL_SPEC",
    "R_SPEC",
    "RUBY_SPEC",
    "RUST_SPEC",
    "SCALA_SPEC",
    "SWIFT_SPEC",
    "TREESITTER_SPECS",
    "TYPESCRIPT_SPEC",
    "ZIG_SPEC",
]
