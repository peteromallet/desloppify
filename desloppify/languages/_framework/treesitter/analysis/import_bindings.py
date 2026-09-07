"""Binding extraction for languages whose imports rename freely.

Path-derived import names hold for languages where the statement dictates the
binding (Python's ``import foo``, Go's import block). They break for languages
where an import is an ordinary expression assigned to an ordinary variable:
``local TeamClass = require("Tools/Team")`` binds ``TeamClass``, not ``Team``,
and ``{ require("Entities/awp"), ... }`` binds nothing at all.

A spec supplies one of these hooks to have the unused-import detector work from
the binding it can see rather than from the module path.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class ImportBinding(NamedTuple):
    """The name an import binds, and the statement that binds it.

    ``statement`` is the range the detector must exclude when searching for
    references. The captured import node covers only the call expression, so
    excluding it alone would leave the binding's own declaration in the
    searched text, where it would match itself and never look unused.
    """

    name: str
    statement: Any


def _named_children(node: Any) -> list[Any]:
    """Return a node's named children, skipping punctuation tokens."""
    return [child for child in node.children if child.is_named]


def _identifier_text(node: Any) -> str | None:
    """Return the text of an identifier node, or None for any other node."""
    if node is None or node.type != "identifier":
        return None
    raw = node.text
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return text or None


def luau_import_binding(import_node: Any) -> ImportBinding | None:
    """Return the local name a Luau/Lua ``require`` call is bound to.

    Returns None when the call is not assigned to a plain identifier — an
    inline element of a table, an argument to another call, a field
    assignment. Such a require has no name that could go unreferenced, so the
    caller skips it rather than inventing one from the module path.
    """
    expression_list = import_node.parent
    if expression_list is None or expression_list.type != "expression_list":
        return None

    assignment = expression_list.parent
    if assignment is None or assignment.type != "assignment_statement":
        return None

    targets = next(
        (child for child in assignment.children if child.type == "variable_list"),
        None,
    )
    if targets is None:
        return None

    # `local a, b = require(x), require(y)` pairs targets with values by
    # position, so the binding for this call is the target at its own index.
    values = _named_children(expression_list)
    index = next(
        (i for i, value in enumerate(values) if value.id == import_node.id), None
    )
    if index is None:
        return None

    names = [child for child in _named_children(targets) if child.type == "identifier"]
    if index >= len(names):
        return None

    name = _identifier_text(names[index])
    if name is None:
        return None

    # A leading underscore is the Lua convention for a binding kept on purpose
    # and knowingly not referenced — selene's unused_variable rule reads it the
    # same way — so reporting one would contradict a deliberate annotation.
    if name.startswith("_"):
        return None

    # `local x = require(...)` wraps the assignment in a variable_declaration;
    # a plain reassignment does not. Exclude the outermost of the two.
    statement = assignment
    if (
        assignment.parent is not None
        and assignment.parent.type == "variable_declaration"
    ):
        statement = assignment.parent

    return ImportBinding(name, statement)


__all__ = ["ImportBinding", "luau_import_binding"]
