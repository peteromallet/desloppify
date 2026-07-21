"""Regression tests for internal plan helper modules."""

from __future__ import annotations

from desloppify.engine._plan.annotations import (
    annotation_counts,
    get_issue_description,
    get_issue_note,
    get_issue_override,
)
from desloppify.engine._plan.promoted_ids import (
    add_promoted_ids,
    has_promoted_execution_candidate,
    promoted_insertion_index,
    prune_promoted_ids,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.skip_policy import (
    USER_SKIP_KINDS,
    VALID_SKIP_KINDS,
    skip_kind_from_flags,
    skip_kind_needs_state_reopen,
    skip_kind_requires_attestation,
    skip_kind_requires_note,
    skip_kind_state_status,
)


def test_skip_policy_maps_and_requirements():
    assert skip_kind_from_flags(permanent=False, false_positive=False) == "temporary"
    assert skip_kind_from_flags(permanent=True, false_positive=False) == "permanent"
    assert skip_kind_from_flags(permanent=True, false_positive=True) == "false_positive"

    assert skip_kind_requires_attestation("temporary") is False
    assert skip_kind_requires_attestation("permanent") is True
    assert skip_kind_requires_attestation("false_positive") is True

    assert skip_kind_requires_note("temporary") is False
    assert skip_kind_requires_note("permanent") is True
    assert skip_kind_requires_note("false_positive") is False

    assert skip_kind_state_status("temporary") == "deferred"
    assert skip_kind_state_status("permanent") == "wontfix"
    assert skip_kind_state_status("false_positive") == "false_positive"
    assert skip_kind_state_status("triaged_out") == "triaged_out"

    assert skip_kind_needs_state_reopen("temporary") is True
    assert skip_kind_needs_state_reopen("permanent") is True
    assert skip_kind_needs_state_reopen("false_positive") is True
    assert skip_kind_needs_state_reopen("triaged_out") is True
    assert skip_kind_needs_state_reopen("triage_observe_auto") is True

    assert skip_kind_state_status("triage_observe_auto") == "false_positive"
    assert skip_kind_requires_attestation("triage_observe_auto") is False
    assert skip_kind_requires_note("triage_observe_auto") is False

    assert tuple(USER_SKIP_KINDS) == ("temporary", "permanent", "false_positive")
    assert VALID_SKIP_KINDS == {
        "temporary",
        "permanent",
        "false_positive",
        "triaged_out",
        "triage_observe_auto",
    }


def test_promoted_helpers_preserve_order_and_prune():
    plan = empty_plan()
    order = ["a", "b", "c", "d"]

    add_promoted_ids(plan, ["b", "c"])
    add_promoted_ids(plan, ["c", "a"])
    assert plan["promoted_ids"] == ["b", "c", "a"]
    assert promoted_insertion_index(order, plan) == 3
    assert has_promoted_execution_candidate(plan, ["b", "d"]) is True
    assert has_promoted_execution_candidate(plan, ["d"]) is False

    prune_promoted_ids(plan, {"b", "x"})
    assert plan["promoted_ids"] == ["c", "a"]
    assert promoted_insertion_index(order, plan) == 3


def test_annotation_helpers_handle_missing_and_non_dict_payloads():
    plan = empty_plan()
    plan["overrides"] = {
        "a": {"issue_id": "a", "description": "desc", "note": "note"},
        "b": {"issue_id": "b", "description": "", "note": None},
        "c": "invalid payload",
    }

    assert get_issue_override(plan, "a")["issue_id"] == "a"
    assert get_issue_override(plan, "missing") == {}
    assert get_issue_override(plan, "c") == {}

    assert get_issue_description(plan, "a") == "desc"
    assert get_issue_description(plan, "b") == ""
    assert get_issue_note(plan, "a") == "note"
    assert get_issue_note(plan, "b") is None

    assert annotation_counts(plan) == (1, 1)
