"""Direct tests for TypeScript review helpers."""

from __future__ import annotations

from desloppify.languages.typescript import review as ts_review


def test_typescript_review_guidance_has_expected_sections():
    assert "patterns" in ts_review.REVIEW_GUIDANCE
    assert "auth" in ts_review.REVIEW_GUIDANCE
    assert isinstance(ts_review.REVIEW_GUIDANCE["patterns"], list)
    assert isinstance(ts_review.REVIEW_GUIDANCE["auth"], list)


def test_low_value_pattern_matches_dts_and_types_files():
    assert ts_review.LOW_VALUE_PATTERN.search("src/types.ts")
    assert ts_review.LOW_VALUE_PATTERN.search("src/api.d.ts")
    assert not ts_review.LOW_VALUE_PATTERN.search("src/feature/service.ts")


def test_module_patterns_detects_default_and_named_exports():
    content = "export default function A() {}\nexport const B = 1\n"
    patterns = ts_review.module_patterns(content)
    assert "default_export" in patterns
    assert "named_export" in patterns
