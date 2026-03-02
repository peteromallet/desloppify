"""Direct tests for review context pattern helpers."""

from __future__ import annotations

import desloppify.intelligence.review._context.patterns as patterns_mod


def test_extract_imported_names_handles_from_and_import_forms():
    content = """
from pkg.mod import Foo, Bar as Baz
import one, two as alias
from pkg.other import (
    SkipMe,
)
"""
    names = patterns_mod.extract_imported_names(content)
    assert "Foo" in names
    assert "Bar" in names
    assert "one" in names
    assert "two" in names
    assert "SkipMe" not in names


def test_default_review_module_patterns_flags_key_exports():
    content = """
export default function main() {}
export function helper() {}
def py_func():
    return 1
__all__ = ["py_func"]
"""
    tags = patterns_mod.default_review_module_patterns(content)
    assert "default_export" in tags
    assert "named_export" in tags
    assert "functions" in tags
    assert "explicit_api" in tags


def test_compiled_regexes_match_expected_symbols():
    assert patterns_mod.FUNC_NAME_RE.search("def compute(x):").group(1) == "compute"
    assert patterns_mod.CLASS_NAME_RE.search("class Handler:").group(1) == "Handler"
    assert patterns_mod.ERROR_PATTERNS["throws"].search("raise ValueError('bad')")
    assert patterns_mod.NAME_PREFIX_RE.search("compute_total")
