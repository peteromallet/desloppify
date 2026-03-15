"""Tree-sitter based unused import detection.

Cross-references parsed import statements against file body to find
imports whose names don't appear elsewhere in the file.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .. import PARSE_INIT_ERRORS
from ..imports.cache import get_or_parse_tree
from .extractors import _get_parser, _make_query, _node_text, _run_query, _unwrap_node

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

logger = logging.getLogger(__name__)

_ECMASCRIPT_IMPORT_NODE_TYPE = "import_statement"

# Identifier-ish nodes that represent a reference to a binding in JavaScript/TypeScript.
# JSX tag names are typically represented as `identifier` in tree-sitter-javascript/tsx,
# but we include `jsx_identifier` as well for compatibility with grammar variants.
_ECMASCRIPT_REFERENCE_NODE_TYPES = frozenset({
    "identifier",
    "jsx_identifier",
    "type_identifier",
    "shorthand_property_identifier",
})

_ECMASCRIPT_ASSIGNMENT_PATTERN_NODE_TYPES = frozenset({
    "assignment_pattern",
    "object_assignment_pattern",
    "array_assignment_pattern",
})

_ECMASCRIPT_DECLARATION_NAME_NODE_TYPES = frozenset({
    # JS
    "function_declaration",
    "class_declaration",
    # TS/TSX
    "type_alias_declaration",
    "interface_declaration",
    "enum_declaration",
})


def detect_unused_imports(
    file_list: list[str],
    spec: TreeSitterLangSpec,
) -> list[dict]:
    """Find imports whose names are not referenced elsewhere in the file.

    Returns list of {file, line, name} entries.
    """
    if not spec.import_query:
        return []

    try:
        parser, language = _get_parser(spec.grammar)
    except PARSE_INIT_ERRORS as exc:
        logger.debug("tree-sitter init failed: %s", exc)
        return []

    # JavaScript/JSX: extract imported *local bindings* and check whether each
    # binding is referenced in the file body. This avoids module-path heuristics.
    if spec.grammar in ("javascript", "tsx"):
        return _detect_unused_imports_ecmascript(file_list, spec, parser, language)

    query = _make_query(language, spec.import_query)
    entries: list[dict] = []

    for filepath in file_list:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
        if cached is None:
            continue
        source, tree = cached
        source_text = source.decode("utf-8", errors="replace")

        matches = _run_query(query, tree.root_node)
        if not matches:
            continue

        for _pattern_idx, captures in matches:
            import_node = _unwrap_node(captures.get("import"))
            path_node = _unwrap_node(captures.get("path"))
            if not import_node or not path_node:
                continue

            raw_path = _node_text(path_node).strip("\"'`")
            if not raw_path:
                continue

            # Check for alias (e.g. PHP ``use Foo as Bar``, Python ``import X as Y``).
            # When an alias is present, search for the alias name instead.
            alias_name = _extract_alias(import_node)

            # Extract the imported name from the path.
            name = alias_name or _extract_import_name(raw_path)
            if not name:
                continue

            # Get the import statement's line range so we can exclude it
            # from the search.
            import_start = import_node.start_byte
            import_end = import_node.end_byte

            # Build text without the import statement itself.
            rest = source_text[:import_start] + source_text[import_end:]

            # Check if the name appears in the rest of the file.
            if not re.search(r'\b' + re.escape(name) + r'\b', rest):
                entries.append({
                    "file": filepath,
                    "line": import_node.start_point[0] + 1,
                    "name": name,
                })

    return entries


def _detect_unused_imports_ecmascript(
    file_list: list[str],
    spec: TreeSitterLangSpec,
    parser,
    language,
) -> list[dict]:
    """Binding-aware unused import detection for JavaScript/TypeScript (JSX/TSX).

    Emits one entry per unused imported local binding:
    {file, line, name, symbol}

    Side-effect-only imports (e.g. `import "x"`) are ignored.
    """
    query = _make_query(language, f"({_ECMASCRIPT_IMPORT_NODE_TYPE}) @import")
    entries: list[dict] = []

    for filepath in file_list:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
        if cached is None:
            continue
        source, tree = cached

        # Some real-world repos contain stray NUL bytes (e.g. broken fixtures).
        # Tree-sitter can treat these as parse-stopping errors, leading to false
        # positives due to missing references. Replace NUL with space (same length)
        # and re-parse for analysis.
        if b"\x00" in source:
            source = source.replace(b"\x00", b" ")
            tree = parser.parse(source)

        # If the parse is still errorful, be conservative and skip this file to
        # avoid false positives from incomplete trees.
        if getattr(tree.root_node, "has_error", False):
            continue

        matches = _run_query(query, tree.root_node)
        if not matches:
            continue

        referenced = _collect_ecmascript_references(tree.root_node)

        for _pattern_idx, captures in matches:
            import_node = _unwrap_node(captures.get("import"))
            if not import_node:
                continue

            bindings = _extract_ecmascript_import_bindings(import_node)
            if not bindings:
                # Side-effect import (`import "x"`) or empty named import (`import {} from "x"`).
                continue

            line = import_node.start_point[0] + 1
            for symbol in bindings:
                if symbol not in referenced:
                    entries.append({
                        "file": filepath,
                        "line": line,
                        "name": symbol,
                        "symbol": symbol,
                    })

    return entries


def _extract_ecmascript_import_bindings(import_node) -> list[str]:
    """Extract local binding names from an ECMAScript import_statement node."""
    import_clause = None
    for child in import_node.named_children:
        if child.type == "import_clause":
            import_clause = child
            break
    if import_clause is None:
        return []

    bindings: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        bindings.append(name)

    for child in import_clause.named_children:
        # Default import: `import Foo from "x"`
        if child.type == "identifier":
            add(_node_text(child))
            continue

        # Namespace import: `import * as ns from "x"`
        if child.type == "namespace_import":
            for grand in child.named_children:
                if grand.type == "identifier":
                    add(_node_text(grand))
                    break
            continue

        # Named imports: `import { a, b as c } from "x"`
        if child.type == "named_imports":
            for spec in child.named_children:
                if spec.type != "import_specifier":
                    continue
                alias = spec.child_by_field_name("alias")
                name = spec.child_by_field_name("name")
                add(_node_text(alias) if alias is not None else _node_text(name))
            continue

    return bindings


def _collect_ecmascript_references(root_node) -> set[str]:
    """Collect identifier-like references outside ECMAScript import statements."""
    referenced: set[str] = set()
    stack = [root_node]

    while stack:
        node = stack.pop()
        if node.type in _ECMASCRIPT_REFERENCE_NODE_TYPES and not _has_ancestor_type(
            node, {_ECMASCRIPT_IMPORT_NODE_TYPE}
        ):
            if not _is_ecmascript_declaration_occurrence(node):
                text = _node_text(node)
                if text:
                    referenced.add(text)

        for child in reversed(node.named_children):
            stack.append(child)

    return referenced


def _has_ancestor_type(node, ancestor_types: set[str]) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in ancestor_types:
            return True
        parent = parent.parent
    return False


def _is_ecmascript_declaration_occurrence(node) -> bool:
    """Return True when `node` appears in a declaration/binding position.

    This prevents counting declarations as references (e.g. destructuring patterns,
    parameter names, catch parameters, type names).

    Not a full scope resolver; it is a conservative structural filter.
    """
    # If we're on the right side of an assignment pattern, treat as an expression reference.
    if _is_within_assignment_pattern_right(node):
        return False

    cur = node
    while cur is not None:
        # Variable declarators: `const foo = ...`, `const {a: b} = ...`
        if cur.type == "variable_declarator":
            name = cur.child_by_field_name("name")
            if name is not None and _is_descendant(name, node):
                return True

        # TS/TSX params: `required_parameter` / `optional_parameter` pattern field.
        if cur.type in ("required_parameter", "optional_parameter"):
            pattern = cur.child_by_field_name("pattern")
            if pattern is not None and _is_descendant(pattern, node):
                return True

        # JS params: patterns live directly under `formal_parameters`.
        if cur.type == "formal_parameters":
            param_root = _direct_child_under(cur, node)
            if param_root is not None:
                # TS/TSX wraps params in required/optional_parameter; handled above.
                if param_root.type not in ("required_parameter", "optional_parameter"):
                    if _is_param_binding_occurrence(param_root, node):
                        return True

        # Catch binding: `catch (e) { ... }`
        if cur.type == "catch_clause":
            param = cur.child_by_field_name("parameter")
            if param is not None and _is_descendant(param, node):
                return True

        # Declaration names (function/class/type/interface/enum)
        if cur.type in _ECMASCRIPT_DECLARATION_NAME_NODE_TYPES:
            name = cur.child_by_field_name("name")
            if name is not None and _is_descendant(name, node):
                return True

        # `for (const x of xs)` / `for (let x in xs)` binding.
        if cur.type == "for_in_statement":
            left = cur.child_by_field_name("left")
            if left is not None and _is_descendant(left, node):
                # Only treat as a declaration if preceded by a declaration keyword.
                prev = left.prev_sibling
                if prev is not None and prev.type in ("const", "let", "var"):
                    return True

        cur = cur.parent

    return False


def _is_within_assignment_pattern_right(node) -> bool:
    """Return True if node appears within the `right` field of an assignment pattern."""
    cur = node
    while cur is not None:
        parent = cur.parent
        if parent is None:
            return False
        if parent.type in _ECMASCRIPT_ASSIGNMENT_PATTERN_NODE_TYPES:
            right = parent.child_by_field_name("right")
            if right is not None and _is_descendant(right, node):
                return True
        cur = parent
    return False


def _is_descendant(ancestor, node) -> bool:
    cur = node
    while cur is not None:
        if cur == ancestor:
            return True
        cur = cur.parent
    return False


def _direct_child_under(ancestor, node):
    """Return the direct child of `ancestor` that contains `node`, if any."""
    cur = node
    while cur is not None and cur.parent is not None and cur.parent != ancestor:
        cur = cur.parent
    if cur is not None and cur.parent == ancestor:
        return cur
    return None


def _is_param_binding_occurrence(param_root, node) -> bool:
    """Return True if `node` is part of the parameter binding pattern.

    `param_root` is the direct child of `formal_parameters` that contains `node`.
    """
    if _is_within_assignment_pattern_right(node):
        return False

    # `x` in `(x)` or `...rest` in `(...rest)` are bindings.
    if param_root.type in ("identifier", "rest_pattern"):
        return True

    # `x=Default` binds `x` on the left; right side is an expression.
    if param_root.type == "assignment_pattern":
        left = param_root.child_by_field_name("left")
        if left is not None and _is_descendant(left, node):
            return True
        return False

    # Destructuring patterns (object/array) bind identifiers inside them.
    if param_root.type in ("object_pattern", "array_pattern", "pair_pattern"):
        return True

    return False


def _extract_alias(import_node) -> str | None:
    """Extract alias name from import nodes.

    Handles two styles:
    - Go-style named imports where a ``package_identifier`` child precedes
      the path with no ``as`` keyword (e.g. ``alias "pkg/path"``).
    - ``as``-style aliases (Python ``import X as Y``, PHP ``use Foo as Bar``).

    Returns the alias text or None.
    """
    # Go-style named imports: alias is a package_identifier child.
    for i in range(import_node.child_count):
        child = import_node.children[i]
        if child.type == "package_identifier":
            return _node_text(child)

    # "as"-style aliases (Python, PHP, etc.)
    found_as = False
    for child in _iter_children(import_node):
        text = _node_text(child)
        if text == "as":
            found_as = True
            continue
        # The node immediately after "as" is the alias name.
        if found_as and child.type in ("name", "identifier", "namespace_name"):
            return _node_text(child)
    return None


def _iter_children(node):
    """Recursively yield terminal-ish children relevant to alias extraction.

    Only descends into namespace_use_clause / import_clause nodes (the
    immediate import container) — avoids descending into unrelated subtrees.
    """
    for i in range(node.child_count):
        child = node.children[i]
        # Yield leaf-like nodes (keywords, identifiers).
        if child.child_count == 0:
            yield child
        elif child.type in (
            "namespace_use_clause", "import_clause",
            "namespace_alias", "as_pattern",
        ):
            yield from _iter_children(child)


def _extract_import_name(import_path: str) -> str:
    """Extract the usable name from an import path.

    Examples:
        "fmt" -> "fmt"
        "./utils" -> "utils"
        "crate::module::Foo" -> "Foo"
        "com.example.MyClass" -> "MyClass"
        "MyApp::Model::User" -> "User"
        "Data.List" -> "List"
    """
    candidate = import_path.strip()
    for sep in ("/", "\\"):
        if sep in candidate:
            parts = [p for p in candidate.split(sep) if p]
            if parts:
                candidate = parts[-1]

    for ext in (".go", ".rs", ".rb", ".py", ".js", ".jsx", ".ts",
                ".tsx", ".java", ".kt", ".cs", ".fs", ".ml",
                ".ex", ".erl", ".hs", ".lua", ".zig", ".pm",
                ".sh", ".pl", ".scala", ".swift", ".php",
                ".dart", ".mjs", ".cjs", ".h", ".hh", ".hpp"):
        if candidate.endswith(ext):
            return candidate[:-len(ext)]

    for sep in ("::", "."):
        if sep in candidate:
            parts = [p for p in candidate.split(sep) if p]
            if parts:
                return parts[-1]

    return candidate


__all__ = ["detect_unused_imports"]
