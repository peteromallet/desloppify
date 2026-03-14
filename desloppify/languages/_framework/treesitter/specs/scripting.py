"""Tree-sitter specs for scripting/dynamic language families."""

from __future__ import annotations

from ..imports.resolvers_functional import resolve_zig_import
from ..imports.resolvers_scripts import (
    resolve_bash_source,
    resolve_js_import,
    resolve_lua_import,
    resolve_perl_import,
    resolve_r_import,
    resolve_ruby_import,
)
from ..types import TreeSitterLangSpec

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

R_SPEC = TreeSitterLangSpec(
    grammar="r",
    function_query="""
        (binary_operator
            (identifier) @name
            (function_definition
                (parameters) @params
                body: (braced_expression) @body)) @func
        (call
            function: (identifier) @fn
            arguments: (arguments
                (argument
                    (function_definition
                        (parameters) @params
                        body: (braced_expression) @body)))) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (call
            function: (identifier) @fn
            arguments: (arguments
                (argument) @path)) @import
        (call
            function: (namespace_operator
                (identifier) @path
                "::"
                (identifier) @fn)) @import
    """,
    resolve_import=resolve_r_import,
    log_patterns=(
        r"^\s*(?:print\(|cat\(|message\(|browser\(|debug\()",
    ),
)

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
