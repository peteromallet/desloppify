"""Direct regressions for consistent subjective queue thresholds."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.app.commands.plan.queue_render as plan_queue_mod
import desloppify.app.commands.resolve.queue_guard as queue_guard_mod


def test_plan_queue_context_uses_runtime_target_strict(monkeypatch) -> None:
    captured = {}

    def capture_build(_state, *, options):
        captured["context"] = options.context
        captured["options"] = options
        return {"items": []}

    monkeypatch.setattr(plan_queue_mod, "build_execution_queue", capture_build)
    plan_queue_mod._build_queue_items(
        state={},
        plan={"queue_order": []},
        include_skipped=False,
        effective_cluster=None,
        config={"target_strict_score": 85},
    )

    assert captured["context"].target_strict == 85
    assert captured["options"].subjective_threshold == 85


def test_resolve_guard_context_uses_project_target_strict(monkeypatch) -> None:
    plan = {"queue_order": ["review::first"], "clusters": {}, "active_cluster": None}
    access = SimpleNamespace(
        plan=plan,
        degraded=False,
        usable_plan=lambda **_kwargs: plan,
    )
    captured = {}

    monkeypatch.setattr(queue_guard_mod, "load_config", lambda: {"target_strict_score": 85})
    monkeypatch.setattr(queue_guard_mod, "load_resolve_plan_access", lambda: access)

    def capture_build(_state, *, options):
        captured["context"] = options.context
        captured["options"] = options
        return {"items": []}

    monkeypatch.setattr(queue_guard_mod, "build_work_queue", capture_build)
    assert queue_guard_mod._check_queue_order_guard({}, ["review::first"], "fixed") is False
    assert captured["context"].target_strict == 85
    assert captured["options"].subjective_threshold == 85


def _healthy_dimension_with_scene_work():
    issue_ids = ["scene::src/a.py::one", "scene::src/a.py::two"]
    issues = {
        issue_id: {
            "id": issue_id,
            "detector": "scene",
            "file": "src/a.py",
            "tier": 3,
            "confidence": "high",
            "summary": issue_id,
            "status": "open",
            "detail": {},
        }
        for issue_id in issue_ids
    }
    state = {
        "issues": issues,
        "work_items": issues,
        "scan_count": 5,
        "dimension_scores": {
            "Mid elegance": {
                "score": 89,
                "strict": 89,
                "failing": 1,
                "checks": 1,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": "mid_level_elegance",
                    },
                },
            },
        },
    }
    plan = {
        "queue_order": issue_ids,
        "clusters": {
            "scene-cluster": {
                "issue_ids": issue_ids,
                "auto": False,
                "description": "two scene tasks",
                "action_steps": [],
            },
        },
        "overrides": {
            issue_id: {"cluster": "scene-cluster"}
            for issue_id in issue_ids
        },
        "active_cluster": None,
        "refresh_state": {
            "lifecycle_phase": "plan",
            "postflight_scan_completed_at_scan_count": 5,
        },
    }
    return state, plan


def test_plan_queue_uses_target_threshold_for_real_queue_selection() -> None:
    state, plan = _healthy_dimension_with_scene_work()

    items, _queue = plan_queue_mod._build_queue_items(
        state=state,
        plan=plan,
        include_skipped=False,
        effective_cluster=None,
        config={"target_strict_score": 85},
    )

    assert items[0]["id"] == "scene-cluster"
    assert all(item.get("kind") != "subjective_dimension" for item in items)


def test_resolve_guard_uses_target_threshold_for_real_queue_selection(monkeypatch) -> None:
    state, plan = _healthy_dimension_with_scene_work()
    access = SimpleNamespace(usable_plan=lambda **_kwargs: plan)
    monkeypatch.setattr(queue_guard_mod, "load_config", lambda: {"target_strict_score": 85})
    monkeypatch.setattr(queue_guard_mod, "load_resolve_plan_access", lambda: access)

    assert queue_guard_mod._check_queue_order_guard(
        state,
        ["scene-cluster"],
        "fixed",
    ) is False
