"""Direct tests for Python review guidance helpers."""

from __future__ import annotations

import desloppify.languages.python.review as py_review_mod


def test_python_review_module_patterns():
    content = """
__all__ = ["run"]

def run():
    return 1
"""
    patterns = py_review_mod.module_patterns(content)
    assert "functions" in patterns
    assert "explicit_api" in patterns


def test_python_review_api_surface_is_empty_dict():
    surface = py_review_mod.api_surface({"a.py": "def run():\n    return 1\n"})
    assert isinstance(surface, dict)
    assert surface == {}
