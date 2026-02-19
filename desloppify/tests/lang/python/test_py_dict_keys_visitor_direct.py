"""Direct tests for DictKeyVisitor internals."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.dict_keys_visitor import DictKeyVisitor


def test_dict_key_visitor_captures_dict_literals_for_schema_drift():
    source = """
def build_payload():
    return {"a": 1, "b": 2, "c": 3}
"""
    visitor = DictKeyVisitor("sample.py")
    visitor.visit(ast.parse(source))

    assert len(visitor._dict_literals) == 1
    literal = visitor._dict_literals[0]
    assert literal["file"] == "sample.py"
    assert literal["keys"] == frozenset({"a", "b", "c"})


def test_dict_key_visitor_handles_basic_writes_and_reads_without_crashing():
    source = """
def update():
    state = {}
    state["x"] = 1
    return state.get("x")
"""
    visitor = DictKeyVisitor("sample.py")
    visitor.visit(ast.parse(source))

    assert isinstance(visitor._findings, list)
    assert isinstance(visitor._dict_literals, list)
