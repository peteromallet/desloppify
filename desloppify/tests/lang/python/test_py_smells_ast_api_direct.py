"""Direct API surface tests for Python AST smell package exports."""

from __future__ import annotations

import pytest

import desloppify.languages.python.detectors.smells_ast as smells_ast


def test_smells_ast_public_api_is_narrow():
    assert sorted(smells_ast.__all__) == [
        "collect_module_constants",
        "detect_ast_smells",
        "detect_duplicate_constants",
        "detect_star_import_no_all",
        "detect_vestigial_parameter",
    ]


def test_smells_ast_legacy_exports_are_removed():
    assert not hasattr(smells_ast, "_detect_dead_functions")
    with pytest.raises(AttributeError):
        _ = smells_ast._detect_dead_functions
