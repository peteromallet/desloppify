"""Temporary queue deferral preserves the cluster chosen during reflect."""

from __future__ import annotations

import pytest

from desloppify.app.commands.plan.triage.validation.organize_policy import (
    validate_organize_against_dispositions,
    validate_organize_against_reflect_ledger,
)

ISSUE_ID = "review::src/service.php::shared_validation"
CLUSTER_NAME = "later-service"


def _deferred_plan(*, decision: str = "cluster", skip_kind: str = "temporary") -> dict:
    return {
        "clusters": {
            CLUSTER_NAME: {"issue_ids": [ISSUE_ID], "description": "Update the service in a later batch."}
        },
        "skipped": {
            ISSUE_ID: {"kind": skip_kind, "note": "Keep the real issue for its scheduled replacement."}
        },
        "epic_triage_meta": {
            "issue_dispositions": {
                ISSUE_ID: {"decision": decision, "target": CLUSTER_NAME}
            },
            "triage_stages": {
                "reflect": {
                    "disposition_ledger": [
                        {"issue_id": ISSUE_ID, "decision": decision, "target": CLUSTER_NAME}
                    ]
                }
            },
        },
    }


def _mismatches(plan: dict, *, unified: bool) -> list:
    if unified:
        return validate_organize_against_dispositions(plan=plan)
    return validate_organize_against_reflect_ledger(
        plan=plan,
        stages=plan["epic_triage_meta"]["triage_stages"],
    )


@pytest.mark.parametrize("unified", [True, False])
def test_temporary_deferral_retains_the_reflected_cluster(unified: bool) -> None:
    plan = _deferred_plan()

    assert _mismatches(plan, unified=unified) == []


@pytest.mark.parametrize("unified", [True, False])
def test_temporary_deferral_does_not_hide_assignment_to_the_wrong_cluster(unified: bool) -> None:
    plan = _deferred_plan()
    plan["clusters"]["other-service"] = plan["clusters"].pop(CLUSTER_NAME)

    mismatches = _mismatches(plan, unified=unified)

    assert len(mismatches) == 1
    assert mismatches[0].expected_target == CLUSTER_NAME
    assert mismatches[0].actual.cluster_name == "other-service"


@pytest.mark.parametrize("unified", [True, False])
@pytest.mark.parametrize("decision", ["cluster", "permanent_skip"])
def test_temporary_deferral_without_membership_does_not_satisfy_reflect(
    unified: bool,
    decision: str,
) -> None:
    plan = _deferred_plan(decision=decision)
    plan["clusters"] = {}

    mismatches = _mismatches(plan, unified=unified)

    assert len(mismatches) == 1
    assert mismatches[0].actual_state == "temporarily deferred without a cluster"


@pytest.mark.parametrize("unified", [True, False])
@pytest.mark.parametrize("decision", ["cluster", "permanent_skip"])
def test_permanent_skip_only_satisfies_a_reflected_skip(
    unified: bool,
    decision: str,
) -> None:
    plan = _deferred_plan(decision=decision, skip_kind="permanent")

    mismatches = _mismatches(plan, unified=unified)

    if decision == "permanent_skip":
        assert mismatches == []
    else:
        assert len(mismatches) == 1
        assert mismatches[0].actual_state == "permanently skipped"
