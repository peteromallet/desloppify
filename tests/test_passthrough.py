"""Tests for desloppify.detectors.passthrough — tier classification and param classification."""

import re

from desloppify.detectors.passthrough import classify_passthrough_tier, classify_params


# ── classify_passthrough_tier ────────────────────────────────


class TestClassifyPassthroughTier:
    """Tests for classify_passthrough_tier."""

    def test_very_high_count_returns_tier4(self):
        """20+ passthrough params always returns T4/high."""
        result = classify_passthrough_tier(20, 0.5)
        assert result == (4, "high")

    def test_very_high_ratio_returns_tier4(self):
        """80%+ ratio always returns T4/high."""
        result = classify_passthrough_tier(5, 0.8)
        assert result == (4, "high")

    def test_high_count_and_ratio_returns_tier3_high(self):
        """8+ count with 70%+ ratio returns T3/high."""
        result = classify_passthrough_tier(8, 0.7)
        assert result == (3, "high")

    def test_high_count_moderate_ratio_returns_tier3_medium(self):
        """8+ count with 50-70% ratio returns T3/medium."""
        result = classify_passthrough_tier(8, 0.5)
        assert result == (3, "medium")

    def test_spread_with_sufficient_count_returns_tier3(self):
        """has_spread=True with 4+ count returns T3/medium."""
        result = classify_passthrough_tier(4, 0.3, has_spread=True)
        assert result == (3, "medium")

    def test_spread_insufficient_count_returns_none(self):
        """has_spread=True but <4 count returns None."""
        result = classify_passthrough_tier(3, 0.3, has_spread=True)
        assert result is None

    def test_below_all_thresholds_returns_none(self):
        """Below all thresholds returns None."""
        result = classify_passthrough_tier(3, 0.3)
        assert result is None

    def test_zero_returns_none(self):
        """Zero passthrough count returns None."""
        result = classify_passthrough_tier(0, 0.0)
        assert result is None

    def test_boundary_count_20(self):
        """Exactly 20 hits the T4 branch."""
        result = classify_passthrough_tier(20, 0.0)
        assert result is not None
        assert result[0] == 4

    def test_boundary_ratio_0_8(self):
        """Exactly 0.8 ratio hits the T4 branch."""
        result = classify_passthrough_tier(1, 0.8)
        assert result == (4, "high")

    def test_boundary_count_8_ratio_0_5(self):
        """Exactly 8 count and 0.5 ratio hits T3."""
        result = classify_passthrough_tier(8, 0.5)
        assert result is not None
        assert result[0] == 3

    def test_count_7_ratio_0_5_returns_none(self):
        """7 count with 0.5 ratio is below the 8-count threshold."""
        result = classify_passthrough_tier(7, 0.5)
        assert result is None

    def test_count_8_ratio_0_49_returns_none(self):
        """8 count with <0.5 ratio falls through to None."""
        result = classify_passthrough_tier(8, 0.49)
        assert result is None


# ── classify_params ─────────────────────────────────────────


def _simple_passthrough_pattern(name):
    """Pattern: param appears in fn_call(name) or obj.name context."""
    return rf"\b\w+\({re.escape(name)}\)|\.\s*{re.escape(name)}\b"


class TestClassifyParams:
    """Tests for classify_params."""

    def test_all_passthrough(self):
        """All params used only in passthrough contexts."""
        body = "return doSomething(alpha)\nreturn doOther(beta)"
        pt, direct = classify_params(
            ["alpha", "beta"], body, _simple_passthrough_pattern,
        )
        assert pt == ["alpha", "beta"]
        assert direct == []

    def test_all_direct(self):
        """Params used in non-passthrough contexts are classified as direct."""
        body = "x = alpha + 1\ny = beta * 2"
        pt, direct = classify_params(
            ["alpha", "beta"], body, _simple_passthrough_pattern,
        )
        assert pt == []
        assert direct == ["alpha", "beta"]

    def test_mixed_params(self):
        """Mix of passthrough and direct-use params."""
        body = "return doSomething(alpha)\nx = beta + 1"
        pt, direct = classify_params(
            ["alpha", "beta"], body, _simple_passthrough_pattern,
        )
        assert pt == ["alpha"]
        assert direct == ["beta"]

    def test_unused_param_counted_as_direct(self):
        """Unused params (zero occurrences) are classified as direct."""
        body = "return 42"
        pt, direct = classify_params(
            ["unused_param"], body, _simple_passthrough_pattern,
        )
        assert pt == []
        assert direct == ["unused_param"]

    def test_empty_params(self):
        """Empty param list returns empty results."""
        pt, direct = classify_params([], "some body", _simple_passthrough_pattern)
        assert pt == []
        assert direct == []

    def test_occurrences_per_match_default(self):
        """Default occurrences_per_match=2: each pattern match accounts for 2 word-boundary hits."""
        # "fn(x)" contains 1 passthrough match and 1 total \bx\b occurrence
        # With occurrences_per_match=2, 1*2 >= 1, so it's passthrough
        body = "fn(x)"
        pt, direct = classify_params(
            ["x"], body, lambda name: rf"\b\w+\({re.escape(name)}\)",
            occurrences_per_match=2,
        )
        assert pt == ["x"]

    def test_occurrences_per_match_1(self):
        """With occurrences_per_match=1, need at least as many pattern matches as total occurrences."""
        # "fn(x) + x" has 2 total \bx\b but only 1 passthrough match
        # 1*1 = 1 < 2, so direct
        body = "fn(x) + x"
        pt, direct = classify_params(
            ["x"], body, lambda name: rf"\b\w+\({re.escape(name)}\)",
            occurrences_per_match=1,
        )
        assert pt == []
        assert direct == ["x"]

    def test_param_appears_both_passthrough_and_direct(self):
        """Param with more total occurrences than passthrough matches is direct."""
        # "fn(data)" gives 1 passthrough match * 2 = 2 occurrences
        # but "data" appears 3 times total (fn(data), data + 1, data * 2)
        body = "fn(data)\nresult = data + 1\nother = data * 2"
        pt, direct = classify_params(
            ["data"], body, lambda name: rf"\b\w+\({re.escape(name)}\)",
            occurrences_per_match=2,
        )
        assert pt == []
        assert direct == ["data"]

    def test_word_boundary_matching(self):
        """Params are matched with word boundaries, not substrings."""
        # "x" should not match inside "extra" or "max"
        body = "extra = max(something)\nreturn fn(x)"
        pt, direct = classify_params(
            ["x"], body, lambda name: rf"\b\w+\({re.escape(name)}\)",
        )
        # "x" total occurrences = only the standalone \bx\b matches
        # fn(x) is 1 passthrough match, 1*2 >= count of standalone x
        assert pt == ["x"]
