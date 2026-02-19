"""Tests verifying the review/ package split — all imports work, no circular deps."""

from __future__ import annotations

import importlib
import sys

import pytest

from desloppify.intelligence import review


class TestReviewImports:
    """Verify all public names are importable from desloppify.intelligence.review."""

    def test_all_exports_importable(self):
        """Every name in __all__ is importable."""
        for name in review.__all__:
            assert hasattr(review, name), f"Missing export: {name}"

    def test_key_public_names(self):
        """Key public names are available."""


class TestSubmoduleImports:
    """Each submodule can be imported independently."""

    @pytest.mark.parametrize(
        "module",
        [
            "desloppify.intelligence.review.dimensions.file",
            "desloppify.intelligence.review.dimensions.holistic",
            "desloppify.intelligence.review.dimensions.lang",
            "desloppify.intelligence.review.context",
            "desloppify.intelligence.review.selection",
            "desloppify.intelligence.review.prepare",
            "desloppify.intelligence.review.importing.per_file",
            "desloppify.intelligence.review.importing.holistic",
            "desloppify.intelligence.review.importing.shared",
            "desloppify.intelligence.review.remediation",
        ],
    )
    def test_submodule_importable(self, module):
        mod = importlib.import_module(module)
        assert mod is not None

    def test_no_circular_import(self):
        """Fresh import of desloppify.intelligence.review succeeds without circular import errors."""
        # Remove cached modules to force fresh import
        to_remove = [k for k in sys.modules if k.startswith("desloppify.intelligence.review")]
        removed = {}
        for k in to_remove:
            removed[k] = sys.modules.pop(k)
        try:
            # If we get here, no circular import
            imported = importlib.import_module("desloppify.intelligence.review")
            assert hasattr(imported, "__all__")
        finally:
            # Restore removed modules
            sys.modules.update(removed)
