"""Direct tests for resolve living-plan helpers."""

from __future__ import annotations

import argparse

import desloppify.app.commands.resolve.living_plan as living_plan_mod


def _args(*, status: str = "fixed", note: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(status=status, note=note)


def test_capture_cluster_context_returns_remaining_counts() -> None:
    plan = {
        "overrides": {
            "a": {"cluster": "epic/x"},
            "b": {"cluster": "epic/x"},
        },
        "clusters": {"epic/x": {"issue_ids": ["a", "b", "c"]}},
    }
    ctx = living_plan_mod.capture_cluster_context(plan, ["a", "b"])
    assert ctx.cluster_name == "epic/x"
    assert ctx.cluster_completed is False
    assert ctx.cluster_remaining == 1

    done_ctx = living_plan_mod.capture_cluster_context(plan, ["a", "b", "c"])
    assert done_ctx.cluster_completed is True
    assert done_ctx.cluster_remaining == 0


def test_completed_cluster_names_returns_all_empty_clusters() -> None:
    plan = {
        "overrides": {
            "a": {"cluster": "epic/x"},
            "b": {"cluster": "epic/x"},
            "c": {"cluster": "epic/y"},
            "d": {"cluster": "epic/y"},
        },
        "clusters": {
            "epic/x": {"issue_ids": ["a", "b"]},
            "epic/y": {"issue_ids": ["c", "d"]},
        },
    }

    assert living_plan_mod._completed_cluster_names(plan, ["a", "b", "c", "d"]) == [
        "epic/x",
        "epic/y",
    ]


def test_update_living_plan_after_resolve_no_living_plan(monkeypatch) -> None:
    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: False)
    plan, ctx = living_plan_mod.update_living_plan_after_resolve(
        args=_args(),
        all_resolved=["x"],
        attestation="attest",
    )
    assert plan is None
    assert ctx.cluster_name is None


def test_update_living_plan_after_resolve_fixed_flow(monkeypatch, capsys) -> None:
    plan = {
        "queue_order": ["a"],
        "overrides": {"a": {"cluster": "epic/a"}},
        "clusters": {"epic/a": {"issue_ids": ["a"]}},
    }
    calls: list[str] = []
    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: True)
    monkeypatch.setattr(living_plan_mod, "load_plan", lambda _p=None: plan)
    monkeypatch.setattr(living_plan_mod, "purge_ids", lambda _plan, _ids: 1)
    monkeypatch.setattr(
        living_plan_mod, "auto_complete_steps", lambda _plan: ["step complete"]
    )
    monkeypatch.setattr(
        living_plan_mod, "append_log_entry", lambda *_a, **_k: calls.append("log")
    )
    monkeypatch.setattr(
        living_plan_mod, "add_uncommitted_issues", lambda *_a, **_k: calls.append("add")
    )
    monkeypatch.setattr(
        living_plan_mod,
        "invalidate_postflight_scan",
        lambda *_a, **_k: calls.append("clear"),
    )
    monkeypatch.setattr(
        living_plan_mod, "save_plan", lambda _plan, _p=None: calls.append("save")
    )

    updated_plan, ctx = living_plan_mod.update_living_plan_after_resolve(
        args=_args(status="fixed", note="done"),
        all_resolved=["a"],
        attestation="attest",
    )

    out = capsys.readouterr().out
    assert updated_plan is plan
    assert ctx.cluster_completed is True
    assert "step complete" in out
    assert "Plan updated: 1 item(s)" in out
    assert calls.count("log") == 2  # resolve + cluster_done
    assert "add" in calls and "clear" in calls and "save" in calls


def test_update_living_plan_after_resolve_marks_all_completed_clusters_done(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": ["a", "b"],
        "active_cluster": "epic/y",
        "overrides": {
            "a": {"cluster": "epic/x"},
            "b": {"cluster": "epic/y"},
        },
        "clusters": {
            "epic/x": {"issue_ids": ["a"], "execution_status": "active"},
            "epic/y": {"issue_ids": ["b"], "execution_status": "active"},
        },
    }
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: True)
    monkeypatch.setattr(living_plan_mod, "load_plan", lambda _p=None: plan)
    monkeypatch.setattr(living_plan_mod, "purge_ids", lambda _plan, _ids: 2)
    monkeypatch.setattr(living_plan_mod, "auto_complete_steps", lambda _plan: [])
    monkeypatch.setattr(
        living_plan_mod,
        "append_log_entry",
        lambda _plan, event, **kwargs: calls.append((event, kwargs.get("cluster_name"))),
    )
    monkeypatch.setattr(
        living_plan_mod, "add_uncommitted_issues", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        living_plan_mod, "invalidate_postflight_scan", lambda *_a, **_k: None
    )
    monkeypatch.setattr(living_plan_mod, "save_plan", lambda _plan, _p=None: None)

    updated_plan, ctx = living_plan_mod.update_living_plan_after_resolve(
        args=_args(status="fixed", note="done"),
        all_resolved=["a", "b"],
        attestation="attest",
    )

    assert updated_plan is plan
    assert ctx.cluster_name == "epic/x"
    assert updated_plan["clusters"]["epic/x"]["execution_status"] == "done"
    assert updated_plan["clusters"]["epic/y"]["execution_status"] == "done"
    assert updated_plan["active_cluster"] is None
    assert calls == [
        ("resolve", None),
        ("cluster_done", "epic/x"),
        ("cluster_done", "epic/y"),
    ]


def test_update_living_plan_after_resolve_reconciles_when_queue_drains(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": ["workflow::create-plan"],
        "overrides": {},
        "clusters": {},
    }
    state = {"config": {"target_strict_score": 97}}
    seen: list[object] = []

    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: True)
    monkeypatch.setattr(living_plan_mod, "load_plan", lambda _p=None: plan)

    def _purge(_plan, _ids):
        _plan["queue_order"] = []
        return 1

    monkeypatch.setattr(living_plan_mod, "purge_ids", _purge)
    monkeypatch.setattr(living_plan_mod, "auto_complete_steps", lambda _plan: [])
    monkeypatch.setattr(living_plan_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        living_plan_mod, "add_uncommitted_issues", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        living_plan_mod, "invalidate_postflight_scan", lambda *_a, **_k: None
    )
    monkeypatch.setattr(living_plan_mod, "save_plan", lambda _plan, _p=None: None)
    monkeypatch.setattr(living_plan_mod, "live_planned_queue_empty", lambda _plan: True)
    monkeypatch.setattr(
        living_plan_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 97.0,
    )
    monkeypatch.setattr(
        living_plan_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            ("reconcile", target_strict, _state)
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": False, "lifecycle_phase": "execute"},
        )(),
    )

    living_plan_mod.update_living_plan_after_resolve(
        args=_args(status="fixed", note="done"),
        all_resolved=["workflow::create-plan"],
        attestation="attest",
        state=state,
    )

    assert ("target", state["config"]) in seen
    assert ("reconcile", 97.0, state) in seen


def test_update_living_plan_after_resolve_skips_reconcile_without_state(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": ["a"],
        "overrides": {},
        "clusters": {},
    }
    seen: list[str] = []

    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: True)
    monkeypatch.setattr(living_plan_mod, "load_plan", lambda _p=None: plan)
    monkeypatch.setattr(living_plan_mod, "purge_ids", lambda _plan, _ids: 1)
    monkeypatch.setattr(living_plan_mod, "auto_complete_steps", lambda _plan: [])
    monkeypatch.setattr(living_plan_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        living_plan_mod, "add_uncommitted_issues", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        living_plan_mod, "invalidate_postflight_scan", lambda *_a, **_k: None
    )
    monkeypatch.setattr(living_plan_mod, "save_plan", lambda _plan, _p=None: None)
    monkeypatch.setattr(living_plan_mod, "live_planned_queue_empty", lambda _plan: True)
    monkeypatch.setattr(
        living_plan_mod,
        "reconcile_plan",
        lambda *_a, **_k: seen.append("reconcile"),
    )

    living_plan_mod.update_living_plan_after_resolve(
        args=_args(status="fixed", note="done"),
        all_resolved=["a"],
        attestation="attest",
        state=None,
    )

    assert seen == []


def test_update_living_plan_after_resolve_reconciles_once_when_invalidated_and_drained(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": ["a"],
        "overrides": {},
        "clusters": {},
    }
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: True)
    monkeypatch.setattr(living_plan_mod, "load_plan", lambda _p=None: plan)

    def _purge(_plan, _ids):
        _plan["queue_order"] = []
        return 1

    monkeypatch.setattr(living_plan_mod, "purge_ids", _purge)
    monkeypatch.setattr(living_plan_mod, "auto_complete_steps", lambda _plan: [])
    monkeypatch.setattr(living_plan_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        living_plan_mod, "add_uncommitted_issues", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        living_plan_mod, "invalidate_postflight_scan", lambda *_a, **_k: True
    )
    monkeypatch.setattr(living_plan_mod, "save_plan", lambda _plan, _p=None: None)
    monkeypatch.setattr(living_plan_mod, "live_planned_queue_empty", lambda _plan: True)
    monkeypatch.setattr(
        living_plan_mod,
        "target_strict_score_from_config",
        lambda config: seen.append(("target", config)) or 97.0,
    )
    monkeypatch.setattr(
        living_plan_mod,
        "reconcile_plan",
        lambda _plan, _state, *, target_strict: seen.append(
            ("reconcile", target_strict)
        )
        or type(
            "Result",
            (),
            {"lifecycle_phase_changed": False, "lifecycle_phase": "execute"},
        )(),
    )

    living_plan_mod.update_living_plan_after_resolve(
        args=_args(status="fixed", note="done"),
        all_resolved=["a"],
        attestation="attest",
        state={"config": {"target_strict_score": 97}},
    )

    assert seen == [
        ("target", {"target_strict_score": 97}),
        ("reconcile", 97.0),
    ]


def test_update_living_plan_after_resolve_handles_plan_exceptions(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(living_plan_mod, "has_living_plan", lambda _p=None: True)
    monkeypatch.setattr(
        living_plan_mod,
        "load_plan",
        lambda _p=None: (_ for _ in ()).throw(OSError("boom")),
    )
    monkeypatch.setattr(living_plan_mod, "PLAN_LOAD_EXCEPTIONS", (OSError,))

    plan, ctx = living_plan_mod.update_living_plan_after_resolve(
        args=_args(),
        all_resolved=["a"],
        attestation="attest",
    )

    err = capsys.readouterr().err
    assert plan is None
    assert ctx.cluster_name is None
    assert "could not be loaded" in err
