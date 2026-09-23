"""Implicit Kotlin import references from delegates, indexing and DSL calls."""

from __future__ import annotations


def collect_implicit_references(root) -> set[str]:
    """Collect operator names that syntax may invoke without an identifier.

    Without receiver types we cannot resolve these calls to an imported extension
    or a member. Retain potentially used imports rather than recommend removing
    them. Inspect nodes, not source text, so comments and strings do not count.
    """
    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "import_list":
            continue
        if node.type == "property_delegate":
            names.update(("getValue", "provideDelegate"))
            if any(
                child.type == "binding_pattern_kind" and child.text == b"var"
                for child in node.parent.children
            ):
                names.add("setValue")
        elif node.type == "indexing_suffix":
            parent = node.parent
            assignment = parent.parent
            if parent.type == "directly_assignable_expression":
                names.add("set")
                if not any(child.type == "=" for child in assignment.children):
                    names.add("get")
            else:
                names.add("get")
                if assignment.type in ("prefix_expression", "postfix_expression"):
                    names.add("set")
        elif node.type == "call_expression":
            names.add("invoke")
        elif node.type == "assignment" and any(
            child.type == "=" for child in node.children
        ):
            # Kotlin's assignment compiler plugin (used by Gradle's Kotlin DSL)
            # resolves `property = value` to an imported `assign` extension.
            names.add("assign")
        stack.extend(node.named_children)
    return names
