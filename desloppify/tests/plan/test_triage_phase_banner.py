"""Tests for triage lifecycle banner messaging."""

from __future__ import annotations

from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS
from desloppify.engine.plan_triage import triage_phase_banner


def test_banner_empty_when_no_triage_stages():
    plan = empty_plan()
    assert triage_phase_banner(plan) == ""


def test_banner_pending_when_objective_backlog_exists():
    plan = empty_plan()
    plan["queue_order"] = list(TRIAGE_STAGE_IDS)
    state = {
        "issues": {
            "obj-1": {"status": "open", "detector": "complexity"},
            "review-1": {"status": "open", "detector": "review"},
        }
    }

    banner = triage_phase_banner(plan, state)
    assert banner.startswith("TRIAGE PENDING")


def test_banner_pending_when_stale_triage_is_deferred_behind_objective_backlog():
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 72.0}
    plan["epic_triage_meta"] = {"triaged_ids": ["review::old"]}
    state = {
        "issues": {
            "obj-1": {"id": "obj-1", "status": "open", "detector": "complexity"},
            "review::old": {"id": "review::old", "status": "open", "detector": "review"},
            "review::new": {"id": "review::new", "status": "open", "detector": "review"},
        }
    }

    banner = triage_phase_banner(plan, state)
    assert banner.startswith("TRIAGE PENDING")


def test_banner_mode_when_no_objective_backlog():
    plan = empty_plan()
    plan["queue_order"] = list(TRIAGE_STAGE_IDS)
    state = {"issues": {"review-1": {"status": "open", "detector": "review"}}}

    banner = triage_phase_banner(plan, state)
    assert banner.startswith("TRIAGE MODE")


def test_banner_progress_when_stages_in_progress_and_no_objective_backlog():
    plan = empty_plan()
    plan["queue_order"] = list(TRIAGE_STAGE_IDS)
    plan["epic_triage_meta"] = {
        "triage_stages": {
            "observe": {"report": "x"},
            "reflect": {"report": "y"},
        }
    }
    state = {"issues": {"review-1": {"status": "open", "detector": "review"}}}

    banner = triage_phase_banner(plan, state)
    assert "TRIAGE MODE (2/6 stages recorded)" in banner
