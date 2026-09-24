"""Syntax facts for conservative Kotlin dependency resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_TYPE_DECLARATIONS = {"class_declaration", "object_declaration", "type_alias"}


def node_text(node) -> str:
    return node.text.decode("utf-8", errors="replace").strip("`")


def qualified_name(node) -> str:
    return ".".join(node_text(child) for child in node.named_children)


def walk(node):
    yield node
    for child in node.named_children:
        yield from walk(child)


def declaration_names(node) -> list[str]:
    if node.type in _TYPE_DECLARATIONS | {"function_declaration", "type_parameter"}:
        names = [
            child
            for child in node.named_children
            if child.type in {"simple_identifier", "type_identifier"}
        ]
        return [node_text(names[0])] if names else []
    if node.type in {"variable_declaration", "parameter", "class_parameter"}:
        return [
            node_text(child)
            for child in node.named_children
            if child.type == "simple_identifier"
        ]
    return []


def top_level_names(node) -> list[str]:
    if node.type == "property_declaration":
        names = []
        for child in node.named_children:
            if child.type == "variable_declaration":
                names.extend(declaration_names(child))
            elif child.type == "multi_variable_declaration":
                for variable in child.named_children:
                    names.extend(declaration_names(variable))
        return names
    return declaration_names(node)


@dataclass
class KotlinFile:
    package: str = ""
    # Qualified import path and optional alias; stars are kept separately.
    imports: list[tuple[str, str]] = field(default_factory=list)
    stars: list[str] = field(default_factory=list)
    declarations: dict[str, bool] = field(default_factory=dict)
    references: set[str] = field(default_factory=set)
    shadowed: set[str] = field(default_factory=set)


def parse_kotlin_file(root: Any) -> KotlinFile:
    facts = KotlinFile()
    for node in root.named_children:
        if node.type == "package_header":
            identifier = next(
                (c for c in node.named_children if c.type == "identifier"), None
            )
            if identifier is not None:
                facts.package = qualified_name(identifier)
        elif node.type == "import_list":
            for header in node.named_children:
                identifier = next(
                    (c for c in header.named_children if c.type == "identifier"), None
                )
                if identifier is None:
                    continue
                path = qualified_name(identifier)
                if any(c.type == "wildcard_import" for c in header.named_children):
                    facts.stars.append(path)
                else:
                    alias = next(
                        (c for c in header.named_children if c.type == "import_alias"),
                        None,
                    )
                    local = (
                        node_text(alias.named_children[0])
                        if alias
                        else path.rsplit(".", 1)[-1]
                    )
                    facts.imports.append((path, local))
                    facts.shadowed.add(local)
        else:
            modifiers = next(
                (c for c in node.named_children if c.type == "modifiers"), None
            )
            private = modifiers is not None and any(
                node_text(c) == "private" for c in modifiers.named_children
            )
            if not private:
                for name in top_level_names(node):
                    facts.declarations[name] = node.type in _TYPE_DECLARATIONS

    # Infer only bare type uses and constructor-shaped calls. A matching local
    # declaration anywhere in this file suppresses inference: false negatives are
    # preferable to crediting a test for an unrelated, shadowed package symbol.
    for top in root.named_children:
        if top.type in {"package_header", "import_list"}:
            continue
        for node in walk(top):
            facts.shadowed.update(declaration_names(node))
            if node.type == "user_type":
                names = [c for c in node.named_children if c.type == "type_identifier"]
                if len(names) == 1:
                    facts.references.add(node_text(names[0]))
            elif node.type == "call_expression" and node.named_children:
                callee = node.named_children[0]
                if callee.type == "simple_identifier":
                    facts.references.add(node_text(callee))
    return facts
