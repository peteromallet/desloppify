"""Native PHP class imports and references without guessed file targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

_CLASS_DECLARATIONS = frozenset({
    "class_declaration", "interface_declaration", "trait_declaration", "enum_declaration",
})
_CLASS_NAMES = frozenset({"name", "qualified_name", "relative_name"})
_DIRECT_NAME_CONTEXTS = frozenset({
    "object_creation_expression", "named_type", "base_clause", "class_interface_clause",
    "use_declaration", "attribute",
})


@dataclass
class PhpClassSymbols:
    declared: set[str] = field(default_factory=set)
    referenced: set[str] = field(default_factory=set)


def _text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _class_name(name: str, namespace: str, aliases: dict[str, str]) -> str | None:
    if name.lower() in {"self", "static", "parent"}:
        return None
    if name.startswith("\\"):
        return name.lstrip("\\")
    if name.lower().startswith("namespace\\"):
        name = name[len("namespace\\"):]
        return f"{namespace}\\{name}" if namespace else name
    first, separator, rest = name.partition("\\")
    if first.lower() in aliases:
        imported = aliases[first.lower()]
        return f"{imported}\\{rest}" if separator else imported
    return f"{namespace}\\{name}" if namespace else name


def _class_imports(node: Node) -> list[tuple[str, str]]:
    """Class/namespace aliases have a separate table from functions/constants."""
    if node.child_by_field_name("type"):
        return []
    group = node.child_by_field_name("body")
    prefix = next((child for child in node.named_children if child.type == "namespace_name"), None)
    clauses = group.named_children if group else node.named_children
    imports: list[tuple[str, str]] = []
    for clause in clauses:
        if clause.type != "namespace_use_clause" or clause.child_by_field_name("type"):
            continue
        path = next((child for child in clause.named_children if child.type in _CLASS_NAMES), None)
        if not path:
            continue
        imported = _text(path).lstrip("\\")
        if prefix:
            imported = f"{_text(prefix)}\\{imported}"
        alias = clause.child_by_field_name("alias")
        alias_name = _text(alias) if alias else imported.rsplit("\\", 1)[-1]
        imports.append((alias_name.lower(), imported))
    return imports


def _reference_nodes(node: Node) -> list[Node]:
    if node.type in _DIRECT_NAME_CONTEXTS:
        return [child for child in node.named_children if child.type in _CLASS_NAMES]
    if node.type in {"scoped_call_expression", "scoped_property_access_expression"}:
        scope = node.child_by_field_name("scope")
        return [scope] if scope and scope.type in _CLASS_NAMES else []
    if node.type == "class_constant_access_expression":
        scope = node.named_children[0] if node.named_children else None
        return [scope] if scope and scope.type in _CLASS_NAMES else []
    if node.type == "binary_expression":
        operator = node.child_by_field_name("operator")
        right = node.child_by_field_name("right")
        if operator and _text(operator) == "instanceof" and right and right.type in _CLASS_NAMES:
            return [right]
    return []


def collect_php_class_symbols(root: Node) -> PhpClassSymbols:
    """Collect declared and referenced class names in their namespace scopes."""
    symbols = PhpClassSymbols()

    def walk(nodes: list[Node], namespace: str, aliases: dict[str, str]) -> None:
        for node in nodes:
            if node.type == "namespace_definition":
                name = node.child_by_field_name("name")
                next_namespace = _text(name) if name else ""
                body = node.child_by_field_name("body")
                if body:
                    walk(body.named_children, next_namespace, {})
                else:
                    namespace = next_namespace
                    aliases = {}
                continue
            if node.type == "namespace_use_declaration":
                for alias, imported in _class_imports(node):
                    aliases[alias] = imported
                    symbols.referenced.add(imported)
                continue
            if node.type in _CLASS_DECLARATIONS:
                name = node.child_by_field_name("name")
                if name:
                    declared = _text(name)
                    symbols.declared.add(f"{namespace}\\{declared}" if namespace else declared)
            for child in _reference_nodes(node):
                name = _class_name(_text(child), namespace, aliases)
                if name:
                    symbols.referenced.add(name)
            walk(node.named_children, namespace, aliases)

    walk(root.named_children, "", {})
    return symbols


def add_php_class_reference_edges(
    graph: dict[str, dict[str, Any]],
    symbols_by_file: dict[str, PhpClassSymbols],
) -> None:
    """Link exact scanned declarations, omitting ambiguous and self references."""
    declared: dict[str, set[str]] = {}
    for filepath, symbols in symbols_by_file.items():
        for name in symbols.declared:
            declared.setdefault(name.lower(), set()).add(filepath)
    for filepath, symbols in symbols_by_file.items():
        for name in symbols.referenced:
            candidates = declared.get(name.lower(), set())
            if len(candidates) != 1:
                continue
            dependency = next(iter(candidates))
            if dependency == filepath:
                continue
            graph[filepath]["imports"].add(dependency)
            graph[dependency]["importers"].add(filepath)
