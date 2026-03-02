"""Direct tests for review context dataclasses."""

from __future__ import annotations

import pytest

from desloppify.intelligence.review._context.models import (
    HolisticContext,
    ReviewContextSchemaError,
    ReviewContext,
)


def test_review_context_defaults_are_isolated():
    first = ReviewContext()
    second = ReviewContext()

    first.naming_vocabulary["snake_case"] = 1

    assert "snake_case" in first.naming_vocabulary
    assert "snake_case" not in second.naming_vocabulary


def test_holistic_context_from_raw_rejects_non_dict_section_values():
    with pytest.raises(ReviewContextSchemaError) as exc:
        HolisticContext.from_raw(
            {
                "architecture": {"layers": 3},
                "errors": "not-a-dict",
                "authorization": {"strategy": "rbac"},
            }
        )
    assert "errors" in str(exc.value)


def test_holistic_context_to_dict_emits_stable_optional_sections():
    ctx = HolisticContext.from_raw({"architecture": {"modules": 5}})
    dumped = ctx.to_dict()

    assert dumped["architecture"] == {"modules": 5}
    assert dumped["authorization"] == {}
    assert dumped["ai_debt_signals"] == {}
    assert dumped["migration_signals"] == {}
