from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.engine._plan.refresh_lifecycle import (
    _LEGACY_PHASE_TO_MODE,
    carry_forward_subjective_review,
    current_lifecycle_phase,
    derive_display_phase,
    invalidate_postflight_scan,
    mark_postflight_scan_completed,
    migrate_legacy_phase,
    postflight_scan_pending,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync.workflow import _subjective_review_current_for_cycle

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_REFRESH_LIFECYCLE = _PACKAGE_ROOT / "engine" / "_plan" / "refresh_lifecycle.py"
_PIPELINE = _PACKAGE_ROOT / "engine" / "_plan" / "sync" / "pipeline.py"


def test_postflight_scan_pending_until_completed() -> None:
    plan = empty_plan()

    assert postflight_scan_pending(plan) is True

    changed = mark_postflight_scan_completed(plan, scan_count=7)

    assert changed is True
    assert postflight_scan_pending(plan) is False
    assert plan["refresh_state"]["postflight_scan_completed_at_scan_count"] == 7


def test_clearing_completion_ignores_synthetic_ids() -> None:
    plan = empty_plan()
    mark_postflight_scan_completed(plan, scan_count=3)

    changed = invalidate_postflight_scan(
        plan,
        issue_ids=[
            "workflow::run-scan",
            "triage::observe",
            "subjective::naming_quality",
        ],
    )

    assert changed is False
    assert postflight_scan_pending(plan) is False


def test_clearing_completion_for_real_issue_requires_new_scan() -> None:
    plan = empty_plan()
    mark_postflight_scan_completed(plan, scan_count=5)

    changed = invalidate_postflight_scan(
        plan,
        issue_ids=["unused::src/app.ts::thing"],
        state={
            "issues": {
                "unused::src/app.ts::thing": {
                    "id": "unused::src/app.ts::thing",
                    "detector": "unused",
                    "status": "open",
                    "file": "src/app.ts",
                    "tier": 1,
                    "confidence": "high",
                    "summary": "unused import",
                    "detail": {},
                }
            }
        },
    )

    assert changed is True
    assert postflight_scan_pending(plan) is True
    assert current_lifecycle_phase(plan) == "plan"


def test_clearing_completion_for_review_issue_keeps_current_scan_boundary() -> None:
    plan = empty_plan()
    mark_postflight_scan_completed(plan, scan_count=5)

    changed = invalidate_postflight_scan(
        plan,
        issue_ids=["review::src/app.ts::naming"],
        state={
            "issues": {
                "review::src/app.ts::naming": {
                    "id": "review::src/app.ts::naming",
                    "detector": "review",
                    "status": "open",
                    "file": "src/app.ts",
                    "tier": 1,
                    "confidence": "high",
                    "summary": "naming issue",
                    "detail": {"dimension": "naming_quality"},
                }
            }
        },
    )

    assert changed is False
    assert postflight_scan_pending(plan) is False


def test_current_lifecycle_phase_falls_back_for_legacy_plans() -> None:
    plan = empty_plan()
    original = deepcopy(plan)

    assert current_lifecycle_phase(plan) == "plan"
    assert plan == original

    mark_postflight_scan_completed(plan, scan_count=2)
    assert current_lifecycle_phase(plan) == "execute"

    plan["plan_start_scores"] = {"strict": 75.0}
    assert current_lifecycle_phase(plan) == "execute"


@pytest.mark.parametrize(
    ("legacy_phase", "expected_mode", "expected_changed"),
    [
        (legacy_phase, expected_mode, legacy_phase != expected_mode)
        for legacy_phase, expected_mode in sorted(_LEGACY_PHASE_TO_MODE.items())
    ],
)
def test_migrate_legacy_phase_maps_every_legacy_value(
    legacy_phase: str, expected_mode: str, expected_changed: bool
) -> None:
    plan = empty_plan()
    plan["refresh_state"] = {"lifecycle_phase": legacy_phase}

    changed = migrate_legacy_phase(plan)

    assert changed is expected_changed
    assert plan["refresh_state"]["lifecycle_phase"] == expected_mode


def test_migrate_legacy_phase_is_idempotent_for_valid_mode() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {"lifecycle_phase": "plan"}

    changed = migrate_legacy_phase(plan)

    assert changed is False
    assert plan["refresh_state"]["lifecycle_phase"] == "plan"


def test_migrate_legacy_phase_promotes_stuck_plan_to_execute() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {"lifecycle_phase": "review"}
    plan["plan_start_scores"] = {"strict": 75.0}
    plan["queue_order"] = ["unused::src/app.ts::thing"]

    changed = migrate_legacy_phase(plan)

    assert changed is True
    assert plan["refresh_state"]["lifecycle_phase"] == "execute"


def test_migrate_legacy_phase_noops_for_fresh_plan_without_marker() -> None:
    plan = empty_plan()

    changed = migrate_legacy_phase(plan)

    assert changed is False
    assert plan["refresh_state"] == {}


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "has_initial_review": True,
                "has_postflight_assessment": False,
                "has_workflow": False,
                "has_triage": False,
                "has_review_postflight": False,
                "has_execution": False,
                "fresh_boundary": True,
                "prefer_scan": False,
            },
            "review_initial",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": False,
                "has_workflow": False,
                "has_triage": False,
                "has_review_postflight": False,
                "has_execution": False,
                "fresh_boundary": False,
                "prefer_scan": True,
            },
            "scan",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": True,
                "has_workflow": False,
                "has_triage": False,
                "has_review_postflight": False,
                "has_execution": False,
                "fresh_boundary": False,
                "prefer_scan": False,
            },
            "assessment",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": False,
                "has_workflow": True,
                "has_triage": False,
                "has_review_postflight": False,
                "has_execution": False,
                "fresh_boundary": False,
                "prefer_scan": False,
            },
            "workflow",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": False,
                "has_workflow": False,
                "has_triage": True,
                "has_review_postflight": False,
                "has_execution": False,
                "fresh_boundary": False,
                "prefer_scan": False,
            },
            "triage",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": False,
                "has_workflow": False,
                "has_triage": False,
                "has_review_postflight": True,
                "has_execution": False,
                "fresh_boundary": False,
                "prefer_scan": False,
            },
            "review",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": False,
                "has_workflow": False,
                "has_triage": False,
                "has_review_postflight": False,
                "has_execution": True,
                "fresh_boundary": False,
                "prefer_scan": False,
            },
            "execute",
        ),
        (
            {
                "has_initial_review": False,
                "has_postflight_assessment": False,
                "has_workflow": False,
                "has_triage": False,
                "has_review_postflight": False,
                "has_execution": False,
                "fresh_boundary": False,
                "prefer_scan": False,
            },
            "scan",
        ),
    ],
)
def test_derive_display_phase_single_signal_cases(
    kwargs: dict[str, bool], expected: str
) -> None:
    assert derive_display_phase(**kwargs) == expected


def test_derive_display_phase_respects_priority_chain() -> None:
    assert (
        derive_display_phase(
            has_initial_review=True,
            has_postflight_assessment=True,
            has_workflow=True,
            has_triage=True,
            has_review_postflight=True,
            has_execution=True,
            fresh_boundary=True,
            prefer_scan=True,
            has_promoted_execution=True,
        )
        == "execute"
    )
    assert (
        derive_display_phase(
            has_initial_review=True,
            has_postflight_assessment=False,
            has_workflow=True,
            has_triage=False,
            has_review_postflight=False,
            has_execution=False,
            fresh_boundary=True,
            prefer_scan=False,
        )
        == "review_initial"
    )
    assert (
        derive_display_phase(
            has_initial_review=False,
            has_postflight_assessment=True,
            has_workflow=True,
            has_triage=False,
            has_review_postflight=False,
            has_execution=False,
            fresh_boundary=False,
            prefer_scan=False,
        )
        == "assessment"
    )


def test_derive_display_phase_is_stateless() -> None:
    kwargs = {
        "has_initial_review": False,
        "has_postflight_assessment": False,
        "has_workflow": True,
        "has_triage": False,
        "has_review_postflight": False,
        "has_execution": False,
        "fresh_boundary": False,
        "prefer_scan": False,
    }

    assert derive_display_phase(**kwargs) == derive_display_phase(**kwargs)



def test_carry_forward_subjective_review_updates_matching_marker() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "subjective_review_completed_at_scan_count": 5,
    }

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )

    assert changed is True
    assert plan["refresh_state"]["subjective_review_completed_at_scan_count"] == 6


def test_carry_forward_subjective_review_rejects_stale_marker() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "subjective_review_completed_at_scan_count": 3,
    }

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )

    assert changed is False
    assert plan["refresh_state"]["subjective_review_completed_at_scan_count"] == 3


def test_carry_forward_subjective_review_requires_existing_marker() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 5}

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )

    assert changed is False
    assert "subjective_review_completed_at_scan_count" not in plan["refresh_state"]


def test_carry_forward_subjective_review_is_noop_when_marker_already_current() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "subjective_review_completed_at_scan_count": 6,
    }

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=6,
        new_scan_count=6,
    )

    assert changed is False
    assert plan["refresh_state"]["subjective_review_completed_at_scan_count"] == 6


def test_carry_forward_subjective_review_requires_refresh_state_dict() -> None:
    plan = empty_plan()
    plan["refresh_state"] = None

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )

    assert changed is False


def test_force_rescan_preserves_subjective_review_completion() -> None:
    plan = empty_plan()
    plan["queue_order"] = []
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "subjective_review_completed_at_scan_count": 5,
    }
    state = {"issues": {}, "dimension_scores": {}, "scan_count": 6}
    policy = SimpleNamespace(
        unscored_ids=set(),
        stale_ids={"naming_quality"},
        under_target_ids={"naming_quality"},
    )

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )
    mark_postflight_scan_completed(plan, scan_count=6)

    assert changed is True
    assert plan["refresh_state"]["subjective_review_completed_at_scan_count"] == 6
    assert _subjective_review_current_for_cycle(plan, state, policy=policy) is True


def test_force_rescan_with_stale_review_marker_does_not_promote() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "subjective_review_completed_at_scan_count": 3,
    }
    state = {"issues": {}, "dimension_scores": {}, "scan_count": 6}
    policy = SimpleNamespace(
        unscored_ids=set(),
        stale_ids={"naming_quality"},
        under_target_ids={"naming_quality"},
    )

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )
    mark_postflight_scan_completed(plan, scan_count=6)

    assert changed is False
    assert plan["refresh_state"]["subjective_review_completed_at_scan_count"] == 3
    assert _subjective_review_current_for_cycle(plan, state, policy=policy) is False


def test_force_rescan_without_prior_review_does_not_create_marker() -> None:
    plan = empty_plan()
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 5}

    changed = carry_forward_subjective_review(
        plan,
        old_postflight_scan_count=5,
        new_scan_count=6,
    )

    assert changed is False
    assert "subjective_review_completed_at_scan_count" not in plan["refresh_state"]


def test_lifecycle_phase_writes_stay_owned_by_refresh_lifecycle_module() -> None:
    direct_writers: list[str] = []
    private_setter_callers: list[str] = []

    for path in _PACKAGE_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_set_lifecycle_phase":
                    private_setter_callers.append(str(path.relative_to(_PACKAGE_ROOT)))
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                slice_node = target.slice
                key: str | None = None
                if isinstance(slice_node, ast.Constant) and isinstance(
                    slice_node.value, str
                ):
                    key = slice_node.value
                elif isinstance(slice_node, ast.Name):
                    key = slice_node.id
                if key in {"lifecycle_phase", "_LIFECYCLE_PHASE_KEY"}:
                    direct_writers.append(str(path.relative_to(_PACKAGE_ROOT)))

    assert private_setter_callers == [str(_PIPELINE.relative_to(_PACKAGE_ROOT))]
    assert sorted(set(direct_writers)) == [
        str(_REFRESH_LIFECYCLE.relative_to(_PACKAGE_ROOT))
    ]
