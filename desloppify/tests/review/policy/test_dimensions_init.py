"""Tests for review dimension predicates and normalization (dimensions/__init__.py)."""

from __future__ import annotations

from desloppify.intelligence.review.dimensions import (
    DIMENSION_PROMPTS,
    DIMENSIONS,
    is_custom_dimension,
    is_known_dimension,
    normalize_dimension_name,
)

# ---------------------------------------------------------------------------
# normalize_dimension_name
# ---------------------------------------------------------------------------


def test_normalize_simple_snake_case():
    assert normalize_dimension_name("naming_quality") == "naming_quality"


def test_normalize_strips_whitespace():
    assert normalize_dimension_name("  naming_quality  ") == "naming_quality"


def test_normalize_lowercases():
    assert normalize_dimension_name("Naming_Quality") == "naming_quality"
    assert normalize_dimension_name("NAMING_QUALITY") == "naming_quality"


def test_normalize_replaces_hyphens_with_underscores():
    assert normalize_dimension_name("naming-quality") == "naming_quality"


def test_normalize_collapses_whitespace_to_underscores():
    assert normalize_dimension_name("naming  quality") == "naming_quality"
    assert normalize_dimension_name("naming\tquality") == "naming_quality"


def test_normalize_combined_transformations():
    assert normalize_dimension_name("  Custom-Foo  Bar ") == "custom_foo_bar"


def test_normalize_empty_string():
    assert normalize_dimension_name("") == ""


def test_normalize_whitespace_only():
    assert normalize_dimension_name("   ") == ""


def test_normalize_idempotent():
    """Normalizing an already-normalized name returns the same value."""
    for name in ["naming_quality", "custom_foo", "cross_module_architecture"]:
        assert normalize_dimension_name(normalize_dimension_name(name)) == name


# ---------------------------------------------------------------------------
# is_custom_dimension
# ---------------------------------------------------------------------------


def test_is_custom_dimension_with_prefix():
    assert is_custom_dimension("custom_foo") is True
    assert is_custom_dimension("custom_") is True


def test_is_custom_dimension_without_prefix():
    assert is_custom_dimension("naming_quality") is False
    assert is_custom_dimension("foo_custom") is False


def test_is_custom_dimension_normalizes_input():
    assert is_custom_dimension("Custom-Foo") is True
    assert is_custom_dimension("CUSTOM_BAR") is True


def test_is_custom_dimension_empty():
    assert is_custom_dimension("") is False


# ---------------------------------------------------------------------------
# is_known_dimension
# ---------------------------------------------------------------------------


def test_is_known_dimension_recognizes_known():
    assert is_known_dimension("naming_quality") is True
    assert is_known_dimension("logic_clarity") is True
    assert is_known_dimension("cross_module_architecture") is True


def test_is_known_dimension_rejects_unknown():
    assert is_known_dimension("totally_made_up") is False
    assert is_known_dimension("custom_foo") is False


def test_is_known_dimension_normalizes_input():
    assert is_known_dimension("Naming-Quality") is True
    assert is_known_dimension("LOGIC_CLARITY") is True
    assert is_known_dimension("  naming_quality  ") is True


def test_is_known_dimension_empty():
    assert is_known_dimension("") is False


def test_is_known_dimension_whitespace():
    assert is_known_dimension("   ") is False


# ---------------------------------------------------------------------------
# _KNOWN_DIMENSIONS invariants
# ---------------------------------------------------------------------------


def test_all_dimension_prompts_are_known():
    """Every key in DIMENSION_PROMPTS should be a known dimension."""
    for name in DIMENSION_PROMPTS:
        canonical = normalize_dimension_name(name)
        assert is_known_dimension(canonical), (
            f"DIMENSION_PROMPTS key {name!r} is not recognized as known"
        )


def test_all_default_dimensions_are_known():
    """Every entry in DIMENSIONS should be a known dimension."""
    for name in DIMENSIONS:
        canonical = normalize_dimension_name(name)
        assert is_known_dimension(canonical), (
            f"DIMENSIONS entry {name!r} is not recognized as known"
        )


def test_dimension_prompts_is_nonempty():
    """Sanity check: there should be at least a few dimension prompts."""
    assert len(DIMENSION_PROMPTS) >= 5


def test_dimensions_is_nonempty():
    """Sanity check: there should be at least a few default dimensions."""
    assert len(DIMENSIONS) >= 5


def test_known_dimension_not_custom():
    """No known dimension should have the custom_ prefix."""
    for name in DIMENSION_PROMPTS:
        assert not is_custom_dimension(name), (
            f"Known dimension {name!r} has custom_ prefix"
        )
