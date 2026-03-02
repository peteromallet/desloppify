"""Tests for review packet policy helpers (shared config redaction + file limit)."""

from __future__ import annotations

from desloppify.app.commands.review.packet_policy import (
    DEFAULT_REVIEW_BATCH_MAX_FILES,
    coerce_review_batch_file_limit,
    redacted_review_config,
)


# ── redacted_review_config ──────────────────────────────────


def test_redacted_strips_target_strict_score():
    config = {"target_strict_score": 90, "review_batch_max_files": 80, "other": "val"}
    result = redacted_review_config(config)
    assert "target_strict_score" not in result
    assert result == {"review_batch_max_files": 80, "other": "val"}


def test_redacted_returns_empty_for_none():
    assert redacted_review_config(None) == {}


def test_redacted_returns_empty_for_non_dict():
    assert redacted_review_config("not a dict") == {}
    assert redacted_review_config(42) == {}


def test_redacted_passes_through_config_without_target():
    config = {"review_batch_max_files": 100, "x": "y"}
    assert redacted_review_config(config) == config


# ── coerce_review_batch_file_limit ──────────────────────────


def test_coerce_returns_configured_value():
    assert coerce_review_batch_file_limit({"review_batch_max_files": 50}) == 50


def test_coerce_returns_default_when_missing():
    assert coerce_review_batch_file_limit({}) == DEFAULT_REVIEW_BATCH_MAX_FILES
    assert coerce_review_batch_file_limit(None) == DEFAULT_REVIEW_BATCH_MAX_FILES


def test_coerce_returns_none_for_zero_or_negative():
    assert coerce_review_batch_file_limit({"review_batch_max_files": 0}) is None
    assert coerce_review_batch_file_limit({"review_batch_max_files": -1}) is None


def test_coerce_returns_default_for_invalid_type():
    assert (
        coerce_review_batch_file_limit({"review_batch_max_files": "not_a_number"})
        == DEFAULT_REVIEW_BATCH_MAX_FILES
    )


def test_coerce_converts_string_int():
    assert coerce_review_batch_file_limit({"review_batch_max_files": "120"}) == 120
