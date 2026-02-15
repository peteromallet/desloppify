"""Tests verifying the review/ package split — all imports work, no circular deps."""

from __future__ import annotations

import importlib
import sys

import pytest


class TestReviewImports:
    """Verify all public names are importable from desloppify.review."""

    def test_all_exports_importable(self):
        """Every name in __all__ is importable."""
        from desloppify import review
        for name in review.__all__:
            assert hasattr(review, name), f"Missing export: {name}"

    def test_key_public_names(self):
        """Key public names are available."""
        from desloppify.review import (
            # dimensions
            HOLISTIC_DIMENSIONS,
            HOLISTIC_DIMENSION_PROMPTS,
            HOLISTIC_REVIEW_SYSTEM_PROMPT,
            DEFAULT_DIMENSIONS,
            DIMENSION_PROMPTS,
            LANG_GUIDANCE,
            REVIEW_SYSTEM_PROMPT,
            # context
            ReviewContext,
            build_review_context,
            build_holistic_context,
            _serialize_context,
            _file_excerpt,
            _extract_imported_names,
            _abs,
            _dep_graph_lookup,
            _importer_count,
            _gather_ai_debt_signals,
            _gather_auth_context,
            _gather_migration_signals,
            _classify_error_strategy,
            # selection
            select_files_for_review,
            hash_file,
            _compute_review_priority,
            _get_file_findings,
            _count_fresh,
            _count_stale,
            LOW_VALUE_NAMES,
            MIN_REVIEW_LOC,
            # prepare
            prepare_review,
            prepare_holistic_review,
            _build_investigation_batches,
            _build_file_requests,
            _HOLISTIC_WORKFLOW,
            _rel_list,
            # import
            import_review_findings,
            import_holistic_findings,
            _store_assessments,
            _extract_findings_and_assessments,
            _update_review_cache,
            _update_holistic_review_cache,
            # remediation
            generate_remediation_plan,
            _empty_plan,
        )


class TestSubmoduleImports:
    """Each submodule can be imported independently."""

    @pytest.mark.parametrize("module", [
        "desloppify.review.dimensions",
        "desloppify.review.context",
        "desloppify.review.selection",
        "desloppify.review.prepare",
        "desloppify.review.import_findings",
        "desloppify.review.remediation",
    ])
    def test_submodule_importable(self, module):
        mod = importlib.import_module(module)
        assert mod is not None

    def test_no_circular_import(self):
        """Fresh import of desloppify.review succeeds without circular import errors."""
        # Remove cached modules to force fresh import
        to_remove = [k for k in sys.modules if k.startswith("desloppify.review")]
        removed = {}
        for k in to_remove:
            removed[k] = sys.modules.pop(k)
        try:
            import desloppify.review
            # If we get here, no circular import
            assert hasattr(desloppify.review, "__all__")
        finally:
            # Restore removed modules
            sys.modules.update(removed)
