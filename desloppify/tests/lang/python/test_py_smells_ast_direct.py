"""Direct tests for Python AST smell helpers."""

from __future__ import annotations

import ast

import desloppify.languages.python.detectors.smells_ast._node_detectors as node_detectors


def test_detect_dead_function_flags_pass_only_function():
    source = """
def noop():
    pass
"""
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    smell_counts = {"dead_function": []}

    node_detectors._detect_dead_functions("file.py", node, smell_counts)

    assert len(smell_counts["dead_function"]) == 1
    assert smell_counts["dead_function"][0]["file"] == "file.py"
    assert "noop()" in smell_counts["dead_function"][0]["content"]


def test_detect_monster_function_ignores_small_functions():
    source = """
def small():
    return 1
"""
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    smell_counts = {"monster_function": []}

    node_detectors._detect_monster_functions("file.py", node, smell_counts)

    assert smell_counts["monster_function"] == []
