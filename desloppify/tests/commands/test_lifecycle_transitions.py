"""Integration tests for lifecycle transitions through reconcile → work queue.

Exercises the full lifecycle by walking through each stage:
  scan → initial reviews → objectives → postflight scan → subjective review
  → communicate-score/create-plan → triage

Between scans, items are completed via ``purge_ids`` (what ``plan resolve``
does) and the queue is re-checked without reconciling.  ``reconcile`` only
runs at scan boundaries — matching the real CLI flow.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.scan.plan_reconcile as reconcile_mod
from desloppify.base.subjective_dimensions import DISPLAY_NAMES
from desloppify.engine._plan.constants import (
    TRIAGE_STAGE_IDS,
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_CREATE_PLAN_ID,
)
from desloppify.engine._plan.operations.lifecycle import purge_ids
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    build_work_queue,
)

# ---------------------------------------------------------------------------
# Dimensions we use throughout (3 is enough to be readable)
# ---------------------------------------------------------------------------
DIM_KEYS = ("naming_quality", "logic_clarity", "type_safety")
DIM_DISPLAY = {k: DISPLAY_NAMES[k] for k in DIM_KEYS}

OBJECTIVE_ISSUES = [
    {"id": "obj-1", "detector": "complexity", "file": "src/app.py", "status": "open",
     "tier": 2, "confidence": "high"},
    {"id": "obj-2", "detector": "naming", "file": "src/util.py", "status": "open",
     "tier": 3, "confidence": "medium"},
]


# ---------------------------------------------------------------------------
# State / plan helpers
# ---------------------------------------------------------------------------

def _placeholder_dim_entries(key: str) -> tuple[str, dict, dict]:
    """(display_name, dim_scores_entry, subjective_assessment) for a placeholder."""
    return (
        DIM_DISPLAY[key],
        {
            "score": 0, "strict": 0, "failing": 0, "checks": 0,
            "detectors": {"subjective_assessment": {"placeholder": True, "dimension_key": key}},
        },
        {"score": 0, "placeholder": True},
    )


def _scored_dim_entries(key: str, score: float) -> tuple[str, dict, dict]:
    """(display_name, dim_scores_entry, subjective_assessment) with a real score."""
    return (
        DIM_DISPLAY[key],
        {
            "score": score, "strict": score, "failing": 0, "checks": 1,
            "detectors": {"subjective_assessment": {"placeholder": False, "dimension_key": key}},
        },
        {"score": score, "placeholder": False},
    )


def _build_state(
    issues: list[dict],
    dims: list[tuple[str, dict, dict]],
    *,
    strict_score: float | None = None,
    overall_score: float | None = None,
    objective_score: float | None = None,
) -> dict:
    work_items = {i["id"]: dict(i) for i in issues}
    state: dict = {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 1,
        "dimension_scores": {},
        "subjective_assessments": {},
    }
    for display, dim_entry, assessment in dims:
        state["dimension_scores"][display] = dim_entry
        dim_key = dim_entry["detectors"]["subjective_assessment"]["dimension_key"]
        state["subjective_assessments"][dim_key] = assessment
    if strict_score is not None:
        state["strict_score"] = strict_score
    if overall_score is not None:
        state["overall_score"] = overall_score
    if objective_score is not None:
        state["objective_score"] = objective_score
    return state


def _reconcile(state: dict, plan: dict, monkeypatch) -> dict:
    """Simulate a scan boundary: run reconcile_plan_post_scan with mocked I/O."""
    saved: list[dict] = []
    monkeypatch.setattr(reconcile_mod, "load_plan", lambda _path=None: plan)
    monkeypatch.setattr(reconcile_mod, "save_plan", lambda p, _path=None: saved.append(p))
    reconcile_mod.reconcile_plan_post_scan(SimpleNamespace(
        state=state, state_path=Path("/tmp/fake-state.json"), config={},
    ))
    return saved[-1] if saved else plan


def _queue_ids(state: dict, plan: dict) -> list[str]:
    result = build_work_queue(state, options=QueueBuildOptions(plan=plan, count=None))
    return [item["id"] for item in result["items"]]


def _spoof_reviews_complete(state: dict, *, score: float = 100.0) -> None:
    """Mutate state in place: replace all placeholder dims with scored ones."""
    for key in DIM_KEYS:
        display, dim_entry, assessment = _scored_dim_entries(key, score)
        state["dimension_scores"][display] = dim_entry
        state["subjective_assessments"][key] = assessment
    state["strict_score"] = score
    state["overall_score"] = score
    state["objective_score"] = score


def _complete_endgame_subjective_reruns(state: dict) -> None:
    """Mark scored subjective dimensions as fully current/high to clear rerun queue."""
    for key in DIM_KEYS:
        assessment = state["subjective_assessments"].setdefault(key, {})
        assessment["placeholder"] = False
        assessment["needs_review_refresh"] = False
        assessment["score"] = 100.0
        dim = state["dimension_scores"][DIM_DISPLAY[key]]
        dim["score"] = 100.0
        dim["strict"] = 100.0


def _add_review_issues(state: dict) -> None:
    """Mutate state in place: add review detector issues that trigger triage."""
    work_items = state.setdefault("work_items", state.get("issues", {}))
    state["issues"] = work_items
    for key in ("naming_quality", "logic_clarity"):
        fid = f"review-{key}"
        work_items[fid] = {
            "id": fid, "detector": "review", "file": "src/app.py",
            "status": "open", "detail": {"dimension": key},
        }


# ---------------------------------------------------------------------------
# Test 1: Fresh scan — only initial reviews visible
# ---------------------------------------------------------------------------

class TestPhase1OnlyInitialReviews:

    def test_only_initial_reviews_visible(self, monkeypatch):
        """Fresh scan with placeholders: only subjective initial review items appear."""
        state = _build_state(OBJECTIVE_ISSUES, [_placeholder_dim_entries(k) for k in DIM_KEYS])
        plan = _reconcile(state, empty_plan(), monkeypatch)

        ids = _queue_ids(state, plan)

        assert all(fid.startswith("subjective::") for fid in ids)
        assert len(ids) == len(DIM_KEYS)
        assert "obj-1" not in ids
        assert "obj-2" not in ids


# ---------------------------------------------------------------------------
# Test 2: Complete reviews (between scans) → objectives unlock immediately
# ---------------------------------------------------------------------------

class TestCompleteReviewsUnlocksObjectives:

    def test_objectives_visible_after_completing_reviews(self, monkeypatch):
        """After completing reviews (no reconcile), lifecycle filter lets objectives through."""
        state = _build_state(OBJECTIVE_ISSUES, [_placeholder_dim_entries(k) for k in DIM_KEYS])
        plan = _reconcile(state, empty_plan(), monkeypatch)

        # Complete reviews: update state + purge subjective IDs
        subj_ids = [fid for fid in _queue_ids(state, plan) if fid.startswith("subjective::")]
        _spoof_reviews_complete(state)
        purge_ids(plan, subj_ids)

        # No reconcile — just check the queue
        ids = _queue_ids(state, plan)
        assert "obj-1" in ids
        assert "obj-2" in ids
        # communicate-score hasn't been injected yet (no scan since reviews)
        assert WORKFLOW_COMMUNICATE_SCORE_ID not in ids


# ---------------------------------------------------------------------------
# Test 3: Next scan after reviews → communicate-score + create-plan appear
# ---------------------------------------------------------------------------

class TestScanAfterReviewsInjectsWorkflow:

    def test_workflow_items_injected_on_next_scan(self, monkeypatch):
        """Scan after completing reviews injects communicate-score and create-plan.

        Postflight is exclusive once the scan boundary is crossed:
        score/workflow surfaces first, and only then does execute backlog
        reappear.
        """
        state = _build_state(OBJECTIVE_ISSUES, [_placeholder_dim_entries(k) for k in DIM_KEYS])
        plan = _reconcile(state, empty_plan(), monkeypatch)

        # Complete reviews between scans
        subj_ids = [fid for fid in _queue_ids(state, plan) if fid.startswith("subjective::")]
        _spoof_reviews_complete(state)
        purge_ids(plan, subj_ids)

        # --- Next scan (reconcile) ---
        plan = _reconcile(state, plan, monkeypatch)

        ids = _queue_ids(state, plan)
        assert WORKFLOW_COMMUNICATE_SCORE_ID in ids
        assert WORKFLOW_CREATE_PLAN_ID in ids
        assert ids.index(WORKFLOW_COMMUNICATE_SCORE_ID) < ids.index(WORKFLOW_CREATE_PLAN_ID)

        purge_ids(plan, [WORKFLOW_COMMUNICATE_SCORE_ID, WORKFLOW_CREATE_PLAN_ID])
        ids = _queue_ids(state, plan)
        assert "obj-1" in ids and "obj-2" in ids


# ---------------------------------------------------------------------------
# Phase-order contract: assessment -> score -> triage -> review (after objective drains)
# ---------------------------------------------------------------------------

class TestPhaseOrderInvariant:

    def test_assessment_then_score_when_no_review_followup(self):
        """Endgame queue order is fixed once objective backlog is drained."""
        state = _build_state(
            [],
            [_scored_dim_entries("naming_quality", 80.0)],
            strict_score=76.2,
            overall_score=80.1,
            objective_score=99.9,
        )
        state["subjective_assessments"]["naming_quality"]["needs_review_refresh"] = True
        plan = empty_plan()
        plan["queue_order"] = [
            WORKFLOW_COMMUNICATE_SCORE_ID,
            "triage::observe",
            "subjective::naming_quality",
        ]
        # Mark postflight scan as done so it doesn't block
        plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 1}

        # Subjective follow-up surfaces before workflow items.
        ids = _queue_ids(state, plan)
        assert ids == ["subjective::naming_quality"]

        # After subjective follow-up completion, workflow appears.
        ids = _queue_ids(state, plan)
        state["subjective_assessments"]["naming_quality"]["needs_review_refresh"] = False
        state["subjective_assessments"]["naming_quality"]["score"] = 100.0
        state["dimension_scores"][DIM_DISPLAY["naming_quality"]]["score"] = 100.0
        state["dimension_scores"][DIM_DISPLAY["naming_quality"]]["strict"] = 100.0
        ids = _queue_ids(state, plan)
        assert ids == [WORKFLOW_COMMUNICATE_SCORE_ID]

        # After workflow completion, triage becomes visible.
        purge_ids(plan, [WORKFLOW_COMMUNICATE_SCORE_ID])
        ids = _queue_ids(state, plan)
        assert ids == ["triage::observe"]


# ---------------------------------------------------------------------------
# Test 4: Triage injected when review issues appear
# ---------------------------------------------------------------------------

class TestTriageInjectedOnScan:

    def test_triage_after_review_issues_on_scan(self, monkeypatch):
        """Review-driven triage waits behind score workflow after review import."""
        state = _build_state(OBJECTIVE_ISSUES, [_placeholder_dim_entries(k) for k in DIM_KEYS])
        plan = _reconcile(state, empty_plan(), monkeypatch)

        # Complete reviews between scans
        subj_ids = [fid for fid in _queue_ids(state, plan) if fid.startswith("subjective::")]
        _spoof_reviews_complete(state)
        purge_ids(plan, subj_ids)

        # Add review issues + scan
        _add_review_issues(state)
        plan = _reconcile(state, plan, monkeypatch)

        ids = _queue_ids(state, plan)
        assert not any(fid.startswith("triage::") for fid in ids), ids
        assert WORKFLOW_COMMUNICATE_SCORE_ID in ids
        assert WORKFLOW_CREATE_PLAN_ID in ids

        # Triage stages are still injected in plan order.
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

        # After completing workflow items, triage becomes visible before execute resumes.
        purge_ids(plan, [WORKFLOW_COMMUNICATE_SCORE_ID, WORKFLOW_CREATE_PLAN_ID])
        ids = _queue_ids(state, plan)
        triage_ids = [fid for fid in ids if fid.startswith("triage::")]
        assert len(triage_ids) == len(TRIAGE_STAGE_IDS), ids

        # After triage completes for the live review issue set, the findings surface.
        triage_meta = plan.setdefault("epic_triage_meta", {})
        triage_meta["triaged_ids"] = sorted(
            fid for fid in state["work_items"] if state["work_items"][fid].get("detector") == "review"
        )
        triage_meta["triage_stages"] = {
            stage_id.removeprefix("triage::"): {"confirmed_at": "2026-03-13T00:00:00+00:00"}
            for stage_id in TRIAGE_STAGE_IDS
        }
        purge_ids(plan, TRIAGE_STAGE_IDS)
        ids = _queue_ids(state, plan)
        review_ids = [fid for fid in ids if fid.startswith("review")]
        assert len(review_ids) > 0, f"Expected review issues after triage: {ids}"


# ---------------------------------------------------------------------------
# Test 5: Full lifecycle golden path
# ---------------------------------------------------------------------------

class TestFullLifecycleGoldenPath:

    def test_golden_path(self, monkeypatch):
        """Walk through every lifecycle stage, completing items between scans."""
        state = _build_state(OBJECTIVE_ISSUES, [_placeholder_dim_entries(k) for k in DIM_KEYS])
        plan = empty_plan()

        # ── Scan 1: initial reviews ──
        plan = _reconcile(state, plan, monkeypatch)
        ids = _queue_ids(state, plan)
        assert all(fid.startswith("subjective::") for fid in ids), f"Scan 1: {ids}"
        assert len(ids) == len(DIM_KEYS)

        # ── Between scans: complete reviews ──
        _spoof_reviews_complete(state)
        purge_ids(plan, [fid for fid in ids if fid.startswith("subjective::")])

        ids = _queue_ids(state, plan)
        # Objectives unlocked immediately, no workflow items yet
        assert "obj-1" in ids, f"Post-reviews (no scan): {ids}"
        assert WORKFLOW_COMMUNICATE_SCORE_ID not in ids, f"Post-reviews (no scan): {ids}"

        # ── Scan 2: score workflow surfaces before execute resumes ──
        plan = _reconcile(state, plan, monkeypatch)
        ids = _queue_ids(state, plan)
        assert WORKFLOW_COMMUNICATE_SCORE_ID in ids, f"Scan 2: {ids}"
        assert WORKFLOW_CREATE_PLAN_ID in ids, f"Scan 2: {ids}"

        # ── Complete workflow items; clear cycle baseline so execute resumes ──
        purge_ids(plan, [WORKFLOW_COMMUNICATE_SCORE_ID, WORKFLOW_CREATE_PLAN_ID])
        plan["plan_start_scores"] = {}
        ids = _queue_ids(state, plan)
        assert "obj-1" in ids and "obj-2" in ids, f"Post-workflow: {ids}"

        # ── Scan 3: add review issues + reopen objectives for mid-cycle test ──
        state["work_items"]["obj-1"]["status"] = "open"
        state["work_items"]["obj-2"]["status"] = "open"
        # Place objectives in queue_order so the plan is mid-cycle (non-empty).
        plan["queue_order"] = ["obj-1", "obj-2"]
        _add_review_issues(state)
        plan = _reconcile(state, plan, monkeypatch)
        ids = _queue_ids(state, plan)
        # Mid-cycle guard: triage NOT injected while objective work remains
        assert not any(fid.startswith("triage::") for fid in ids), f"Scan 3: {ids}"
        assert not any(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS), (
            f"Triage should be deferred mid-cycle: {plan['queue_order']}"
        )
        assert "obj-1" in ids and "obj-2" in ids, f"Scan 3: {ids}"

        # ── Complete objective queue → rescan injects triage in plan, but
        #    postflight still starts with workflow items ──
        del state["work_items"]["obj-1"]
        del state["work_items"]["obj-2"]
        plan = _reconcile(state, plan, monkeypatch)
        ids = _queue_ids(state, plan)
        workflow_ids = [fid for fid in ids if fid.startswith("workflow::")]
        assert len(workflow_ids) > 0, f"Expected workflow phase: {ids}"

        # ── Complete workflow items → triage unlocks ──
        purge_ids(plan, workflow_ids)
        ids = _queue_ids(state, plan)
        triage_ids = [fid for fid in ids if fid.startswith("triage::")]
        assert len(triage_ids) == len(TRIAGE_STAGE_IDS), f"Triage unlock: {ids}"
        assert not plan["epic_triage_meta"].get("triage_recommended"), (
            "triage_recommended should be cleared after injection"
        )

        # ── Complete triage → review findings finally become executable ──
        triage_meta = plan.setdefault("epic_triage_meta", {})
        triage_meta["triaged_ids"] = sorted(
            fid for fid in state["work_items"] if state["work_items"][fid].get("detector") == "review"
        )
        triage_meta["triage_stages"] = {
            stage_id.removeprefix("triage::"): {"confirmed_at": "2026-03-13T00:00:00+00:00"}
            for stage_id in TRIAGE_STAGE_IDS
        }
        purge_ids(plan, list(TRIAGE_STAGE_IDS))
        ids = _queue_ids(state, plan)
        assert not any(fid.startswith("triage::") for fid in ids), f"Post-triage: {ids}"
        review_ids = [fid for fid in ids if fid.startswith("review")]
        assert len(review_ids) > 0, f"Expected review execution after triage: {ids}"
