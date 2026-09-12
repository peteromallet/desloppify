"""Tree-sitter specs for compiled/backend language families."""

from __future__ import annotations

from ..imports.resolvers_backend import (
    resolve_csharp_import,
    resolve_dart_import,
    resolve_go_import,
    resolve_java_import,
    resolve_kotlin_import,
    resolve_rust_import,
)
from ..imports.resolvers_scripts import resolve_php_import
from ..types import TreeSitterLangSpec
from .compiled_native import C_SPEC, CPP_SPEC, SCALA_SPEC

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
    implicit_import_uses=(
        # Property delegation (`var x by remember { mutableStateOf(0) }`) resolves the
        # getValue/setValue/provideDelegate operators through imported extensions that
        # are never spelled out in the body. Pervasive in Compose Multiplatform.
        (r"^(?:getValue|setValue|provideDelegate)$", r"(?<![\w.])by\s"),
        # Destructuring declarations (`val (a, b) = pair`) call componentN() implicitly.
        (r"^component\d+$", r"(?m)^\s*(?:val|var)\s*\("),
    ),
    log_patterns=(
        r"^\s*(?:println\(|print\(|Logger\.|log\.)",
    ),
)

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

__all__ = [
    "C_SPEC",
    "CPP_SPEC",
    "SCALA_SPEC",
    "GO_SPEC",
    "RUST_SPEC",
    "JAVA_SPEC",
    "KOTLIN_SPEC",
    "CSHARP_SPEC",
    "SWIFT_SPEC",
    "PHP_SPEC",
    "DART_SPEC",
]
