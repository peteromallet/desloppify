"""Coverage enforcement for explicitly scoped trusted review runs."""

from __future__ import annotations

import pytest

from desloppify.app.commands.review.batch.execution_results import enforce_import_coverage
from desloppify.app.commands.review.batch.scope import (
    print_import_dimension_coverage_notice,
)
from desloppify.base.exception_sets import CommandError


def _coverage(assessed: list[str], selected: list[str], *, allow_partial=False):
    missing = print_import_dimension_coverage_notice(
        assessed_dims=assessed,
        scored_dims=["naming_quality", "logic_clarity", "type_safety"],
        scan_path="src",
        colorize_fn=lambda text, _tone: text,
    )
    enforce_import_coverage(
        missing_after_import=missing,
        packet_dimensions=selected,
        allow_partial=allow_partial,
        scan_path="src",
        colorize_fn=lambda text, _tone: text,
    )


def test_complete_selected_subset_imports_without_partial_override(capsys):
    _coverage(["naming_quality", "logic_clarity"], ["naming_quality", "logic_clarity"])
    output = capsys.readouterr()
    assert "Still missing: type_safety" in output.out
    assert "Coverage override" not in output.out
    assert output.err == ""


def test_missing_selected_dimension_is_blocked_without_requiring_unselected_ones(capsys):
    with pytest.raises(CommandError, match="incomplete selected-dimension coverage"):
        _coverage(["naming_quality"], ["naming_quality", "logic_clarity"])
    output = capsys.readouterr()
    assert "Missing dimensions: logic_clarity" in output.err
    assert "--dimensions logic_clarity`" in output.err
    assert "type_safety" not in output.err


def test_full_scope_still_requires_all_assessments():
    with pytest.raises(CommandError, match="incomplete selected-dimension coverage"):
        _coverage(["naming_quality", "logic_clarity"], ["naming_quality", "logic_clarity", "type_safety"])


def test_partial_override_remains_available_for_a_missing_selected_dimension(capsys):
    _coverage(["naming_quality"], ["naming_quality", "logic_clarity"], allow_partial=True)
    output = capsys.readouterr()
    assert "Coverage override" in output.out
    assert output.err == ""


def test_complete_full_scope_imports_without_warnings(capsys):
    dimensions = ["naming_quality", "logic_clarity", "type_safety"]
    _coverage(dimensions, dimensions)
    output = capsys.readouterr()
    assert output.out == output.err == ""
