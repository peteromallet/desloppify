import json
from functools import partial
from types import SimpleNamespace

import pytest

from desloppify.app.commands.review.importing import cmd
from desloppify.app.commands.review.importing.flags import ReviewImportConfig
from desloppify.engine._state import merge as merge_mod
from desloppify.engine._state.schema import empty_state
from desloppify.intelligence.review.importing.assessments import store_assessments
from desloppify.intelligence.review.importing.holistic import import_holistic_issues

ASSESS = "2026-10-16T14:34:55+00:00"
AUDIT = "2026-10-16T14:34:56+00:00"


def issue(number=1):
    return dict(
        id=f"structural::large{number}.py",
        detector="structural",
        file=f"large{number}.py",
        tier=3,
        confidence="high",
        summary="large file",
        detail={"loc": 500},
        status="open",
        note=None,
        first_seen=ASSESS,
        last_seen=ASSESS,
        resolved_at=None,
        reopen_count=0,
    )


@pytest.fixture
def do_trusted_import(monkeypatch, tmp_path):
    monkeypatch.setattr(cmd, "has_living_plan", lambda *args: False)
    monkeypatch.setattr(cmd, "sync_plan_after_import", lambda *args, **kwargs: None)
    monkeypatch.setattr(cmd, "_refresh_scorecard_after_import", lambda **kwargs: False)
    monkeypatch.setattr(cmd, "report_review_import_outcome", lambda **kwargs: None)
    monkeypatch.setattr(cmd, "utc_now", lambda: AUDIT)
    monkeypatch.setattr(merge_mod, "utc_now", lambda: ASSESS)
    monkeypatch.setattr(
        cmd,
        "import_holistic_issues",
        partial(
            import_holistic_issues, utc_now_fn=lambda: ASSESS, project_root=tmp_path
        ),
    )

    def run(state, assessments):
        payload = tmp_path / "review.json"
        payload.write_text(
            json.dumps(
                {
                    "issues": [],
                    "assessments": assessments,
                    "dimension_notes": {
                        d: {
                            "evidence": [
                                "synthetic fixture intentionally scores the reviewed dimension"
                            ]
                        }
                        for d in assessments
                    },
                }
            )
        )
        cmd.do_import(
            str(payload),
            state,
            SimpleNamespace(name="python"),
            tmp_path / "input-state.json",
            import_config=ReviewImportConfig(trusted_assessment_source=True),
        )
        return state

    # Retain the real persistence behavior, redirected to isolated files.
    original_persist = cmd._persist_import_state

    def persist(**kwargs):
        kwargs["state_file"] = tmp_path / "saved-state.json"
        return original_persist(**kwargs)

    monkeypatch.setattr(cmd, "_persist_import_state", persist)
    return run


def baseline():
    state = empty_state()
    state["last_scan"] = "2026-10-16T14:00:00+00:00"
    return state


@pytest.mark.parametrize("clock_gap", [False, True])
def test_actual_trusted_import_survives_first_mechanical_scan(
    do_trusted_import, monkeypatch, clock_gap
):
    if not clock_gap:
        monkeypatch.setattr(cmd, "utc_now", lambda: ASSESS)
    state = do_trusted_import(baseline(), {"design_coherence": 90})
    assert state["subjective_assessments"]["design_coherence"]["assessed_at"] == ASSESS
    merge_mod.merge_scan(state, [issue()])
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )


def test_partial_import_does_not_protect_unreviewed_dimension(do_trusted_import):
    state = baseline()
    state["subjective_assessments"] = {
        "design_coherence": {"score": 70, "assessed_at": "2026-10-15T00:00:00+00:00"}
    }
    do_trusted_import(state, {"naming_quality": 90})
    merge_mod.merge_scan(state, [issue()])
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_later_mechanical_scan_stales_previously_fresh_review(do_trusted_import):
    state = do_trusted_import(baseline(), {"design_coherence": 90})
    merge_mod.merge_scan(state, [issue()])
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )
    merge_mod.merge_scan(state, [issue(), issue(2)])
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_untrusted_overwrite_same_second_is_not_protected(do_trusted_import):
    state = do_trusted_import(baseline(), {"design_coherence": 90})
    store_assessments(
        state, {"design_coherence": 60}, "holistic", utc_now_fn=lambda: ASSESS
    )
    merge_mod.merge_scan(state, [issue()])
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_repeated_scan_of_already_verified_absent_issue_is_fresh(do_trusted_import):
    state = baseline()
    merge_mod.merge_scan(state, [issue()])
    state["work_items"][issue()["id"]]["status"] = "fixed"
    state["work_items"][issue()["id"]]["resolution_attestation"] = {
        "scan_verified": True,
        "scan_verified_at": ASSESS,
        "scan_verification_text": "Absent from detector output in latest scan",
    }
    do_trusted_import(state, {"design_coherence": 90})
    options = merge_mod.MergeScanOptions(
        potentials={"structural": 1}, force_resolve=True
    )
    merge_mod.merge_scan(state, [], options)
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )
    merge_mod.merge_scan(state, [], options)
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )


def test_review_import_does_not_corroborate_unrun_mechanical_detector(
    do_trusted_import,
):
    state = baseline()
    merge_mod.merge_scan(state, [issue()])
    state["work_items"][issue()["id"]]["status"] = "fixed"
    do_trusted_import(state, {"design_coherence": 90})
    assert (
        not state["work_items"][issue()["id"]]
        .get("resolution_attestation", {})
        .get("scan_verified")
    )
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )
