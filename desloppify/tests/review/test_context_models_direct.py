"""Direct tests for review context dataclasses."""

from __future__ import annotations

from desloppify.intelligence.review.context_internal.models import (
    HolisticContext,
    ReviewContext,
)


def test_review_context_defaults_are_isolated():
    first = ReviewContext()
    second = ReviewContext()

    first.naming_vocabulary["snake_case"] = 1

    assert "snake_case" in first.naming_vocabulary
    assert "snake_case" not in second.naming_vocabulary


def test_holistic_context_from_raw_coerces_non_dict_values():
    ctx = HolisticContext.from_raw(
        {
            "architecture": {"layers": 3},
            "errors": "not-a-dict",
            "authorization": {"strategy": "rbac"},
        }
    )

    assert ctx.architecture == {"layers": 3}
    assert ctx.errors == {}
    assert ctx.authorization == {"strategy": "rbac"}


def test_holistic_context_to_dict_omits_empty_optional_sections():
    ctx = HolisticContext.from_raw({"architecture": {"modules": 5}})
    dumped = ctx.to_dict()

    assert dumped["architecture"] == {"modules": 5}
    assert "authorization" not in dumped
    assert "ai_debt_signals" not in dumped
    assert "migration_signals" not in dumped
