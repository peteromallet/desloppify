"""Tests for the unified triage disposition map (IssueDisposition)."""

from __future__ import annotations

from desloppify.app.commands.plan.triage.confirmations.basic import (
    _AUTO_SKIP_VERDICTS,
    _apply_observe_auto_skips,
    _undo_observe_auto_skips,
)
from desloppify.app.commands.plan.triage.stage_queue import cascade_clear_dispositions
from desloppify.app.commands.plan.triage.stages.evidence_parsing import (
    resolve_short_hash_to_full_id,
)
from desloppify.app.commands.plan.triage.validation.organize_policy import (
    validate_organize_against_dispositions,
)
from desloppify.engine._plan.schema import (
    IssueDisposition,
    empty_plan,
)
from desloppify.engine._plan.skip_policy import (
    VALID_SKIP_KINDS,
    skip_kind_requires_attestation,
    skip_kind_state_status,
)

# ---------------------------------------------------------------------------
# Schema: IssueDisposition exists and is well-typed
# ---------------------------------------------------------------------------


def test_issue_disposition_type_exists():
    """IssueDisposition is importable and has expected fields."""
    d: IssueDisposition = {
        "verdict": "genuine",
        "verdict_reasoning": "confirmed real",
        "files_read": ["src/foo.ts"],
        "recommendation": "fix it",
        "decision": "cluster",
        "target": "my-cluster",
        "decision_source": "reflect",
    }
    assert d["verdict"] == "genuine"
    assert d["decision_source"] == "reflect"


# ---------------------------------------------------------------------------
# resolve_short_hash_to_full_id: collision-aware resolution
# ---------------------------------------------------------------------------


class TestResolveShortHash:
    def test_direct_match(self):
        valid = {"review::complexity::abcd1234"}
        assert resolve_short_hash_to_full_id("review::complexity::abcd1234", valid) == "review::complexity::abcd1234"

    def test_short_hash_resolves(self):
        valid = {"review::complexity::abcd1234"}
        assert resolve_short_hash_to_full_id("abcd1234", valid) == "review::complexity::abcd1234"

    def test_ambiguous_short_hash_returns_none(self):
        # Two IDs with the same short hash
        valid = {
            "review::complexity::abcd1234",
            "review::naming::abcd1234",
        }
        assert resolve_short_hash_to_full_id("abcd1234", valid) is None

    def test_unknown_hash_returns_none(self):
        valid = {"review::complexity::abcd1234"}
        assert resolve_short_hash_to_full_id("deadbeef", valid) is None


# ---------------------------------------------------------------------------
# cascade_clear_dispositions
# ---------------------------------------------------------------------------


class TestCascadeClearDispositions:
    def test_observe_clears_all(self):
        meta = {
            "issue_dispositions": {
                "id1": {"verdict": "genuine", "decision": "cluster", "target": "c1", "decision_source": "reflect"},
                "id2": {"verdict": "false positive", "decision": "skip", "target": "fp", "decision_source": "observe_auto"},
            }
        }
        cascade_clear_dispositions(meta, "observe")
        assert meta["issue_dispositions"] == {}

    def test_reflect_clears_only_decisions(self):
        meta = {
            "issue_dispositions": {
                "id1": {
                    "verdict": "genuine",
                    "verdict_reasoning": "real",
                    "decision": "cluster",
                    "target": "c1",
                    "decision_source": "reflect",
                },
                "id2": {
                    "verdict": "false positive",
                    "decision": "skip",
                    "target": "fp",
                    "decision_source": "observe_auto",
                },
            }
        }
        cascade_clear_dispositions(meta, "reflect")
        # Verdicts preserved
        assert meta["issue_dispositions"]["id1"]["verdict"] == "genuine"
        assert meta["issue_dispositions"]["id1"]["verdict_reasoning"] == "real"
        # Decisions cleared
        assert "decision" not in meta["issue_dispositions"]["id1"]
        assert "target" not in meta["issue_dispositions"]["id1"]
        assert "decision_source" not in meta["issue_dispositions"]["id1"]
        # Observe-auto decisions are preserved because reflect does not own them.
        assert meta["issue_dispositions"]["id2"]["verdict"] == "false positive"
        assert meta["issue_dispositions"]["id2"]["decision"] == "skip"
        assert meta["issue_dispositions"]["id2"]["target"] == "fp"
        assert meta["issue_dispositions"]["id2"]["decision_source"] == "observe_auto"

    def test_no_dispositions_is_noop(self):
        meta = {}
        cascade_clear_dispositions(meta, "observe")
        assert "issue_dispositions" not in meta

    def test_other_stage_is_noop(self):
        meta = {"issue_dispositions": {"id1": {"verdict": "genuine"}}}
        cascade_clear_dispositions(meta, "organize")
        assert meta["issue_dispositions"]["id1"]["verdict"] == "genuine"

    def test_observe_clears_protected_disposition_entries(self):
        held = {"verdict": "genuine", "decision": "cluster", "target": "hold"}
        meta = {
            "protected_review_issue_ids": ["held"],
            "issue_dispositions": {
                "held": held,
                "other": {"verdict": "genuine"},
            },
        }

        cascade_clear_dispositions(meta, "observe")

        assert meta["issue_dispositions"] == {}


# ---------------------------------------------------------------------------
# Auto-skip on observe confirmation
# ---------------------------------------------------------------------------


class _FakeServices:
    def __init__(self):
        self.saved = False

    def save_plan(self, plan):
        self.saved = True


class TestAutoSkip:
    def test_auto_skip_false_positive(self):
        plan = empty_plan()
        plan["queue_order"] = ["id1", "id2"]
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "false positive", "verdict_reasoning": "not real"},
            "id2": {"verdict": "genuine", "verdict_reasoning": "confirmed"},
        }

        services = _FakeServices()
        count = _apply_observe_auto_skips(plan, meta, services)

        assert count == 1
        assert "id1" in plan["skipped"]
        assert plan["skipped"]["id1"]["kind"] == "triage_observe_auto"
        assert plan["skipped"]["id1"]["reason"] == "false positive"
        assert "id2" not in plan["skipped"]
        # id1 removed from queue
        assert "id1" not in plan["queue_order"]
        assert "id2" in plan["queue_order"]
        # Disposition updated
        assert meta["issue_dispositions"]["id1"]["decision"] == "skip"
        assert meta["issue_dispositions"]["id1"]["decision_source"] == "observe_auto"

    def test_auto_skip_exaggerated(self):
        plan = empty_plan()
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "exaggerated", "verdict_reasoning": "overstated"},
        }

        services = _FakeServices()
        count = _apply_observe_auto_skips(plan, meta, services)
        assert count == 1
        assert plan["skipped"]["id1"]["kind"] == "triage_observe_auto"

    def test_no_double_skip(self):
        plan = empty_plan()
        plan["skipped"]["id1"] = {"issue_id": "id1", "kind": "permanent"}
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "false positive", "verdict_reasoning": "not real"},
        }

        services = _FakeServices()
        count = _apply_observe_auto_skips(plan, meta, services)
        assert count == 0  # Already skipped

    def test_actionability_verdicts_not_auto_skipped(self):
        plan = empty_plan()
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "over engineering", "verdict_reasoning": "overkill"},
            "id2": {"verdict": "not worth it", "verdict_reasoning": "marginal"},
        }

        services = _FakeServices()
        count = _apply_observe_auto_skips(plan, meta, services)
        assert count == 0

    def test_undo_auto_skips(self):
        plan = empty_plan()
        plan["skipped"]["id1"] = {"issue_id": "id1", "kind": "triage_observe_auto"}
        plan["skipped"]["id2"] = {"issue_id": "id2", "kind": "permanent"}
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "false positive", "decision_source": "observe_auto"},
        }

        count = _undo_observe_auto_skips(plan, meta)
        assert count == 1
        assert "id1" not in plan["skipped"]
        assert "id2" in plan["skipped"]  # Not touched


# ---------------------------------------------------------------------------
# Skip policy: triage_observe_auto kind
# ---------------------------------------------------------------------------


def test_triage_observe_auto_in_valid_kinds():
    assert "triage_observe_auto" in VALID_SKIP_KINDS


def test_triage_observe_auto_no_attestation():
    assert skip_kind_requires_attestation("triage_observe_auto") is False


def test_triage_observe_auto_state_status():
    assert skip_kind_state_status("triage_observe_auto") == "false_positive"


# ---------------------------------------------------------------------------
# Organize validates against dispositions
# ---------------------------------------------------------------------------


class TestOrganizeDispositionValidation:
    def test_no_dispositions_returns_empty(self):
        plan = empty_plan()
        assert validate_organize_against_dispositions(plan=plan) == []

    def test_matching_cluster_disposition(self):
        plan = empty_plan()
        plan["clusters"]["my-cluster"] = {
            "name": "my-cluster",
            "issue_ids": ["id1"],
        }
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "genuine", "decision": "cluster", "target": "my-cluster", "decision_source": "reflect"},
        }
        assert validate_organize_against_dispositions(plan=plan) == []

    def test_matching_skip_disposition(self):
        plan = empty_plan()
        plan["skipped"]["id1"] = {"issue_id": "id1", "kind": "triage_observe_auto"}
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "false positive", "decision": "skip", "target": "false positive", "decision_source": "observe_auto"},
        }
        assert validate_organize_against_dispositions(plan=plan) == []

    def test_mismatch_detected(self):
        plan = empty_plan()
        # id1 should be in cluster but isn't
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "genuine", "decision": "cluster", "target": "my-cluster", "decision_source": "reflect"},
        }
        mismatches = validate_organize_against_dispositions(plan=plan)
        assert len(mismatches) == 1
        assert mismatches[0].issue_id == "id1"

    def test_entries_without_decision_ignored(self):
        plan = empty_plan()
        meta = plan["epic_triage_meta"]
        meta["issue_dispositions"] = {
            "id1": {"verdict": "genuine"},  # No decision yet
        }
        assert validate_organize_against_dispositions(plan=plan) == []


# ---------------------------------------------------------------------------
# Auto-skip verdicts taxonomy
# ---------------------------------------------------------------------------


def test_auto_skip_verdicts_are_validity_only():
    """Only validity verdicts (false positive, exaggerated) trigger auto-skip."""
    assert _AUTO_SKIP_VERDICTS == frozenset({"false positive", "exaggerated"})
    # Actionability verdicts should NOT be in auto-skip
    assert "over engineering" not in _AUTO_SKIP_VERDICTS
    assert "not worth it" not in _AUTO_SKIP_VERDICTS
    assert "genuine" not in _AUTO_SKIP_VERDICTS
