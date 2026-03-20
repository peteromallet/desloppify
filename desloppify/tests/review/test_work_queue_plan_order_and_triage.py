"""Plan-order and triage workflow tests for work queue selection."""

from __future__ import annotations

from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine._work_queue.core import build_work_queue as _build_work_queue


def build_work_queue(state, **kwargs):
    return _build_work_queue(state, options=QueueBuildOptions(**kwargs))


def _issue(
    fid: str,
    *,
    detector: str = "smells",
    file: str = "src/a.py",
    tier: int = 3,
    confidence: str = "medium",
    status: str = "open",
    detail: dict | None = None,
) -> dict:
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": confidence,
        "summary": fid,
        "status": status,
        "detail": detail or {},
    }


def _state(issues: list[dict], *, dimension_scores: dict | None = None) -> dict:
    return {
        "issues": {f["id"]: f for f in issues},
        "dimension_scores": dimension_scores or {},
    }


# ── Cluster collapse ─────────────────────────────────────


def test_collapse_clusters_preserves_order():
    """Cluster meta-item appears at position of first member, not re-sorted."""
    from desloppify.engine._work_queue.plan_order import collapse_clusters

    plan: dict = {
        "queue_order": [],
        "skipped": {},
        "overrides": {},
        "clusters": {},
        "active_cluster": None,
    }
    plan["clusters"]["auto/unused"] = {
        "name": "auto/unused",
        "auto": True,
        "cluster_key": "auto::unused",
        "issue_ids": ["u1", "u2"],
        "description": "Remove 2 unused issues",
        "action": "desloppify autofix unused-imports --dry-run",
        "user_modified": False,
    }

    # Place a non-cluster item first, then the two cluster members
    items = [
        {"id": "other", "kind": "issue", "detector": "structural",
         "confidence": "medium", "detail": {}},
        {"id": "u1", "kind": "issue", "detector": "unused",
         "confidence": "high", "detail": {}, "estimated_impact": 1.0},
        {"id": "u2", "kind": "issue", "detector": "unused",
         "confidence": "high", "detail": {}, "estimated_impact": 1.0},
    ]

    result = collapse_clusters(items, plan)
    # Non-cluster item stays at position 0
    assert result[0]["id"] == "other"
    # Cluster meta-item appears at position 1 (where first member was)
    assert result[1]["kind"] == "cluster"
    assert result[1]["id"] == "auto/unused"
    assert len(result) == 2  # other + cluster


# -- Plan-ordered subjective items surface despite objective backlog --------


def test_plan_ordered_stale_subjective_gated_with_objective_backlog():
    """Stale subjective items are gated by lifecycle filter while objective
    issues exist, even when the plan includes them in queue_order.
    """
    from desloppify.engine._plan.schema import empty_plan

    objective_issues = [
        _issue(f"smells::src/{c}.py::x", detector="smells", tier=3)
        for c in "abcd"
    ]
    state = _state(
        objective_issues,
        dimension_scores={
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 70.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        }
    }

    # Without an explicit queue, pre-triage objective work still blocks stale
    # subjective review items from surfacing.
    queue_no_plan = build_work_queue(state, count=None, include_subjective=True)
    subj_no_plan = [
        i["id"] for i in queue_no_plan["items"] if i["id"].startswith("subjective::")
    ]
    assert subj_no_plan == []

    # With plan that includes the stale dim in queue_order: still gated
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::naming_quality",
        "smells::src/a.py::x",
        "smells::src/b.py::x",
        "smells::src/c.py::x",
        "smells::src/d.py::x",
    ]
    queue_with_plan = build_work_queue(
        state, count=None, include_subjective=True, plan=plan,
    )
    subj_with_plan = [
        i["id"] for i in queue_with_plan["items"] if i["id"].startswith("subjective::")
    ]
    # Stale subjective items gated by lifecycle filter even with plan ordering
    assert len(subj_with_plan) == 0


def test_legacy_force_visible_subjective_is_ignored_during_execute():
    """Legacy force-visible data must not surface subjective work during execute."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [_issue("smells::src/a.py::x", detector="smells", tier=3)],
        dimension_scores={
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 70.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        }
    }

    plan = empty_plan()
    plan["queue_order"] = ["subjective::naming_quality", "smells::src/a.py::x"]
    plan["subjective_defer_meta"] = {
        "force_visible_ids": ["subjective::naming_quality"],
    }

    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    ids = [item["id"] for item in queue["items"]]
    assert ids == ["smells::src/a.py::x"]


def test_triage_pending_does_not_unhide_stale_subjective_items():
    """Triage presence must not bypass stale-subjective gating."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue("smells::src/a.py::x", detector="smells", tier=3),
            _issue("smells::src/b.py::x", detector="smells", tier=3),
        ],
        dimension_scores={
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
            "Error consistency": {
                "score": 72.0,
                "strict": 72.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "error_consistency"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 70.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        },
        "error_consistency": {
            "score": 72.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        },
    }

    plan = empty_plan()
    plan["queue_order"] = [
        "triage::observe",
        "subjective::naming_quality",
        "subjective::error_consistency",
        "smells::src/a.py::x",
        "smells::src/b.py::x",
    ]

    queue = build_work_queue(
        state, count=None, include_subjective=True, plan=plan,
    )
    ids = [item["id"] for item in queue["items"]]
    assert "smells::src/a.py::x" in ids
    assert "smells::src/b.py::x" in ids
    assert "subjective::naming_quality" not in ids
    assert "subjective::error_consistency" not in ids


def test_legacy_force_visible_triage_stage_is_ignored_during_execute():
    """Legacy triage-force data must not surface triage during execute."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state([_issue("smells::src/a.py::x", detector="smells", tier=3)])
    plan = empty_plan()
    plan["queue_order"] = ["triage::observe", "smells::src/a.py::x"]
    plan["epic_triage_meta"] = {"triage_force_visible": True}

    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    ids = [item["id"] for item in queue["items"]]
    assert ids == ["smells::src/a.py::x"]


def test_stale_triage_surfaces_observe_instead_of_empty_queue():
    """When new review findings exist after triage, next should surface triage recovery."""
    from desloppify.engine._plan.schema import empty_plan

    review_issue = _issue(
        "review::.::holistic::design_coherence::needs_triage",
        detector="review",
        tier=4,
        confidence="high",
        detail={"dimension": "design_coherence", "holistic": True},
    )
    state = _state([review_issue])
    state["scan_count"] = 7

    plan = empty_plan()
    plan["queue_order"] = [review_issue["id"]]
    plan["refresh_state"] = {
        "lifecycle_phase": "review_postflight",
        "postflight_scan_completed_at_scan_count": 7,
    }
    plan["epic_triage_meta"] = {
        "triaged_ids": ["review::.::holistic::older::already_triaged"],
        "triage_stages": {
            "observe": {"confirmed_at": "2026-03-13T14:00:00+00:00"},
            "reflect": {"confirmed_at": "2026-03-13T14:01:00+00:00"},
        },
    }

    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    ids = [item["id"] for item in queue["items"]]
    assert ids[0] == "triage::strategize"


def test_postflight_synthetic_queue_keeps_objective_backlog_suppressed():
    """Synthetic-only postflight work must not reactivate implicit execute mode."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue("smells::src/a.py::x", detector="smells", tier=3),
            _issue("smells::src/b.py::x", detector="smells", tier=3),
        ],
        dimension_scores={
            "Naming quality": {
                "score": 82.0,
                "strict": 82.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
            "Design coherence": {
                "score": 73.0,
                "strict": 73.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "design_coherence"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {"score": 82.0},
        "design_coherence": {
            "score": 73.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        },
    }

    plan = empty_plan()
    plan["queue_order"] = ["workflow::communicate-score", "workflow::create-plan"]
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 15}

    queue = build_work_queue(
        state, count=None, include_subjective=True, plan=plan,
    )
    ids = [item["id"] for item in queue["items"]]
    assert all(fid.startswith("subjective::") for fid in ids)


def test_explicit_planned_issue_bypasses_standalone_threshold_filter():
    """Explicit queue_order items must still surface even when naturally filtered."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state([
        _issue(
            "facade::src/a.py",
            detector="facade",
            file="src/a.py",
            tier=2,
            confidence="medium",
        ),
    ])
    plan = empty_plan()
    plan["queue_order"] = ["facade::src/a.py"]

    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)

    assert [item["id"] for item in queue["items"]] == ["facade::src/a.py"]


def test_triaged_review_findings_stay_postflight_while_objective_work_remains():
    """Completed triage should not mix review findings into execute."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue("smells::src/a.py::x", detector="smells", tier=3),
            _issue(
                "review::src/a.py::naming",
                detector="review",
                tier=1,
                confidence="high",
                detail={"dimension": "naming_quality"},
            ),
        ]
    )
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["queue_order"] = ["review::src/a.py::naming", "smells::src/a.py::x"]
    plan["epic_triage_meta"] = {
        "triaged_ids": ["review::src/a.py::naming"],
        "last_completed_at": "2026-03-13T00:00:00+00:00",
    }
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 1}

    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=False,
            plan=plan,
        ),
    )
    ids = [item["id"] for item in queue["items"]]
    assert ids == ["smells::src/a.py::x"]


def test_postflight_assessment_precedes_review_findings():
    """Postflight subjective reruns gate later review execution work."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue(
                "review::src/a.py::naming",
                detector="review",
                tier=1,
                confidence="high",
                detail={"dimension": "naming_quality"},
            ),
            _issue(
                "subjective_review::naming_quality",
                detector="subjective_review",
                tier=1,
                confidence="high",
                detail={"dimension": "naming_quality"},
            ),
        ],
        dimension_scores={
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 70.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        }
    }
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["epic_triage_meta"] = {
        "triaged_ids": ["review::src/a.py::naming"],
        "last_completed_at": "2026-03-13T00:00:00+00:00",
    }
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 1}

    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=True,
            plan=plan,
        ),
    )
    ids = [item["id"] for item in queue["items"]]
    # Subjective dimension item is suppressed when review issues cover the
    # same dimension — the assessment request alone surfaces.
    assert ids == ["subjective_review::naming_quality"]


def test_execution_queue_excludes_unplanned_objective_items():
    """Unplanned objective items don't appear in execution — only planned items do."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue("smells::src/a.py::planned", detector="smells"),
            _issue("smells::src/b.py::unplanned", detector="smells"),
        ]
    )
    plan = empty_plan()
    plan["queue_order"] = ["smells::src/a.py::planned"]

    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=False,
            plan=plan,
        ),
    )
    ids = [item["id"] for item in queue["items"]]
    assert ids == ["smells::src/a.py::planned"]


def test_backlog_queue_excludes_execution_objective_items():
    """Backlog should exclude execution items and synthetic workflow helpers."""
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue("smells::src/a.py::planned", detector="smells"),
            _issue("smells::src/b.py::unplanned", detector="smells"),
        ]
    )
    plan = empty_plan()
    plan["queue_order"] = ["smells::src/a.py::planned"]

    queue = build_backlog_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=False,
            plan=plan,
        ),
    )
    ids = [item["id"] for item in queue["items"]]
    assert "smells::src/a.py::planned" not in ids
    assert "smells::src/b.py::unplanned" in ids
    assert "workflow::run-scan" not in ids


def test_unplanned_objective_items_dont_block_postflight():
    """Unplanned objective items don't keep the system in EXECUTE phase.

    When all planned work drains, unplanned objective items should not block
    phase transitions to postflight work. The has_unplanned_objective_blockers
    flag is still set for informational purposes.

    The split only applies when the plan has at least one tracked objective
    (i.e. post-triage). Pre-triage plans treat all objectives as planned.
    """
    from desloppify.engine._plan.schema import empty_plan

    state = _state(
        [
            _issue("smells::src/a.py::planned", detector="smells"),
            _issue("smells::src/b.py::unplanned", detector="smells"),
        ],
        dimension_scores={
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 70.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        }
    }

    # Plan has one tracked objective — simulates post-triage state
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 75.0}
    plan["queue_order"] = ["smells::src/a.py::planned"]

    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=True,
            plan=plan,
        ),
    )
    ids = [item["id"] for item in queue["items"]]
    # Only planned item appears — unplanned item does NOT block
    assert ids == ["smells::src/a.py::planned"]
    assert "smells::src/b.py::unplanned" not in ids


# ── Lifecycle filter runs after plan_presort ───────────


def test_skipped_objective_items_dont_block_subjective():
    """Plan-skipped objective items are removed before lifecycle filter,
    so they don't block subjective reassessment items.
    """
    from desloppify.engine._plan.schema import empty_plan

    objective_issues = [
        _issue(f"smells::src/{c}.py::x", detector="smells", tier=3)
        for c in "abcd"
    ]
    state = _state(
        objective_issues,
        dimension_scores={
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 70.0,
            "needs_review_refresh": True,
            "stale_since": "2026-01-01T00:00:00+00:00",
        }
    }

    # Skip ALL objective issues in the plan
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::naming_quality",
        "smells::src/a.py::x",
        "smells::src/b.py::x",
        "smells::src/c.py::x",
        "smells::src/d.py::x",
    ]
    plan["skipped"] = {
        "smells::src/a.py::x": {"reason": "deferred"},
        "smells::src/b.py::x": {"reason": "deferred"},
        "smells::src/c.py::x": {"reason": "deferred"},
        "smells::src/d.py::x": {"reason": "deferred"},
    }

    queue = build_work_queue(
        state, count=None, include_subjective=True, plan=plan,
    )
    ids = [i["id"] for i in queue["items"]]
    # All objective items skipped → lifecycle filter sees no objective work
    # → but deferred disposition precedes subjective in lifecycle
    assert "workflow::deferred-disposition" in ids
    # Subjective items are gated behind deferred disposition
    subj_ids = [i for i in ids if i.startswith("subjective::")]
    assert len(subj_ids) == 0


# ── Wontfix / resolved issues excluded (#193) ──────────


def test_wontfixed_issues_excluded_from_queue():
    """Issues with status 'wontfix' never appear in the default queue.

    Regression test for #193: wontfixed issues were leaking into the
    auto-generated queue because filtering was spread across multiple
    modules and easy to miss.
    """
    state = _state(
        [
            _issue("a", status="open"),
            _issue("b", status="wontfix"),
            _issue("c", status="fixed"),
            _issue("d", status="open"),
        ]
    )

    queue = build_backlog_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=False,
        ),
    )
    ids = {item["id"] for item in queue["items"]}
    assert "a" in ids
    assert "d" in ids
    assert "b" not in ids  # wontfix excluded
    assert "c" not in ids  # fixed excluded


def test_wontfixed_issues_excluded_with_plan():
    """Wontfixed issues stay out even when a plan is active."""
    from desloppify.engine._plan.schema import empty_plan

    plan = empty_plan()
    plan["queue_order"] = ["a", "b", "c", "d"]

    state = _state(
        [
            _issue("a", status="open"),
            _issue("b", status="wontfix"),
            _issue("c", status="fixed"),
            _issue("d", status="open"),
        ]
    )

    queue = build_work_queue(state, count=None, include_subjective=False, plan=plan)
    ids = {item["id"] for item in queue["items"]}
    assert "a" in ids
    assert "d" in ids
    assert "b" not in ids
    assert "c" not in ids


# ── Triage lifecycle ordering ────────────────────────────────


def test_triage_stages_hidden_during_initial_reviews():
    """Phase 1 hides triage stages and workflow actions — only initial reviews visible."""
    objective_issues = [
        _issue(f"smells::src/{c}.py::x", detector="smells", tier=3)
        for c in "ab"
    ]
    state = _state(
        objective_issues,
        dimension_scores={
            "Naming quality": {
                "score": 0.0,
                "strict": 0.0,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": "naming_quality",
                        "placeholder": True,
                    },
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {"score": 0.0, "placeholder": True}
    }

    # Inject a triage stage and a workflow action into queue_order so they
    # would appear if the lifecycle filter didn't hide them.
    plan = {
        "queue_order": [
            "triage::observe",
            "workflow::communicate-score",
            "subjective::naming_quality",
        ],
        "queue_skipped": {},
    }
    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    ids = [item["id"] for item in queue["items"]]

    # Only initial review visible — triage and workflow hidden
    assert ids == ["subjective::naming_quality"]


def test_subjective_phase_precedes_score_and_triage_when_objective_drained():
    """Subjective reruns stay ahead of workflow and triage once postflight begins."""
    state = _state(
        [],
        dimension_scores={
            "Naming quality": {
                "score": 80.0,
                "strict": 80.0,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": "naming_quality",
                        "placeholder": False,
                    },
                },
            },
        },
    )
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 80.0,
            "placeholder": False,
            "needs_review_refresh": True,
        }
    }

    plan = {
        "queue_order": [
            "workflow::communicate-score",
            "triage::observe",
            "subjective::naming_quality",
        ],
        "queue_skipped": {},
        "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
    }
    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    ids = [item["id"] for item in queue["items"]]
    assert ids == ["subjective::naming_quality"]


def test_triage_stages_sort_after_workflow_in_natural_ranking():
    """In natural ranking (no plan), workflow actions sort before triage stages."""
    from desloppify.engine._work_queue.ranking import item_sort_key

    workflow_item = {
        "id": "workflow::communicate-score",
        "kind": "workflow_action",
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
    }
    triage_item = {
        "id": "triage::observe",
        "kind": "workflow_stage",
        "tier": 1,
        "confidence": "high",
        "detector": "triage",
        "file": ".",
        "detail": {"stage": "observe"},
        "is_blocked": False,
    }

    wf_key = item_sort_key(workflow_item)
    tr_key = item_sort_key(triage_item)
    assert wf_key < tr_key, "workflow actions should sort before triage stages"


def test_fresh_under_target_postflight_review_preempts_persisted_workflow() -> None:
    """Fresh below-target postflight review surfaces before queued workflow items."""
    state = _state(
        [],
        dimension_scores={
            "Naming quality": {
                "score": 82.0,
                "strict": 82.0,
                "failing": 0,
                "checks": 1,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": "naming_quality",
                        "placeholder": False,
                    },
                },
            },
        },
    )
    state["scan_count"] = 19
    state["subjective_assessments"] = {
        "naming_quality": {
            "score": 82.0,
            "placeholder": False,
        }
    }
    plan = {
        "queue_order": ["workflow::communicate-score", "workflow::create-plan"],
        "queue_skipped": {},
        "refresh_state": {
            "postflight_scan_completed_at_scan_count": 19,
            "lifecycle_phase": "workflow_postflight",
        },
    }

    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    assert [item["id"] for item in queue["items"]] == ["subjective::naming_quality"]

    plan["refresh_state"]["subjective_review_completed_at_scan_count"] = 19
    queue = build_work_queue(state, count=None, include_subjective=True, plan=plan)
    assert [item["id"] for item in queue["items"]] == [
        "workflow::communicate-score",
        "workflow::create-plan",
    ]
