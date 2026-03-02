"""Tests for review dimension policy enforcement (policy.py)."""

from __future__ import annotations

import pytest

from desloppify.intelligence.review.policy import (
    DimensionPolicy,
    _normalized_custom_allowlist,
    append_custom_dimensions,
    build_dimension_policy,
    filter_assessments_for_scoring,
    is_allowed_dimension,
    normalize_assessment_inputs,
    normalize_dimension_inputs,
)

# ---------------------------------------------------------------------------
# _normalized_custom_allowlist
# ---------------------------------------------------------------------------


def test_normalized_custom_allowlist_returns_empty_for_none():
    assert _normalized_custom_allowlist(None) == set()


def test_normalized_custom_allowlist_returns_empty_for_empty_list():
    assert _normalized_custom_allowlist([]) == set()


def test_normalized_custom_allowlist_keeps_only_custom_prefixed():
    result = _normalized_custom_allowlist(
        ["custom_foo", "naming_quality", "custom_bar"]
    )
    assert result == {"custom_foo", "custom_bar"}


def test_normalized_custom_allowlist_normalizes_names():
    result = _normalized_custom_allowlist(["Custom-Foo Bar", "CUSTOM_BAZ"])
    assert result == {"custom_foo_bar", "custom_baz"}


def test_normalized_custom_allowlist_skips_empty_after_normalize():
    result = _normalized_custom_allowlist(["", "   ", "custom_ok"])
    assert result == {"custom_ok"}


# ---------------------------------------------------------------------------
# build_dimension_policy
# ---------------------------------------------------------------------------


def test_build_dimension_policy_defaults():
    policy = build_dimension_policy()
    assert isinstance(policy, DimensionPolicy)
    assert policy.allow_custom is False
    assert isinstance(policy.known, frozenset)
    assert len(policy.known) > 0
    assert "naming_quality" in policy.known
    assert policy.allowed_custom == frozenset()


def test_build_dimension_policy_allow_custom_from_cli():
    policy = build_dimension_policy(allow_custom_dimensions=True)
    assert policy.allow_custom is True


def test_build_dimension_policy_allow_custom_from_config():
    policy = build_dimension_policy(
        config={"review_allow_custom_dimensions": True}
    )
    assert policy.allow_custom is True


def test_build_dimension_policy_merges_custom_from_config_and_state():
    policy = build_dimension_policy(
        config={"review_custom_dimensions": ["custom_from_config"]},
        state={"custom_review_dimensions": ["custom_from_state"]},
    )
    assert "custom_from_config" in policy.allowed_custom
    assert "custom_from_state" in policy.allowed_custom


def test_build_dimension_policy_non_dict_config_and_state():
    policy = build_dimension_policy(config="bad", state=42)
    assert isinstance(policy, DimensionPolicy)
    assert policy.allowed_custom == frozenset()


def test_build_dimension_policy_allowed_subjective_is_union():
    policy = build_dimension_policy(
        state={"custom_review_dimensions": ["custom_x"]},
    )
    assert policy.allowed_subjective == policy.known | policy.allowed_custom
    assert "custom_x" in policy.allowed_subjective
    assert "naming_quality" in policy.allowed_subjective


# ---------------------------------------------------------------------------
# is_allowed_dimension
# ---------------------------------------------------------------------------


def test_is_allowed_dimension_known_is_always_allowed():
    policy = build_dimension_policy()
    assert is_allowed_dimension("naming_quality", policy=policy) is True
    assert is_allowed_dimension("logic_clarity", policy=policy) is True


def test_is_allowed_dimension_empty_name():
    policy = build_dimension_policy()
    assert is_allowed_dimension("", policy=policy) is False
    assert is_allowed_dimension("   ", policy=policy) is False


def test_is_allowed_dimension_custom_in_allowlist():
    policy = build_dimension_policy(
        state={"custom_review_dimensions": ["custom_special"]},
    )
    assert is_allowed_dimension("custom_special", policy=policy) is True


def test_is_allowed_dimension_custom_not_in_allowlist_without_allow_custom():
    policy = build_dimension_policy()
    assert is_allowed_dimension("custom_unknown", policy=policy) is False


def test_is_allowed_dimension_custom_not_in_allowlist_with_allow_custom():
    policy = build_dimension_policy(allow_custom_dimensions=True)
    assert is_allowed_dimension("custom_unknown", policy=policy) is True


def test_is_allowed_dimension_non_custom_unknown():
    """A name that is neither known nor custom_ prefixed is never allowed."""
    policy = build_dimension_policy(allow_custom_dimensions=True)
    assert is_allowed_dimension("totally_unknown", policy=policy) is False


# ---------------------------------------------------------------------------
# normalize_dimension_inputs
# ---------------------------------------------------------------------------


def test_normalize_dimension_inputs_none_returns_empty():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs(None, policy=policy)
    assert valid == []
    assert invalid == []


def test_normalize_dimension_inputs_empty_list():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs([], policy=policy)
    assert valid == []
    assert invalid == []


def test_normalize_dimension_inputs_known_dimensions():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs(
        ["naming_quality", "logic_clarity"], policy=policy
    )
    assert valid == ["naming_quality", "logic_clarity"]
    assert invalid == []


def test_normalize_dimension_inputs_deduplicates():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs(
        ["naming_quality", "naming_quality"], policy=policy
    )
    assert valid == ["naming_quality"]
    assert invalid == []


def test_normalize_dimension_inputs_separates_invalid():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs(
        ["naming_quality", "custom_nope", "logic_clarity"],
        policy=policy,
    )
    assert valid == ["naming_quality", "logic_clarity"]
    assert invalid == ["custom_nope"]


def test_normalize_dimension_inputs_normalizes_names():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs(
        ["Naming-Quality", "Logic clarity"], policy=policy
    )
    assert valid == ["naming_quality", "logic_clarity"]


def test_normalize_dimension_inputs_skips_empty_canonical():
    policy = build_dimension_policy()
    valid, invalid = normalize_dimension_inputs(["", "naming_quality"], policy=policy)
    assert valid == ["naming_quality"]
    assert invalid == []


# ---------------------------------------------------------------------------
# normalize_assessment_inputs
# ---------------------------------------------------------------------------


def test_normalize_assessment_inputs_none():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs(None, policy=policy)
    assert accepted == {}
    assert skipped == []
    assert discovered == set()


def test_normalize_assessment_inputs_empty_dict():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs({}, policy=policy)
    assert accepted == {}
    assert skipped == []
    assert discovered == set()


def test_normalize_assessment_inputs_non_dict():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs("bad", policy=policy)
    assert accepted == {}


def test_normalize_assessment_inputs_known_dimensions_accepted():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs(
        {"naming_quality": {"score": 8}, "logic_clarity": {"score": 7}},
        policy=policy,
    )
    assert "naming_quality" in accepted
    assert "logic_clarity" in accepted
    assert skipped == []
    assert discovered == set()


def test_normalize_assessment_inputs_unknown_skipped():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs(
        {"naming_quality": {"score": 8}, "totally_bogus": {"score": 1}},
        policy=policy,
    )
    assert "naming_quality" in accepted
    assert "totally_bogus" not in accepted
    assert "totally_bogus" in skipped


def test_normalize_assessment_inputs_discovers_new_custom():
    policy = build_dimension_policy(allow_custom_dimensions=True)
    accepted, skipped, discovered = normalize_assessment_inputs(
        {"custom_new_thing": {"score": 5}},
        policy=policy,
    )
    assert "custom_new_thing" in accepted
    assert "custom_new_thing" in discovered


def test_normalize_assessment_inputs_existing_custom_not_rediscovered():
    policy = build_dimension_policy(
        state={"custom_review_dimensions": ["custom_old"]},
    )
    accepted, skipped, discovered = normalize_assessment_inputs(
        {"custom_old": {"score": 5}},
        policy=policy,
    )
    assert "custom_old" in accepted
    assert discovered == set()


def test_normalize_assessment_inputs_skipped_is_sorted_and_deduped():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs(
        {"zzz_unknown": 1, "aaa_unknown": 2, "zzz_unknown_2": 3},
        policy=policy,
    )
    assert skipped == sorted(skipped)


def test_normalize_assessment_inputs_empty_key_skipped():
    policy = build_dimension_policy()
    accepted, skipped, discovered = normalize_assessment_inputs(
        {"": {"score": 1}, "naming_quality": {"score": 8}},
        policy=policy,
    )
    assert "" in skipped
    assert "naming_quality" in accepted


# ---------------------------------------------------------------------------
# append_custom_dimensions
# ---------------------------------------------------------------------------


def test_append_custom_dimensions_adds_to_state():
    state: dict = {}
    append_custom_dimensions(state, {"custom_alpha", "custom_beta"})
    bucket = state["custom_review_dimensions"]
    assert "custom_alpha" in bucket
    assert "custom_beta" in bucket


def test_append_custom_dimensions_deduplicates():
    state: dict = {"custom_review_dimensions": ["custom_alpha"]}
    append_custom_dimensions(state, {"custom_alpha", "custom_beta"})
    bucket = state["custom_review_dimensions"]
    assert bucket.count("custom_alpha") == 1
    assert "custom_beta" in bucket


def test_append_custom_dimensions_noop_for_empty():
    state: dict = {}
    append_custom_dimensions(state, set())
    assert "custom_review_dimensions" not in state


def test_append_custom_dimensions_non_custom_ignored():
    state: dict = {}
    append_custom_dimensions(state, {"naming_quality"})
    bucket = state.get("custom_review_dimensions", [])
    assert "naming_quality" not in bucket


def test_append_custom_dimensions_repairs_non_list_bucket():
    state: dict = {"custom_review_dimensions": "corrupted"}
    append_custom_dimensions(state, {"custom_new"})
    bucket = state["custom_review_dimensions"]
    assert isinstance(bucket, list)
    assert "custom_new" in bucket


# ---------------------------------------------------------------------------
# filter_assessments_for_scoring
# ---------------------------------------------------------------------------


def test_filter_assessments_for_scoring_returns_none_for_none():
    policy = build_dimension_policy()
    assert filter_assessments_for_scoring(None, policy=policy) is None


def test_filter_assessments_for_scoring_returns_none_for_empty():
    policy = build_dimension_policy()
    assert filter_assessments_for_scoring({}, policy=policy) is None


def test_filter_assessments_for_scoring_keeps_known():
    policy = build_dimension_policy()
    result = filter_assessments_for_scoring(
        {"naming_quality": {"score": 7}}, policy=policy
    )
    assert result is not None
    assert "naming_quality" in result


def test_filter_assessments_for_scoring_drops_unknown():
    policy = build_dimension_policy()
    result = filter_assessments_for_scoring(
        {"totally_bogus": {"score": 7}}, policy=policy
    )
    assert result is None


def test_filter_assessments_for_scoring_normalizes_keys():
    policy = build_dimension_policy()
    result = filter_assessments_for_scoring(
        {"Naming-Quality": {"score": 9}}, policy=policy
    )
    assert result is not None
    assert "naming_quality" in result


# ---------------------------------------------------------------------------
# DimensionPolicy frozen dataclass
# ---------------------------------------------------------------------------


def test_dimension_policy_is_frozen():
    policy = build_dimension_policy()
    with pytest.raises(AttributeError):
        policy.allow_custom = True
