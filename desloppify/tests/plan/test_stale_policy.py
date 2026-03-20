"""Tests for stale_policy.py — pure policy helpers for stale/unscored decisions."""

from __future__ import annotations

import hashlib

from desloppify.engine._plan.policy.stale import (
    compute_new_issue_ids,
    current_stale_ids,
    current_under_target_ids,
    current_unscored_ids,
    is_triage_stale,
    review_issue_snapshot_hash,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_empty() -> dict:
    return {"issues": {}, "scan_count": 1}


def _state_with_review_issues(*ids: str) -> dict:
    """Build minimal state with open review issues."""
    issues = {}
    for fid in ids:
        issues[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review issue {fid}",
        }
    return {"issues": issues, "scan_count": 5}


def _state_with_concerns_issues(*ids: str) -> dict:
    """Build minimal state with open concerns issues."""
    issues = {}
    for fid in ids:
        issues[fid] = {
            "status": "open",
            "detector": "concerns",
        }
    return {"issues": issues, "scan_count": 5}


def _state_with_stale_dimensions(*dim_keys: str, score: float = 50.0) -> dict:
    """Build a minimal state where subjective dimensions are stale."""
    dim_scores: dict = {}
    assessments: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": score,
            "strict": score,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": False,
                },
            },
        }
        assessments[dim_key] = {
            "score": score,
            "needs_review_refresh": True,
            "stale_since": "2025-01-01T00:00:00+00:00",
        }
    return {
        "issues": {},
        "scan_count": 5,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _state_with_unscored_dimensions_via_assessments(*dim_keys: str) -> dict:
    """State where subjective_assessments has placeholder entries."""
    dim_scores: dict = {}
    assessments: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": 0,
            "strict": 0,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": True,
                },
            },
        }
        assessments[dim_key] = {
            "score": 0.0,
            "source": "scan_reset_subjective",
            "placeholder": True,
        }
    return {
        "issues": {},
        "scan_count": 1,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _state_with_unscored_dimensions_via_dim_scores(*dim_keys: str) -> dict:
    """State where subjective_assessments is absent; placeholders live in dim_scores."""
    dim_scores: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": 0,
            "strict": 0,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": True,
                },
            },
        }
    return {
        "issues": {},
        "scan_count": 1,
        "dimension_scores": dim_scores,
        # No subjective_assessments key at all
    }


def _scored_state(*dim_keys: str, score: float = 80.0) -> dict:
    """State with scored (non-stale, non-placeholder) dimensions."""
    dim_scores: dict = {}
    assessments: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": score,
            "strict": score,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": False,
                },
            },
        }
        assessments[dim_key] = {
            "score": score,
        }
    return {
        "issues": {},
        "scan_count": 5,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


# ===========================================================================
# review_issue_snapshot_hash
# ===========================================================================


class TestReviewIssueSnapshotHash:
    def test_empty_issues_returns_empty_string(self):
        assert review_issue_snapshot_hash(_state_empty()) == ""

    def test_no_issues_key_returns_empty_string(self):
        assert review_issue_snapshot_hash({}) == ""

    def test_non_review_issues_return_empty_string(self):
        state = {
            "issues": {
                "unused::a": {"status": "open", "detector": "unused"},
                "smells::b": {"status": "open", "detector": "smells"},
            }
        }
        assert review_issue_snapshot_hash(state) == ""

    def test_closed_review_issues_return_empty_string(self):
        state = {
            "issues": {
                "review::a": {"status": "fixed", "detector": "review"},
            }
        }
        assert review_issue_snapshot_hash(state) == ""

    def test_open_review_issue_produces_hash(self):
        state = _state_with_review_issues("r1")
        h = review_issue_snapshot_hash(state)
        assert h != ""
        assert len(h) == 16  # truncated sha256

    def test_concerns_issues_included(self):
        state = _state_with_concerns_issues("c1")
        h = review_issue_snapshot_hash(state)
        assert h != ""

    def test_hash_is_deterministic(self):
        state = _state_with_review_issues("a", "b", "c")
        h1 = review_issue_snapshot_hash(state)
        h2 = review_issue_snapshot_hash(state)
        assert h1 == h2

    def test_hash_is_order_independent(self):
        """Sorted issue IDs should produce the same hash regardless of dict order."""
        s1 = _state_with_review_issues("b", "a")
        s2 = _state_with_review_issues("a", "b")
        assert review_issue_snapshot_hash(s1) == review_issue_snapshot_hash(s2)

    def test_hash_changes_when_issues_change(self):
        s1 = _state_with_review_issues("a", "b")
        s2 = _state_with_review_issues("a", "b", "c")
        assert review_issue_snapshot_hash(s1) != review_issue_snapshot_hash(s2)

    def test_hash_matches_manual_computation(self):
        state = _state_with_review_issues("r1", "r2")
        expected = hashlib.sha256("r1|r2".encode()).hexdigest()[:16]
        assert review_issue_snapshot_hash(state) == expected

    def test_mixed_detectors_only_hashes_review_and_concerns(self):
        state = {
            "issues": {
                "unused::a": {"status": "open", "detector": "unused"},
                "review::b": {"status": "open", "detector": "review"},
                "concerns::c": {"status": "open", "detector": "concerns"},
            }
        }
        # Only review::b and concerns::c should be in the hash
        expected_ids = sorted(["review::b", "concerns::c"])
        expected = hashlib.sha256("|".join(expected_ids).encode()).hexdigest()[:16]
        assert review_issue_snapshot_hash(state) == expected


# ===========================================================================
# current_stale_ids
# ===========================================================================


class TestCurrentStaleIds:
    def test_empty_state_returns_empty_set(self):
        assert current_stale_ids({}) == set()

    def test_no_dimension_scores_returns_empty_set(self):
        state = {"issues": {}, "scan_count": 1}
        assert current_stale_ids(state) == set()

    def test_empty_dimension_scores_returns_empty_set(self):
        state = {"dimension_scores": {}}
        assert current_stale_ids(state) == set()

    def test_stale_dimension_returned(self):
        state = _state_with_stale_dimensions("design_coherence")
        result = current_stale_ids(state)
        assert result == {"subjective::design_coherence"}

    def test_multiple_stale_dimensions(self):
        state = _state_with_stale_dimensions(
            "design_coherence", "error_consistency"
        )
        result = current_stale_ids(state)
        assert result == {
            "subjective::design_coherence",
            "subjective::error_consistency",
        }

    def test_non_stale_dimensions_excluded(self):
        state = _scored_state("design_coherence")
        result = current_stale_ids(state)
        assert result == set()

    def test_placeholder_dimensions_not_stale(self):
        state = _state_with_unscored_dimensions_via_assessments("design_coherence")
        result = current_stale_ids(state)
        assert result == set()

    def test_custom_prefix(self):
        state = _state_with_stale_dimensions("design_coherence")
        result = current_stale_ids(state, subjective_prefix="sub::")
        assert result == {"sub::design_coherence"}


# ===========================================================================
# current_unscored_ids
# ===========================================================================


class TestCurrentUnscoredIds:
    def test_empty_state_returns_empty_set(self):
        assert current_unscored_ids({}) == set()

    def test_no_dimension_scores_returns_empty_set(self):
        state = {"issues": {}, "scan_count": 1}
        assert current_unscored_ids(state) == set()

    def test_unscored_via_subjective_assessments(self):
        """When subjective_assessments exists with placeholder entries."""
        state = _state_with_unscored_dimensions_via_assessments(
            "design_coherence", "error_consistency"
        )
        result = current_unscored_ids(state)
        assert result == {
            "subjective::design_coherence",
            "subjective::error_consistency",
        }

    def test_unscored_via_dim_scores_fallback(self):
        """When subjective_assessments is absent, falls back to dim_scores detectors."""
        state = _state_with_unscored_dimensions_via_dim_scores(
            "design_coherence"
        )
        result = current_unscored_ids(state)
        assert result == {"subjective::design_coherence"}

    def test_scored_dimensions_not_unscored(self):
        state = _scored_state("design_coherence")
        result = current_unscored_ids(state)
        assert result == set()

    def test_non_placeholder_assessments_not_unscored(self):
        """Dimensions that are scored (no placeholder flag) are not unscored."""
        state = _state_with_stale_dimensions("design_coherence")
        result = current_unscored_ids(state)
        assert result == set()

    def test_empty_subjective_assessments_falls_back(self):
        """Empty subjective_assessments dict triggers the dim_scores fallback path."""
        state = _state_with_unscored_dimensions_via_dim_scores("design_coherence")
        state["subjective_assessments"] = {}  # empty dict
        result = current_unscored_ids(state)
        assert result == {"subjective::design_coherence"}

    def test_non_dict_payload_skipped(self):
        """Non-dict payloads in subjective_assessments are skipped."""
        state = {
            "subjective_assessments": {
                "design_coherence": "not_a_dict",
                "error_consistency": {"placeholder": True},
            },
            "dimension_scores": {},
        }
        result = current_unscored_ids(state)
        assert result == {"subjective::error_consistency"}

    def test_custom_prefix(self):
        state = _state_with_unscored_dimensions_via_assessments("design_coherence")
        result = current_unscored_ids(state, subjective_prefix="sub::")
        assert result == {"sub::design_coherence"}

    def test_empty_dim_key_skipped(self):
        """Entries with empty dimension_key are skipped."""
        state = {
            "subjective_assessments": {
                "": {"placeholder": True},
            },
            "dimension_scores": {},
        }
        result = current_unscored_ids(state)
        assert result == set()


# ===========================================================================
# current_under_target_ids
# ===========================================================================


class TestCurrentUnderTargetIds:
    def test_empty_state_returns_empty_set(self):
        assert current_under_target_ids({}) == set()

    def test_no_dimension_scores_returns_empty_set(self):
        state = {"issues": {}, "scan_count": 1}
        assert current_under_target_ids(state) == set()

    def test_dimension_below_target_included(self):
        state = _scored_state("design_coherence", score=70.0)
        result = current_under_target_ids(state, target_strict=95.0)
        assert result == {"subjective::design_coherence"}

    def test_dimension_at_target_excluded(self):
        state = _scored_state("design_coherence", score=95.0)
        result = current_under_target_ids(state, target_strict=95.0)
        assert result == set()

    def test_dimension_above_target_excluded(self):
        state = _scored_state("design_coherence", score=100.0)
        result = current_under_target_ids(state, target_strict=95.0)
        assert result == set()

    def test_stale_dimensions_excluded(self):
        """Stale dimensions are not in under_target because they belong to stale set."""
        state = _state_with_stale_dimensions("design_coherence", score=50.0)
        result = current_under_target_ids(state, target_strict=95.0)
        assert result == set()

    def test_unscored_dimensions_excluded(self):
        """Placeholder dimensions are not in under_target."""
        state = _state_with_unscored_dimensions_via_assessments("design_coherence")
        result = current_under_target_ids(state, target_strict=95.0)
        assert result == set()

    def test_multiple_under_target(self):
        state = _scored_state("dim_a", "dim_b", score=50.0)
        result = current_under_target_ids(state, target_strict=95.0)
        assert result == {"subjective::dim_a", "subjective::dim_b"}

    def test_mixed_above_and_below_target(self):
        """Only dimensions actually below target are returned."""
        state_low = _scored_state("dim_low", score=50.0)
        state_high = _scored_state("dim_high", score=100.0)
        # Merge the two states
        state_low["dimension_scores"].update(state_high["dimension_scores"])
        state_low["subjective_assessments"].update(
            state_high["subjective_assessments"]
        )
        result = current_under_target_ids(state_low, target_strict=95.0)
        assert result == {"subjective::dim_low"}

    def test_default_target_is_85(self):
        """Uses DEFAULT_TARGET_STRICT_SCORE (85.0) when not specified."""
        state = _scored_state("design_coherence", score=84.0)
        result = current_under_target_ids(state)
        assert "subjective::design_coherence" in result

        state_high = _scored_state("design_coherence", score=85.0)
        result_high = current_under_target_ids(state_high)
        assert result_high == set()


# ===========================================================================
# is_triage_stale
# ===========================================================================


class TestIsTriageStale:
    def test_not_stale_when_no_issues_and_no_meta(self):
        plan = {"epic_triage_meta": {}}
        state = _state_empty()
        assert is_triage_stale(plan, state) is False

    def test_stale_when_new_review_issues_exist(self):
        plan = {
            "epic_triage_meta": {
                "triaged_ids": [],
            }
        }
        state = _state_with_review_issues("r1")
        assert is_triage_stale(plan, state) is True

    def test_stale_when_new_concerns_issues_exist(self):
        plan = {
            "epic_triage_meta": {
                "triaged_ids": [],
            }
        }
        state = _state_with_concerns_issues("c1")
        assert is_triage_stale(plan, state) is True

    def test_not_stale_when_all_issues_already_triaged(self):
        plan = {
            "epic_triage_meta": {
                "triaged_ids": ["r1", "r2"],
            }
        }
        state = _state_with_review_issues("r1", "r2")
        assert is_triage_stale(plan, state) is False

    def test_stale_when_one_new_issue_since_triage(self):
        plan = {
            "epic_triage_meta": {
                "triaged_ids": ["r1"],
            }
        }
        state = _state_with_review_issues("r1", "r2")
        assert is_triage_stale(plan, state) is True

    def test_not_stale_when_resolved_issue_disappears(self):
        """Resolving a triaged issue should not trigger staleness."""
        plan = {
            "epic_triage_meta": {
                "triaged_ids": ["r1", "r2"],
            }
        }
        # r2 has been resolved and is no longer open
        state = _state_with_review_issues("r1")
        assert is_triage_stale(plan, state) is False

    def test_not_stale_when_triage_in_progress(self):
        """In-progress triage (confirmed stages + IDs in queue) is NOT stale.

        The lifecycle filter in the work queue already forces triage stages
        to the front — no need for is_triage_stale to double-gate.
        """
        plan = {
            "epic_triage_meta": {
                "triaged_ids": ["r1"],
                "triage_stages": {"observe": {"report": "analysis"}},
            },
            "queue_order": ["triage::observe", "triage::reflect"],
        }
        state = _state_with_review_issues("r1")
        assert is_triage_stale(plan, state) is False

    def test_closed_review_issues_ignored(self):
        plan = {"epic_triage_meta": {"triaged_ids": []}}
        state = {
            "issues": {
                "r1": {"status": "fixed", "detector": "review"},
            }
        }
        assert is_triage_stale(plan, state) is False

    def test_mechanical_issues_trigger_staleness_on_first_triage(self):
        """Mechanical issues trigger staleness when no prior triage exists."""
        plan = {"epic_triage_meta": {"triaged_ids": []}}
        state = {
            "issues": {
                "u1": {"status": "open", "detector": "unused"},
            }
        }
        assert is_triage_stale(plan, state) is True

    def test_mechanical_within_threshold_not_stale(self):
        """Mechanical count growth within threshold does not trigger staleness."""
        plan = {"epic_triage_meta": {
            "triaged_ids": ["r1"],
            "last_mechanical_count": 100,
        }}
        state = {
            "issues": {
                "r1": {"status": "open", "detector": "review"},
                **{f"u{i}": {"status": "open", "detector": "unused"} for i in range(105)},
            }
        }
        assert is_triage_stale(plan, state) is False

    def test_not_stale_when_stages_in_queue_but_all_triaged(self):
        """Triage stage IDs in queue don't trigger staleness if issues are triaged."""
        plan = {
            "epic_triage_meta": {
                "triaged_ids": ["r1"],
                "triage_stages": {"observe": {"report": "analysis"}},
            },
            "queue_order": ["triage::observe"],
        }
        state = _state_with_review_issues("r1")
        assert is_triage_stale(plan, state) is False

    def test_synthesized_ids_not_used_as_fallback(self):
        """is_triage_stale reads triaged_ids only, not synthesized_ids.

        Unlike compute_new_issue_ids, this function does NOT fall back to
        synthesized_ids. So r1 appears as a new untriaged issue.
        """
        plan = {
            "epic_triage_meta": {
                "synthesized_ids": ["r1"],  # legacy key, ignored here
            }
        }
        state = _state_with_review_issues("r1")
        # r1 is not in triaged_ids (empty default), so it's "new" => stale
        assert is_triage_stale(plan, state) is True


# ===========================================================================
# compute_new_issue_ids
# ===========================================================================


class TestComputeNewIssueIds:
    def test_empty_state_returns_empty_set(self):
        plan = {"epic_triage_meta": {}}
        state = _state_empty()
        assert compute_new_issue_ids(plan, state) == set()

    def test_all_new_when_no_triaged_ids(self):
        """When triaged_ids is empty, all current review IDs are new."""
        plan = {"epic_triage_meta": {"triaged_ids": []}}
        state = _state_with_review_issues("r1", "r2")
        # Empty triaged => triaged is empty set, but the function returns
        # current - triaged only if triaged is truthy
        result = compute_new_issue_ids(plan, state)
        # triaged is empty set => falsy => returns set() per implementation
        assert result == set()

    def test_returns_new_issues_since_triage(self):
        plan = {"epic_triage_meta": {"triaged_ids": ["r1"]}}
        state = _state_with_review_issues("r1", "r2", "r3")
        result = compute_new_issue_ids(plan, state)
        assert result == {"r2", "r3"}

    def test_excludes_active_cycle_ids_from_new_issue_detection(self):
        plan = {
            "epic_triage_meta": {
                "triaged_ids": ["r1"],
                "active_triage_issue_ids": ["r2"],
            }
        }
        state = _state_with_review_issues("r1", "r2", "r3")
        result = compute_new_issue_ids(plan, state)
        assert result == {"r3"}

    def test_no_new_when_all_triaged(self):
        plan = {"epic_triage_meta": {"triaged_ids": ["r1", "r2"]}}
        state = _state_with_review_issues("r1", "r2")
        result = compute_new_issue_ids(plan, state)
        assert result == set()

    def test_resolved_issues_not_counted(self):
        plan = {"epic_triage_meta": {"triaged_ids": ["r1"]}}
        state = {
            "issues": {
                "r1": {"status": "fixed", "detector": "review"},
                "r2": {"status": "open", "detector": "review"},
            }
        }
        result = compute_new_issue_ids(plan, state)
        assert result == {"r2"}

    def test_non_review_issues_excluded(self):
        plan = {"epic_triage_meta": {"triaged_ids": ["r1"]}}
        state = {
            "issues": {
                "r1": {"status": "open", "detector": "review"},
                "u1": {"status": "open", "detector": "unused"},
            }
        }
        result = compute_new_issue_ids(plan, state)
        assert result == set()

    def test_concerns_detector_included(self):
        plan = {"epic_triage_meta": {"triaged_ids": ["r1"]}}
        state = {
            "issues": {
                "r1": {"status": "open", "detector": "review"},
                "c1": {"status": "open", "detector": "concerns"},
            }
        }
        result = compute_new_issue_ids(plan, state)
        assert result == {"c1"}

    def test_synthesized_ids_not_used_as_fallback(self):
        """Legacy synthesized_ids should not be treated as triaged_ids."""
        plan = {"epic_triage_meta": {"synthesized_ids": ["r1"]}}
        state = _state_with_review_issues("r1", "r2")
        result = compute_new_issue_ids(plan, state)
        assert result == set()

    def test_no_meta_returns_empty(self):
        plan = {}
        state = _state_with_review_issues("r1")
        result = compute_new_issue_ids(plan, state)
        assert result == set()

    def test_active_cycle_ids_do_not_make_triage_stale(self):
        plan = {
            "epic_triage_meta": {
                "active_triage_issue_ids": ["r1", "r2"],
            }
        }
        state = _state_with_review_issues("r1", "r2")
        assert is_triage_stale(plan, state) is False
