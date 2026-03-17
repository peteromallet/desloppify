"""Direct tests for review importing support modules."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import desloppify.app.commands.review.importing.cmd as import_cmd_mod
import desloppify.app.commands.review.importing.flags as flags_mod
import desloppify.app.commands.review.importing.output as import_output_mod
import desloppify.app.commands.review.importing.plan_sync as plan_sync_mod
import desloppify.app.commands.review.importing.results as results_mod
import desloppify.engine._plan.constants as plan_constants_mod
import desloppify.intelligence.review.importing.holistic as holistic_import_mod
from desloppify.state import empty_state as build_empty_state


def _empty_visibility_policy() -> SimpleNamespace:
    return SimpleNamespace(
        has_objective_backlog=False,
        unscored_ids=frozenset(),
        stale_ids=frozenset(),
        under_target_ids=frozenset(),
    )


def _score_snapshot(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _no_changes(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(changes=False, **kwargs)


def _patch_basic_plan_sync_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: dict,
) -> None:
    monkeypatch.setattr(plan_sync_mod, "has_living_plan", lambda _path=None: True)
    monkeypatch.setattr(plan_sync_mod, "load_plan", lambda _path=None: plan)
    monkeypatch.setattr(plan_sync_mod, "save_plan", lambda _plan, _path=None: None)
    monkeypatch.setattr(
        plan_sync_mod,
        "live_planned_queue_empty",
        lambda _plan: True,
    )
    monkeypatch.setattr(
        plan_sync_mod,
        "reconcile_plan",
        lambda _plan, _state, target_strict: plan_sync_mod.ReconcileResult(),
    )
    monkeypatch.setattr(
        plan_sync_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode, **_kwargs: _no_changes(),
    )
    monkeypatch.setattr(plan_sync_mod, "append_log_entry", lambda *_a, **_k: None)


def _sync_request(**kwargs) -> object:
    return plan_sync_mod.PlanImportSyncRequest(**kwargs)


def test_plan_sync_uses_narrow_plan_facades() -> None:
    src = inspect.getsource(plan_sync_mod)
    assert "from desloppify.engine.plan import" not in src
    assert "desloppify.engine._plan.persistence" in src
    assert "@dataclass(frozen=True)\nclass PlanImportSyncRequest" in src


def test_flags_validation_and_assessment_state_helpers() -> None:
    with pytest.raises(flags_mod.ImportFlagValidationError):
        flags_mod.validate_import_flag_combos(
            attested_external=True,
            allow_partial=False,
            override_enabled=True,
            override_attest="ok",
        )
    with pytest.raises(flags_mod.ImportFlagValidationError):
        flags_mod.validate_import_flag_combos(
            attested_external=False,
            allow_partial=True,
            override_enabled=True,
            override_attest="ok",
        )

    keys = flags_mod.imported_assessment_keys(
        {"assessments": {"Naming Quality": 70, "": 50}}
    )
    assert keys == {"naming_quality"}

    state = {
        "scan_count": 4,
        "subjective_assessments": {"naming_quality": {"source": "holistic"}},
    }
    marked = flags_mod.mark_manual_override_assessments_provisional(
        state,
        assessment_keys={"naming_quality"},
    )
    assert marked == 1
    assert state["subjective_assessments"]["naming_quality"]["provisional_until_scan"] == 5

    cleared = flags_mod.clear_provisional_override_flags(
        state,
        assessment_keys={"naming_quality"},
    )
    assert cleared == 1
    assert state["subjective_assessments"]["naming_quality"]["source"] == "holistic"


def test_sync_plan_after_import_no_living_plan(monkeypatch) -> None:
    monkeypatch.setattr(plan_sync_mod, "has_living_plan", lambda _path=None: False)
    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )


def test_sync_plan_after_import_marks_subjective_review_complete_for_current_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {
        "queue_order": [],
        "refresh_state": {"postflight_scan_completed_at_scan_count": 7},
    }
    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)

    state = {
        "scan_count": 7,
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
        },
    }
    outcome = plan_sync_mod.sync_plan_after_import(
        state=state,
        diff={"new": 0, "reopened": 0, "auto_resolved": 0},
        assessment_mode="trusted_internal",
        request=_sync_request(
            import_payload={"assessments": {"Naming Quality": 82}},
        ),
    )

    assert outcome.status == "synced"
    assert plan["refresh_state"]["subjective_review_completed_at_scan_count"] == 7


def test_print_review_import_sync_reports_new_ids_and_triage_commands(capsys) -> None:
    state = {
        "issues": {
            "review::alpha": {"summary": "Alpha summary"},
            "review::beta": {"summary": "Beta summary"},
        }
    }
    result = SimpleNamespace(
        new_ids={"review::alpha", "review::beta"},
        stale_pruned_from_queue=["review::stale"],
        triage_injected=True,
    )

    plan_sync_mod._print_review_import_sync(
        state,
        result,
        workflow_injected=False,
        triage_injected=True,
        outcome=plan_sync_mod.PlanImportSyncOutcome(status="synced"),
    )

    out = capsys.readouterr().out
    assert "2 new review work item(s) added to queue" in out
    assert "Alpha summary" in out
    assert "stale review work item(s) removed from queue" in out
    assert plan_sync_mod.TRIAGE_CMD_RUN_STAGES_CODEX in out
    assert plan_sync_mod.TRIAGE_CMD_RUN_STAGES_CLAUDE in out


def test_print_open_review_summary_avoids_duplicate_count_phrase(capsys) -> None:
    next_command = import_output_mod.print_open_review_summary(
        {
            "issues": {
                "review::alpha": {"status": "open", "detector": "review"},
                "review::beta": {"status": "open", "detector": "review"},
            }
        },
        colorize_fn=lambda text, _tone: text,
    )

    out = capsys.readouterr().out
    assert "2 review work items open total" in out
    assert "(2 review work items open total)" not in out
    assert next_command == "desloppify show review --status open"


def test_sync_plan_after_import_scopes_living_plan_to_state_file(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}

    def fake_plan_path_for_state(state_path):
        seen["state_path"] = state_path
        return tmp_path / "plan.json"

    def fake_has_living_plan(path=None):
        seen["has_living_plan_path"] = path
        return False

    monkeypatch.setattr(plan_sync_mod, "plan_path_for_state", fake_plan_path_for_state)
    monkeypatch.setattr(plan_sync_mod, "has_living_plan", fake_has_living_plan)

    state_file = tmp_path / "state.json"
    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
        request=_sync_request(state_file=state_file),
    )

    assert seen["state_path"] == state_file
    assert seen["has_living_plan_path"] == tmp_path / "plan.json"


def test_sync_plan_after_import_handles_plan_exceptions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(plan_sync_mod, "has_living_plan", lambda _path=None: True)
    monkeypatch.setattr(
        plan_sync_mod,
        "load_plan",
        lambda _path=None: (_ for _ in ()).throw(OSError("boom")),
    )
    monkeypatch.setattr(plan_sync_mod, "PLAN_LOAD_EXCEPTIONS", (OSError,))

    outcome = plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )
    out = capsys.readouterr().out
    assert "Plan sync degraded" in out
    assert outcome.status == "degraded"


def test_sync_plan_after_import_runs_review_sync_for_auto_resolved_deltas(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    seen = {"import_called": False, "reconcile_called": False}

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)
    def fake_import_sync(_plan, _state, inject_triage=False):
        seen["import_called"] = True
        return None

    monkeypatch.setattr(plan_sync_mod, "sync_plan_after_review_import", fake_import_sync)
    monkeypatch.setattr(
        plan_sync_mod,
        "reconcile_plan",
        lambda *_a, **_k: seen.__setitem__("reconcile_called", True) or plan_sync_mod.ReconcileResult(),
    )

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 0, "reopened": 0, "auto_resolved": 2},
        assessment_mode="issues_only",
    )

    assert seen["import_called"] is True
    assert seen["reconcile_called"] is True


def test_import_holistic_issues_ignores_unknown_context_update_dimensions() -> None:
    state = build_empty_state()

    holistic_import_mod.import_holistic_issues(
        {
            "assessments": {"naming_quality": 90},
            "dimension_judgment": {
                "naming_quality": {
                    "strengths": ["Names are mostly precise."],
                    "dimension_character": "Minor drift remains localized.",
                    "score_rationale": "The naming is mostly dependable with a few rough edges.",
                }
            },
            "issues": [],
            "context_updates": {
                "not_a_real_dimension": {
                    "add": [
                        {
                            "header": "Bogus insight",
                            "description": "Should be ignored.",
                            "settled": False,
                        }
                    ]
                }
            },
        },
        state,
        "python",
    )

    assert state.get("dimension_contexts", {}) == {}


def test_sync_plan_after_import_logs_triage_provenance(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    entries: list[tuple[str, dict]] = []

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)
    monkeypatch.setattr(
        plan_sync_mod,
        "sync_plan_after_review_import",
        lambda _plan, _state, inject_triage=False: SimpleNamespace(
            new_ids={"review::x"},
            added_to_queue=["review::x"],
            stale_pruned_from_queue=[],
            triage_injected=False,
            triage_injected_ids=[],
            triage_deferred=False,
        ),
    )
    reconcile_result = plan_sync_mod.ReconcileResult(
        triage=plan_constants_mod.QueueSyncResult(
            injected=["triage::observe", "triage::reflect"],
        )
    )
    monkeypatch.setattr(
        plan_sync_mod,
        "reconcile_plan",
        lambda *_a, **_k: reconcile_result,
    )
    monkeypatch.setattr(
        plan_sync_mod,
        "append_log_entry",
        lambda _plan, action, **kwargs: entries.append((action, kwargs["detail"])),
    )

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )

    assert entries
    action, detail = entries[-1]
    assert action == "review_import_sync"
    assert detail["triage_injected"] is True
    assert detail["triage_injected_ids"] == ["triage::observe", "triage::reflect"]
    assert detail["triage_deferred"] is False
    assert detail["stale_pruned_from_queue"] == []
    assert detail["sync_status"] == "synced"


def test_sync_plan_after_import_keeps_workflow_before_triage(monkeypatch) -> None:
    plan: dict = {
        "queue_order": [],
        "plan_start_scores": {"strict": 70.0, "overall": 70.0, "objective": 80.0, "verified": 80.0},
    }
    entries: list[tuple[str, dict]] = []

    monkeypatch.setattr(plan_sync_mod, "has_living_plan", lambda _path=None: True)
    monkeypatch.setattr(plan_sync_mod, "load_plan", lambda _path=None: plan)
    monkeypatch.setattr(plan_sync_mod, "save_plan", lambda _plan, _path=None: None)
    def fake_review_import(_plan, _state, inject_triage=False):
        _plan["queue_order"].append("review::x")
        return SimpleNamespace(
            new_ids={"review::x"},
            added_to_queue=["review::x"],
            stale_pruned_from_queue=[],
            triage_injected=False,
            triage_injected_ids=[],
            triage_deferred=False,
        )

    monkeypatch.setattr(
        plan_sync_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode, **_kwargs: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(plan_sync_mod, "sync_plan_after_review_import", fake_review_import)
    def fake_reconcile(_plan, _state, target_strict):
        _plan["queue_order"].extend(
            ["workflow::communicate-score", "workflow::create-plan", "triage::observe"]
        )
        plan_constants_mod.normalize_queue_workflow_and_triage_prefix(_plan["queue_order"])
        return plan_sync_mod.ReconcileResult(
            communicate_score=plan_constants_mod.QueueSyncResult(
                injected=["workflow::communicate-score"]
            ),
            create_plan=plan_constants_mod.QueueSyncResult(
                injected=["workflow::create-plan"]
            ),
            triage=plan_constants_mod.QueueSyncResult(injected=["triage::observe"]),
        )
    monkeypatch.setattr(plan_sync_mod, "reconcile_plan", fake_reconcile)
    monkeypatch.setattr(plan_sync_mod, "live_planned_queue_empty", lambda _plan: True)
    monkeypatch.setattr(
        plan_sync_mod,
        "append_log_entry",
        lambda _plan, action, **kwargs: entries.append((action, kwargs["detail"])),
    )

    plan_sync_mod.sync_plan_after_import(
        state={"issues": {"review::x": {"summary": "new review work item"}}},
        diff={"new": 1, "reopened": 0},
        assessment_mode="trusted_internal",
    )

    assert plan["queue_order"][:2] == [
        "workflow::communicate-score",
        "workflow::create-plan",
    ]
    assert plan["queue_order"].index("workflow::communicate-score") < plan["queue_order"].index("triage::observe")
    assert plan["queue_order"].index("workflow::create-plan") < plan["queue_order"].index("triage::observe")
    action, detail = entries[-1]
    assert action == "review_import_sync"
    assert detail["workflow_injected_ids"] == [
        "workflow::communicate-score",
        "workflow::create-plan",
    ]


def test_sync_plan_after_import_trusted_internal_clears_workflow_cycle_sentinels(
    monkeypatch,
) -> None:
    plan: dict = {
        "queue_order": [],
        "previous_plan_start_scores": {"strict": 70.0},
        "create_plan_resolved_this_cycle": True,
        "communicate_score_resolved_this_cycle": True,
    }

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 0, "reopened": 0, "auto_resolved": 0},
        assessment_mode="trusted_internal",
        request=_sync_request(import_payload={"assessments": {"Naming Quality": 82}}),
    )

    assert "previous_plan_start_scores" not in plan
    assert "create_plan_resolved_this_cycle" not in plan
    assert "communicate_score_resolved_this_cycle" not in plan


def test_sync_plan_after_import_reuses_plan_aware_policy(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    seen: dict[str, object] = {}

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)

    def fake_reconcile(_plan, _state, target_strict):
        seen["target_strict"] = target_strict
        seen["plan"] = _plan
        return plan_sync_mod.ReconcileResult()

    monkeypatch.setattr(plan_sync_mod, "reconcile_plan", fake_reconcile)

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
        request=_sync_request(config={"target_strict_score": 97}),
    )

    assert seen["target_strict"] == 97.0
    assert seen["plan"] is plan


def test_sync_plan_after_import_preserves_scan_phase_for_temporary_skips(
    monkeypatch,
) -> None:
    plan: dict = {
        "queue_order": [],
        "skipped": {
            "review::deferred": {
                "issue_id": "review::deferred",
                "kind": "temporary",
            }
        },
        "refresh_state": {"postflight_scan_completed_at_scan_count": 3},
    }
    saved: list[dict] = []

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)
    monkeypatch.setattr(plan_sync_mod, "save_plan", lambda current_plan, _path=None: saved.append(dict(current_plan)))
    monkeypatch.setattr(
        plan_sync_mod,
        "sync_plan_after_review_import",
        lambda _plan, _state, inject_triage=False: SimpleNamespace(
            new_ids={"review::new"},
            added_to_queue=["review::new"],
            triage_injected=False,
            stale_pruned_from_queue=[],
            triage_injected_ids=[],
            triage_deferred=False,
        ),
    )
    monkeypatch.setattr(
        plan_sync_mod,
        "reconcile_plan",
        lambda _plan, _state, target_strict: _plan["refresh_state"].__setitem__("lifecycle_phase", "scan")
        or plan_sync_mod.ReconcileResult(lifecycle_phase="scan", lifecycle_phase_changed=True),
    )

    plan_sync_mod.sync_plan_after_import(
        state={"issues": {"review::new": {"summary": "new review work item"}}},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )

    assert plan["refresh_state"]["lifecycle_phase"] == "scan"
    assert saved


def test_sync_plan_after_import_prunes_covered_subjective_ids(monkeypatch) -> None:
    plan: dict = {"queue_order": ["subjective::naming_quality", "review::existing"]}

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)
    monkeypatch.setattr(
        plan_sync_mod,
        "sync_plan_after_review_import",
        lambda _plan, _state, inject_triage=False: SimpleNamespace(
            new_ids={"review::new"},
            added_to_queue=["review::new"],
            triage_injected=False,
            stale_pruned_from_queue=[],
            covered_subjective_pruned_from_queue=[],
            triage_injected_ids=[],
            triage_deferred=False,
        ),
    )

    plan_sync_mod.sync_plan_after_import(
        state={"issues": {"review::new": {"summary": "new review work item"}}},
        diff={"new": 1, "reopened": 0},
        assessment_mode="trusted_internal",
        request=_sync_request(
            import_payload={"assessments": {"Naming quality": 80}, "issues": []},
        ),
    )

    assert "subjective::naming_quality" not in plan["queue_order"]


def test_sync_plan_after_import_uses_pre_import_boundary_for_reconcile(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    seen = {"reconcile_called": False}

    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)
    monkeypatch.setattr(
        plan_sync_mod,
        "sync_plan_after_review_import",
        lambda _plan, _state, inject_triage=False: (
            _plan["queue_order"].append("review::new")
            or SimpleNamespace(
                new_ids={"review::new"},
                added_to_queue=["review::new"],
                triage_injected=False,
                stale_pruned_from_queue=[],
                covered_subjective_pruned_from_queue=[],
                triage_injected_ids=[],
                triage_deferred=False,
            )
        ),
    )
    monkeypatch.setattr(
        plan_sync_mod,
        "reconcile_plan",
        lambda *_a, **_k: seen.__setitem__("reconcile_called", True)
        or plan_sync_mod.ReconcileResult(),
    )

    plan_sync_mod.sync_plan_after_import(
        state={"issues": {"review::new": {"summary": "new review work item"}}},
        diff={"new": 1, "reopened": 0},
        assessment_mode="trusted_internal",
        request=_sync_request(
            import_payload={"assessments": {"Naming quality": 80}, "issues": []},
        ),
    )

    assert seen["reconcile_called"] is True


def test_sync_plan_after_import_skips_mid_cycle_reconcile_for_assessment_only_import(
    monkeypatch,
) -> None:
    plan: dict = {
        "queue_order": [
            "subjective::design_coherence",
            "subjective::naming_quality",
        ],
        "clusters": {
            "auto/initial-review": {
                "name": "auto/initial-review",
                "description": "Initial review of 2 unscored subjective dimensions",
                "issue_ids": [
                    "subjective::design_coherence",
                    "subjective::naming_quality",
                ],
                "created_at": "old",
                "updated_at": "old",
                "auto": True,
                "cluster_key": "subjective::unscored",
                "action": (
                    "desloppify review --prepare --dimensions "
                    "design_coherence,naming_quality"
                ),
                "user_modified": False,
            }
        },
        "overrides": {
            "subjective::design_coherence": {
                "issue_id": "subjective::design_coherence",
                "cluster": "auto/initial-review",
                "created_at": "old",
                "updated_at": "old",
            },
            "subjective::naming_quality": {
                "issue_id": "subjective::naming_quality",
                "cluster": "auto/initial-review",
                "created_at": "old",
                "updated_at": "old",
            },
        },
    }
    state = {
        "issues": {},
        "scan_count": 2,
        "dimension_scores": {
            "Design coherence": {
                "score": 80.0,
                "strict": 80.0,
                "checks": 1,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": "design_coherence",
                        "placeholder": False,
                    }
                },
            },
            "Naming quality": {
                "score": 78.0,
                "strict": 78.0,
                "checks": 1,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {
                        "dimension_key": "naming_quality",
                        "placeholder": False,
                    }
                },
            },
        },
        "subjective_assessments": {
            "design_coherence": {"score": 80.0, "needs_review_refresh": True},
            "naming_quality": {"score": 78.0, "needs_review_refresh": True},
        },
    }
    _patch_basic_plan_sync_runtime(monkeypatch, plan=plan)
    reconcile_calls: list[tuple[dict, dict, float]] = []
    monkeypatch.setattr(
        plan_sync_mod,
        "reconcile_plan",
        lambda _plan, _state, target_strict: reconcile_calls.append((_plan, _state, target_strict))
        or plan_sync_mod.ReconcileResult(),
    )
    monkeypatch.setattr(plan_sync_mod, "live_planned_queue_empty", lambda _plan: False)
    monkeypatch.setattr(
        plan_sync_mod,
        "append_log_entry",
        lambda *_a, **_k: None,
    )

    plan_sync_mod.sync_plan_after_import(
        state=state,
        diff={"new": 0, "reopened": 0, "auto_resolved": 0},
        assessment_mode="trusted_internal",
        request=_sync_request(
            import_payload={
                "assessments": {
                    "Design coherence": 80,
                    "Naming quality": 78,
                },
                "issues": [],
            },
        ),
    )

    assert reconcile_calls == []
    assert plan["queue_order"] == []
    assert plan["clusters"]["auto/initial-review"]["issue_ids"] == []


def test_refresh_scorecard_after_import_only_for_trusted_assessments(monkeypatch) -> None:
    calls: list[tuple[object, dict, dict]] = []
    monkeypatch.setattr(
        import_cmd_mod,
        "emit_scorecard_badge",
        lambda args, config, state: (calls.append((args, config, state)), (None, None))[1],
    )

    trusted = SimpleNamespace(assessments_present=True, trusted=True)
    skipped = SimpleNamespace(assessments_present=True, trusted=False)
    scan_state = {
        "last_scan": "2026-03-10T00:00:00+00:00",
        "dimension_scores": {
            "Code quality": {
                "checks": 10,
                "score": 95.0,
                "strict": 95.0,
                "detectors": {"smells": {"potential": 10}},
            },
            "Naming quality": {
                "checks": 10,
                "score": 80.0,
                "strict": 80.0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            },
        },
    }

    assert import_cmd_mod._refresh_scorecard_after_import(
        state=scan_state,
        config={"badge_path": "scorecard.png"},
        assessment_policy=trusted,
    ) is True
    assert len(calls) == 1

    assert import_cmd_mod._refresh_scorecard_after_import(
        state=scan_state,
        config={"badge_path": "scorecard.png"},
        assessment_policy=skipped,
    ) is False
    assert len(calls) == 1

    assert import_cmd_mod._refresh_scorecard_after_import(
        state={"strict_score": 74.5},
        config={"badge_path": "scorecard.png"},
        assessment_policy=trusted,
    ) is False
    assert len(calls) == 1


def test_refresh_scorecard_after_import_skips_subjective_only_state(monkeypatch) -> None:
    calls: list[tuple[object, dict, dict]] = []
    monkeypatch.setattr(
        import_cmd_mod,
        "emit_scorecard_badge",
        lambda args, config, state: (calls.append((args, config, state)), (None, None))[1],
    )
    trusted = SimpleNamespace(assessments_present=True, trusted=True)
    subjective_only_state = {
        "last_scan": "2026-03-10T00:00:00+00:00",
        "dimension_scores": {
            "Naming quality": {
                "checks": 10,
                "score": 100.0,
                "strict": 100.0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            }
        },
    }

    assert import_cmd_mod._refresh_scorecard_after_import(
        state=subjective_only_state,
        config={"badge_path": "scorecard.png"},
        assessment_policy=trusted,
    ) is False
    assert calls == []


def test_report_review_import_outcome_writes_query_payload(monkeypatch) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(results_mod.narrative_core, "compute_narrative", lambda *_a, **_k: {"summary": "ok"})
    monkeypatch.setattr(results_mod, "print_skipped_validation_details", lambda *_a, **_k: None)
    monkeypatch.setattr(results_mod, "print_assessments_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(
        results_mod,
        "print_open_review_summary",
        lambda *_a, **_k: "desloppify next",
    )
    monkeypatch.setattr(
        results_mod,
        "print_review_import_scores_and_integrity",
        lambda *_a, **_k: [{"name": "Design coherence", "score": 95.0}],
    )
    monkeypatch.setattr(results_mod, "show_score_with_plan_context", lambda *_a, **_k: None)
    monkeypatch.setattr(results_mod, "write_query", lambda payload: captured.append(payload))

    results_mod.report_review_import_outcome(
        state={"issues": {}},
        lang_name="python",
        config={},
        diff={"new": 2, "auto_resolved": 1, "reopened": 0},
        prev=SimpleNamespace(overall=0),
        label="Holistic review",
        provisional_count=0,
        assessment_policy=SimpleNamespace(mode="issues_only", trusted=False, reason="untrusted"),
        scorecard_subjective_at_target_fn=lambda *_a, **_k: [],
    )

    assert captured
    payload = captured[0]
    assert payload["command"] == "review"
    assert payload["action"] == "import"
    assert payload["next_command"] == "desloppify next"
    assert payload["assessment_import"]["mode"] == "issues_only"


def test_report_review_import_outcome_reports_provisional_warning(capsys, monkeypatch) -> None:
    monkeypatch.setattr(results_mod.narrative_core, "compute_narrative", lambda *_a, **_k: {})
    monkeypatch.setattr(results_mod, "print_skipped_validation_details", lambda *_a, **_k: None)
    monkeypatch.setattr(results_mod, "print_assessments_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(
        results_mod,
        "print_open_review_summary",
        lambda *_a, **_k: "desloppify next",
    )
    monkeypatch.setattr(
        results_mod,
        "print_review_import_scores_and_integrity",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(results_mod, "show_score_with_plan_context", lambda *_a, **_k: None)
    monkeypatch.setattr(results_mod, "write_query", lambda _payload: None)

    results_mod.report_review_import_outcome(
        state={"issues": {}},
        lang_name="python",
        config={},
        diff={"new": 1, "auto_resolved": 0, "reopened": 0},
        prev=SimpleNamespace(overall=0),
        label="Holistic review",
        provisional_count=2,
        assessment_policy=SimpleNamespace(mode="manual_override", trusted=False, reason="manual"),
        scorecard_subjective_at_target_fn=lambda *_a, **_k: [],
    )

    out = capsys.readouterr().out
    assert "manual override assessments are provisional" in out


def test_plan_sync_source_preserves_scoped_sync_pipeline_contract() -> None:
    src = inspect.getsource(plan_sync_mod.sync_plan_after_import)
    assert "request: PlanImportSyncRequest | None = None" in src
    assert "state_file = request.state_file if request is not None else None" in src
    assert "plan_path = None" in src
    assert "plan_path_for_state(Path(state_file))" in src
    assert "if not has_living_plan(plan_path):" in src
    assert 'return PlanImportSyncOutcome(status="skipped")' in src
    assert "plan = load_plan(plan_path)" in src
    assert 'trusted = assessment_mode in {"trusted_internal", "attested_external"}' in src
    assert "sync_inputs = _build_import_sync_inputs(diff, import_payload)" in src
    assert "was_boundary_ready = live_planned_queue_empty(plan)" in src
    assert "transition = _apply_import_plan_transitions(" in src
    assert "import_result = transition.import_result" in src
    assert "covered_pruned = transition.covered_pruned" in src
    assert "import_scores_result = transition.import_scores_result" in src
    assert "result = transition.reconcile_result" in src
    assert "_append_review_import_sync_log(" in src
    assert "save_plan(plan, plan_path)" in src
    assert "_print_review_import_sync(" in src
    assert 'return PlanImportSyncOutcome(status="degraded", message=message)' in src


def test_results_source_preserves_query_and_narrative_contract() -> None:
    src = inspect.getsource(results_mod.report_review_import_outcome)
    assert "narrative_core.compute_narrative(" in src
    assert 'NarrativeContext(lang=lang_name, command="review")' in src
    assert 'print(colorize(f"\\n  {label} imported:", "bold"))' in src
    assert 'issue_count = int(diff.get("new", 0) or 0)' in src
    assert "print_skipped_validation_details(diff, colorize_fn=colorize)" in src
    assert "print_assessments_summary(state, colorize_fn=colorize)" in src
    assert "next_command = print_open_review_summary(" in src
    assert "show_score_with_plan_context(state, prev)" in src
    assert "print_review_import_scores_and_integrity(" in src
    assert 'f"  Next command to improve subjective scores: `{next_command}`"' in src
    assert "write_query(" in src
    assert '"command": "review"' in src
    assert '"action": "import"' in src
    assert '"mode": "holistic"' in src
    assert '"diff": diff' in src
    assert '"next_command": next_command' in src
    assert '"subjective_at_target": [' in src
    assert '"assessment_import": {' in src
    assert '"narrative": narrative' in src
