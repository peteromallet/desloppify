"""Direct tests for split engine plan/scoring/lifecycle helper modules."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.engine._plan.auto_cluster_sync_issue as auto_cluster_sync_mod
import desloppify.engine._plan.constants as plan_constants_mod
import desloppify.engine._plan.sync as sync_pkg_mod
import desloppify.engine._plan.scan_issue_reconcile as scan_reconcile_mod
import desloppify.engine._plan.sync.review_import as reconcile_import_mod
import desloppify.engine._plan.schema.helpers as schema_helpers_mod
import desloppify.engine._plan.sync.auto_prune as sync_auto_prune_mod
import desloppify.engine._plan.sync.context as sync_context_mod
import desloppify.engine._plan.sync.triage_start_policy as triage_start_policy_mod
import desloppify.engine._plan.sync.workflow as sync_workflow_mod
import desloppify.engine._plan.triage.dismiss as triage_dismiss_mod
import desloppify.engine._plan.triage.playbook as triage_playbook_mod
import desloppify.engine._scoring.state_integration_subjective as scoring_subjective_mod
import desloppify.engine._work_queue.snapshot as snapshot_mod
import desloppify.engine._work_queue.synthetic as synthetic_mod


def test_sync_context_helpers_cover_policy_and_fallback_paths() -> None:
    policy = SimpleNamespace(has_objective_backlog=True)
    assert sync_context_mod.has_objective_backlog({}, policy) is True

    state = {
        "issues": {
            "id1": {"status": "open", "detector": "unused", "suppressed": False},
            "id2": {"status": "fixed", "detector": "unused", "suppressed": False},
        }
    }
    assert sync_context_mod.has_objective_backlog(state, policy=None) is True
    assert sync_context_mod.is_mid_cycle({"plan_start_scores": {"strict": 75.0}}) is True
    assert sync_context_mod.is_mid_cycle({"plan_start_scores": {"reset": True}}) is False


def test_triage_start_policy_decisions_cover_inject_defer_and_active(monkeypatch) -> None:
    plan = {"queue_order": []}
    monkeypatch.setattr(triage_start_policy_mod, "is_mid_cycle", lambda _plan: False)
    assert triage_start_policy_mod.decide_triage_start(plan, state={"issues": {}}).action == "inject"

    active_plan = {"queue_order": ["triage::observe"]}
    assert (
        triage_start_policy_mod.decide_triage_start(active_plan, state={"issues": {}}).action
        == "already_active"
    )

    monkeypatch.setattr(triage_start_policy_mod, "is_mid_cycle", lambda _plan: True)
    monkeypatch.setattr(
        triage_start_policy_mod,
        "has_objective_backlog",
        lambda _state, _policy=None: True,
    )
    deferred = triage_start_policy_mod.decide_triage_start(
        plan,
        state={"issues": {"id1": {"status": "open"}}},
        explicit_start=True,
        attested_override=False,
    )
    assert deferred.action == "defer"
    overridden = triage_start_policy_mod.decide_triage_start(
        plan,
        state={"issues": {"id1": {"status": "open"}}},
        explicit_start=True,
        attested_override=True,
    )
    assert overridden.action == "inject"

    plan_with_defer_meta = {
        "queue_order": [],
        "epic_triage_meta": {"triage_defer_state": {"defer_count": 2}},
    }
    monkeypatch.setattr(triage_start_policy_mod, "is_mid_cycle", lambda _plan: False)
    assert (
        triage_start_policy_mod.decide_triage_start(
            plan_with_defer_meta,
            state={"issues": {}},
        ).action
        == "inject"
    )


def test_triage_stage_helpers_ignore_non_stage_meta_dicts() -> None:
    meta = {"triage_defer_state": {"defer_count": 2}}
    assert plan_constants_mod.confirmed_triage_stage_names(meta) == set()
    assert plan_constants_mod.recorded_unconfirmed_triage_stage_names(meta) == set()


def test_epic_triage_dismiss_moves_issues_to_skipped() -> None:
    triage = SimpleNamespace(
        dismissed_issues=[SimpleNamespace(issue_id="id1", reason="false_positive")],
        clusters=[{"dismissed": ["id2"]}],
    )
    order = ["id1", "id2", "id3"]
    skipped: dict = {}

    dismissed_ids, dismiss_count = triage_dismiss_mod.dismiss_triage_issues(
        triage=triage,
        order=order,
        skipped=skipped,
        now="2026-03-09T00:00:00+00:00",
        version=7,
        scan_count=11,
    )
    assert dismiss_count == 2
    assert dismissed_ids == ["id1", "id2"]
    assert order == ["id3"]
    assert skipped["id1"]["kind"] == "triaged_out"


def test_reconcile_review_import_sync_result(monkeypatch) -> None:
    plan = {"queue_order": ["id1"], "epic_triage_meta": {"triaged_ids": ["id1"]}}
    state = {"issues": {}}

    monkeypatch.setattr(reconcile_import_mod, "compute_open_issue_ids", lambda _s: set())
    monkeypatch.setattr(reconcile_import_mod, "compute_new_issue_ids", lambda _p, _s: {"id2", "id3"})
    monkeypatch.setattr(
        reconcile_import_mod,
        "sync_triage_needed",
        lambda _p, _s, policy=None: SimpleNamespace(
            injected=["triage::observe", "triage::reflect"],
            deferred=False,
        ),
    )

    result = reconcile_import_mod.sync_plan_after_review_import(plan, state, policy=None)
    assert result is not None
    assert result.new_ids == {"id2", "id3"}
    assert result.added_to_queue == ["id2", "id3"]
    assert result.stale_pruned_from_queue == []
    assert result.triage_injected is True
    assert result.triage_injected_ids == ["triage::observe", "triage::reflect"]
    assert result.triage_deferred is False
    assert plan["queue_order"] == ["id1", "id2", "id3"]


def test_reconcile_review_import_sync_uses_open_ids_without_triage_baseline(monkeypatch) -> None:
    plan = {"queue_order": []}
    state = {"issues": {}}

    monkeypatch.setattr(reconcile_import_mod, "compute_open_issue_ids", lambda _s: {"rid::a"})
    monkeypatch.setattr(reconcile_import_mod, "compute_new_issue_ids", lambda _p, _s: set())
    monkeypatch.setattr(
        reconcile_import_mod,
        "sync_triage_needed",
        lambda _p, _s, policy=None: SimpleNamespace(
            injected=["triage::observe"],
            deferred=False,
        ),
    )

    result = reconcile_import_mod.sync_plan_after_review_import(plan, state, policy=None)
    assert result is not None
    assert result.new_ids == {"rid::a"}
    assert result.added_to_queue == ["rid::a"]
    assert result.stale_pruned_from_queue == []
    assert result.triage_injected is True
    assert result.triage_injected_ids == ["triage::observe"]
    assert plan["queue_order"] == ["rid::a"]


def test_reconcile_review_import_prunes_stale_review_ids_even_without_new_ids(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": ["review::live", "review::stale", "smells::keep"],
        "deferred": ["review::stale", "smells::keep"],
        "promoted_ids": ["review::stale", "smells::keep"],
        "clusters": {
            "manual/review": {"issue_ids": ["review::live", "review::stale"]},
            "manual/objective": {"issue_ids": ["smells::keep"]},
        },
        "epic_triage_meta": {"triaged_ids": ["review::live"]},
    }
    state = {"issues": {}}

    monkeypatch.setattr(reconcile_import_mod, "compute_open_issue_ids", lambda _s: {"review::live"})
    monkeypatch.setattr(reconcile_import_mod, "compute_new_issue_ids", lambda _p, _s: set())
    monkeypatch.setattr(
        reconcile_import_mod,
        "sync_triage_needed",
        lambda _p, _s, policy=None: SimpleNamespace(injected=[], deferred=False),
    )

    result = reconcile_import_mod.sync_plan_after_review_import(plan, state, policy=None)

    assert result is not None
    assert result.new_ids == set()
    assert result.added_to_queue == []
    assert result.stale_pruned_from_queue == ["review::stale"]
    assert plan["queue_order"] == ["review::live", "smells::keep"]
    assert plan["deferred"] == []
    assert "review::stale" not in plan["skipped"]
    assert "smells::keep" in plan["skipped"]
    assert plan["promoted_ids"] == ["smells::keep"]
    assert plan["clusters"]["manual/review"]["issue_ids"] == ["review::live"]
    assert plan["clusters"]["manual/objective"]["issue_ids"] == ["smells::keep"]


def test_reconcile_review_import_prunes_stale_triage_recovery_metadata(
    monkeypatch,
) -> None:
    plan = {
        "queue_order": ["review::live", "review::stale"],
        "clusters": {},
        "epic_triage_meta": {
            "triaged_ids": ["review::live", "review::stale"],
            "active_triage_issue_ids": ["review::live", "review::stale"],
            "undispositioned_issue_ids": ["review::live", "review::stale"],
            "undispositioned_issue_count": 2,
        },
    }
    state = {"issues": {}}

    monkeypatch.setattr(reconcile_import_mod, "compute_open_issue_ids", lambda _s: {"review::live"})
    monkeypatch.setattr(reconcile_import_mod, "compute_new_issue_ids", lambda _p, _s: set())
    monkeypatch.setattr(
        reconcile_import_mod,
        "sync_triage_needed",
        lambda _p, _s, policy=None: SimpleNamespace(injected=[], deferred=False),
    )

    result = reconcile_import_mod.sync_plan_after_review_import(plan, state, policy=None)

    assert result is not None
    assert result.stale_pruned_from_queue == ["review::stale"]
    assert plan["epic_triage_meta"]["triaged_ids"] == ["review::live", "review::stale"]
    assert plan["epic_triage_meta"]["active_triage_issue_ids"] == ["review::live"]
    assert plan["epic_triage_meta"]["undispositioned_issue_ids"] == ["review::live"]
    assert plan["epic_triage_meta"]["undispositioned_issue_count"] == 1


def test_reconcile_module_exports_scan_reconcile_only() -> None:
    assert scan_reconcile_mod.__all__ == [
        "ReconcileResult",
        "reconcile_plan_after_scan",
    ]
    assert not hasattr(scan_reconcile_mod, "sync_plan_after_review_import")
    assert not hasattr(scan_reconcile_mod, "ReviewImportSyncResult")


def test_sync_package_includes_review_import_subdomain() -> None:
    assert "review_import" in sync_pkg_mod.__all__
    assert hasattr(reconcile_import_mod, "sync_plan_after_review_import")
    assert hasattr(reconcile_import_mod, "ReviewImportSyncResult")


def test_schema_migration_helpers_cover_legacy_cleanup() -> None:
    assert (
        schema_helpers_mod._has_synthesis_artifacts(
            queue_order=["synthesis::a"],
            skipped={},
            clusters={},
            meta={},
        )
        is True
    )

    plan = {"old": 1, "keep": 2}
    assert schema_helpers_mod._drop_legacy_plan_keys(plan, ("old", "missing")) is True
    assert plan == {"keep": 2}

    meta = {"synthesis_stages": {}, "x": 1}
    assert schema_helpers_mod._cleanup_synthesis_meta(meta) is True
    assert "synthesis_stages" not in meta

    cluster = {"action_steps": ["short", "Sentence one. Additional detail here."]}
    changed = schema_helpers_mod._migrate_action_steps_to_v8(cluster)
    assert changed is True
    assert isinstance(cluster["action_steps"][0], dict)


def test_sync_auto_prune_removes_stale_auto_clusters_and_cleans_overrides() -> None:
    plan = {
        "overrides": {"id1": {"cluster": "auto-a", "updated_at": ""}},
        "active_cluster": "auto-a",
    }
    issues = {"id1": {"status": "fixed"}}
    clusters = {
        "auto-a": {
            "auto": True,
            "cluster_key": "stale",
            "issue_ids": ["id1"],
        },
        "manual": {"auto": False, "issue_ids": []},
    }

    changes = sync_auto_prune_mod.prune_stale_clusters(
        plan,
        issues,
        clusters,
        active_auto_keys=set(),
        now="2026-03-09T00:00:00+00:00",
    )
    assert changes == 1
    assert "auto-a" not in clusters
    assert plan["overrides"]["id1"]["cluster"] is None
    assert plan["active_cluster"] is None


def test_auto_cluster_grouping_filters_to_open_unsuppressed_non_manual_items(
    monkeypatch,
) -> None:
    clusters = {
        "manual/one": {"auto": False, "issue_ids": ["manual-1"]},
        "auto/one": {"auto": True, "issue_ids": ["auto-1"]},
    }
    manual_ids = auto_cluster_sync_mod._manual_member_ids(clusters)
    assert manual_ids == {"manual-1"}

    monkeypatch.setattr(
        auto_cluster_sync_mod,
        "_grouping_key",
        lambda issue, _meta: f"{issue.get('detector')}::bucket",
    )
    monkeypatch.setattr(
        auto_cluster_sync_mod,
        "DETECTORS",
        {"unused": SimpleNamespace(name="unused", needs_judgment=False, auto_queue=True)},
    )

    issues = {
        "manual-1": {"status": "open", "suppressed": False, "detector": "unused"},
        "open-1": {"status": "open", "suppressed": False, "detector": "unused"},
        "open-2": {"status": "open", "suppressed": False, "detector": "unused"},
        "closed": {"status": "fixed", "suppressed": False, "detector": "unused"},
        "suppressed": {"status": "open", "suppressed": True, "detector": "unused"},
    }

    grouped, issue_data = auto_cluster_sync_mod._group_clusterable_issues(
        issues,
        manual_member_ids=manual_ids,
    )
    assert grouped == {"unused::bucket": ["open-1", "open-2"]}
    assert set(issue_data) == {"open-1", "open-2"}


def test_auto_cluster_sync_helpers_cover_create_update_and_user_modified_paths() -> None:
    plan = {"overrides": {"id-a": {"issue_id": "id-a", "created_at": "t0"}}}
    clusters = {"manual/keep": {"issue_ids": ["id-a"]}}

    changes = auto_cluster_sync_mod._sync_user_modified_cluster_members(
        plan,
        clusters=clusters,
        existing_name="manual/keep",
        member_ids=["id-a", "id-b"],
        now="t1",
    )
    assert changes == 1
    assert clusters["manual/keep"]["issue_ids"] == ["id-a", "id-b"]
    assert plan["overrides"]["id-b"]["cluster"] == "manual/keep"

    plan = {"overrides": {}}
    clusters = {}
    by_key: dict[str, str] = {}

    created = auto_cluster_sync_mod._sync_auto_cluster(
        plan,
        clusters,
        by_key,
        cluster_key="unused::bucket",
        cluster_name="auto/unused",
        member_ids=["id-1", "id-2"],
        description="desc",
        action="act",
        now="now",
        optional=True,
    )
    assert created.created is True
    assert created.changed is True
    assert clusters["auto/unused"]["optional"] is True
    assert plan["overrides"]["id-1"]["cluster"] == "auto/unused"

    unchanged = auto_cluster_sync_mod._sync_auto_cluster(
        plan,
        clusters,
        by_key,
        cluster_key="unused::bucket",
        cluster_name="auto/unused",
        member_ids=["id-1", "id-2"],
        description="desc",
        action="act",
        now="later",
    )
    assert unchanged.created is False
    assert unchanged.changed is False

    updated = auto_cluster_sync_mod._sync_auto_cluster(
        plan,
        clusters,
        by_key,
        cluster_key="unused::bucket",
        cluster_name="auto/unused",
        member_ids=["id-2", "id-3"],
        description="desc2",
        action="act2",
        now="later",
    )
    assert updated.changed is True
    assert clusters["auto/unused"]["issue_ids"] == ["id-2", "id-3"]


def test_sync_issue_clusters_handles_name_collisions_and_user_modified_clusters(
    monkeypatch,
) -> None:
    plan = {"overrides": {}}
    clusters = {
        "auto/shared": {
            "auto": True,
            "cluster_key": "unused::manual::one",
            "issue_ids": ["id-a"],
            "user_modified": True,
        }
    }
    existing_by_key = {"unused::manual::one": "auto/shared"}
    active_keys: set[str] = set()

    issues = {
        "id-a": {"detector": "unused"},
        "id-b": {"detector": "unused"},
        "id-c": {"detector": "unused"},
        "id-d": {"detector": "unused"},
    }

    monkeypatch.setattr(
        auto_cluster_sync_mod,
        "_group_clusterable_issues",
        lambda *_a, **_k: (
            {
                "unused::manual::one": ["id-a", "id-b"],
                "unused::new::two": ["id-c", "id-d"],
            },
            issues,
        ),
    )
    monkeypatch.setattr(auto_cluster_sync_mod, "_cluster_name_from_key", lambda _k: "auto/shared")
    monkeypatch.setattr(auto_cluster_sync_mod, "_generate_description", lambda *_a, **_k: "desc")
    monkeypatch.setattr(auto_cluster_sync_mod, "_generate_action", lambda *_a, **_k: "act")
    monkeypatch.setattr(
        auto_cluster_sync_mod,
        "DETECTORS",
        {"unused": SimpleNamespace(name="unused", needs_judgment=False, auto_queue=True)},
    )

    changes = auto_cluster_sync_mod.sync_issue_clusters(
        plan,
        issues,
        clusters,
        existing_by_key,
        active_keys,
        now="2026-03-09T00:00:00+00:00",
    )

    assert changes == 2
    assert clusters["auto/shared"]["issue_ids"] == ["id-a", "id-b"]
    assert "auto/shared-2" in clusters
    assert existing_by_key["unused::new::two"] == "auto/shared-2"
    assert plan["overrides"]["id-c"]["cluster"] == "auto/shared-2"
    assert active_keys == {"unused::manual::one", "unused::new::two"}


def test_sync_workflow_helpers_inject_expected_items(monkeypatch) -> None:
    plan = {"queue_order": ["triage::observe", "review::x"]}
    state = {"issues": {"id1": {"status": "open", "detector": "unused"}}}
    policy = SimpleNamespace(unscored_ids=set(), has_objective_backlog=True)

    r1 = sync_workflow_mod.sync_score_checkpoint_needed(plan, state, policy=policy)
    assert r1.injected == ["workflow::score-checkpoint"]
    assert plan["queue_order"][:2] == ["workflow::score-checkpoint", "triage::observe"]

    plan = {"queue_order": []}
    r2 = sync_workflow_mod.sync_create_plan_needed(plan, state, policy=policy)
    assert r2.injected == ["workflow::create-plan"]

    plan = {"queue_order": []}
    r3 = sync_workflow_mod.sync_import_scores_needed(
        plan,
        state,
        assessment_mode="issues_only",
        import_file="/tmp/review/issues.json",
        import_payload={
            "issues": [],
            "assessments": {"naming_quality": 80},
            "provenance": {"packet_sha256": "abc123", "packet_path": "/tmp/review_packet_blind.json"},
        },
    )
    assert r3.injected == ["workflow::import-scores"]
    assert plan["refresh_state"]["pending_import_scores"]["import_file"] == "/tmp/review/issues.json"
    assert plan["refresh_state"]["pending_import_scores"]["packet_sha256"] == "abc123"

    plan = {"queue_order": []}
    r4 = sync_workflow_mod.sync_communicate_score_needed(
        plan,
        state,
        policy=SimpleNamespace(unscored_ids=set(), has_objective_backlog=True),
    )
    assert r4.injected == ["workflow::communicate-score"]

    monkeypatch.setattr(sync_workflow_mod.stale_policy_mod, "current_unscored_ids", lambda *_a, **_k: {"s"})
    assert sync_workflow_mod._no_unscored(state, policy=None) is False


def test_sync_import_scores_prunes_stale_workflow_after_trusted_import() -> None:
    plan = {
        "queue_order": ["workflow::import-scores", "review::x"],
        "refresh_state": {
            "pending_import_scores": {
                "timestamp": "2026-03-10T10:00:00+00:00",
                "import_file": "/tmp/issues.json",
            }
        },
    }
    state = {
        "assessment_import_audit": [
            {
                "timestamp": "2026-03-10T10:00:00+00:00",
                "mode": "issues_only",
                "import_file": "/tmp/issues.json",
            },
            {
                "timestamp": "2026-03-10T10:05:00+00:00",
                "mode": "trusted_internal",
                "import_file": "/tmp/merged.json",
            },
        ]
    }

    result = sync_workflow_mod.sync_import_scores_needed(plan, state, assessment_mode=None)

    assert result.pruned == ["workflow::import-scores"]
    assert plan["queue_order"] == ["review::x"]
    assert plan["refresh_state"] == {}


def test_sync_import_scores_updates_metadata_on_consecutive_issues_only_import() -> None:
    """A second issues_only import should update pending metadata to the latest batch."""
    plan: dict = {"queue_order": []}
    state: dict = {
        "assessment_import_audit": [
            {
                "timestamp": "2026-03-10T10:00:00+00:00",
                "mode": "issues_only",
                "import_file": "/tmp/review-v1.json",
            },
        ]
    }

    # First issues_only import injects the workflow item with v1 metadata
    r1 = sync_workflow_mod.sync_import_scores_needed(
        plan,
        state,
        assessment_mode="issues_only",
        import_file="/tmp/review-v1.json",
        import_payload={
            "issues": [{"id": "a"}],
            "assessments": {"naming_quality": 80},
            "provenance": {"packet_sha256": "hash-v1"},
        },
    )
    assert r1.injected == ["workflow::import-scores"]
    assert plan["refresh_state"]["pending_import_scores"]["packet_sha256"] == "hash-v1"

    # Second issues_only import with updated data should update metadata
    state["assessment_import_audit"].append(
        {
            "timestamp": "2026-03-10T10:10:00+00:00",
            "mode": "issues_only",
            "import_file": "/tmp/review-v2.json",
        },
    )
    r2 = sync_workflow_mod.sync_import_scores_needed(
        plan,
        state,
        assessment_mode="issues_only",
        import_file="/tmp/review-v2.json",
        import_payload={
            "issues": [{"id": "a"}, {"id": "b"}],
            "assessments": {"naming_quality": 85, "design_coherence": 70},
            "provenance": {"packet_sha256": "hash-v2"},
        },
    )
    assert r2.changes == 1
    assert r2.injected == []  # not re-injected, just updated
    assert r2.resurfaced == ["workflow::import-scores"]
    meta = plan["refresh_state"]["pending_import_scores"]
    assert meta["import_file"] == "/tmp/review-v2.json"
    assert meta["packet_sha256"] == "hash-v2"


def test_pending_import_scores_meta_ignores_malformed_refresh_state() -> None:
    plan = {
        "refresh_state": {
            "pending_import_scores": "bad-shape",
        }
    }
    state = {
        "assessment_import_audit": [
            {
                "timestamp": "2026-03-10T10:00:00+00:00",
                "mode": "issues_only",
                "import_file": "/tmp/review.json",
                "packet_sha256": "hash-from-audit",
            }
        ]
    }

    meta = sync_workflow_mod.pending_import_scores_meta(plan, state)

    assert meta is not None
    assert meta.import_file == "/tmp/review.json"
    assert meta.packet_sha256 == "hash-from-audit"


def test_sync_communicate_score_reinjects_after_trusted_score_import_when_sentinel_cleared() -> None:
    plan = {
        "queue_order": ["triage::observe"],
        "plan_start_scores": {
            "strict": 70.0,
            "overall": 70.0,
            "objective": 80.0,
            "verified": 80.0,
        },
    }

    result = sync_workflow_mod.sync_communicate_score_needed(
        plan,
        state={"issues": {}},
        current_scores=sync_workflow_mod.ScoreSnapshot(
            strict=74.5,
            overall=74.5,
            objective=97.5,
            verified=97.4,
        ),
    )

    assert result.injected == ["workflow::communicate-score"]
    assert plan["queue_order"][:2] == ["workflow::communicate-score", "triage::observe"]
    assert plan["previous_plan_start_scores"]["strict"] == 70.0
    assert plan["plan_start_scores"]["strict"] == 74.5


def test_sync_workflow_injection_removes_stale_skip_entries() -> None:
    plan = {
        "queue_order": [],
        "skipped": {
            "workflow::create-plan": {
                "issue_id": "workflow::create-plan",
                "kind": "temporary",
                "skipped_at_scan": 0,
            }
        },
    }
    state = {"issues": {"id1": {"status": "open", "detector": "unused"}}}
    policy = SimpleNamespace(unscored_ids=set(), has_objective_backlog=True)

    result = sync_workflow_mod.sync_create_plan_needed(plan, state, policy=policy)

    assert result.injected == ["workflow::create-plan"]
    assert "workflow::create-plan" in plan["queue_order"]
    assert "workflow::create-plan" not in plan["skipped"]


def test_subjective_integrity_helpers_disabled_policy() -> None:
    assessments = {
        "naming_quality": {"score": 95},
        "design_coherence": {"score": 96},
        "error_consistency": {"score": 60},
    }
    adjusted, meta = scoring_subjective_mod._apply_subjective_integrity_policy(
        assessments,
        target=95,
    )
    assert meta["status"] == "disabled"
    assert meta["reset_dimensions"] == []
    # Scores are preserved — no penalty applied
    assert adjusted["naming_quality"]["score"] == 95
    assert adjusted["design_coherence"]["score"] == 96

    assert scoring_subjective_mod._coerce_subjective_score({"score": "101"}) == 100.0
    assert scoring_subjective_mod._normalize_integrity_target(120.0) == 100.0
    assert scoring_subjective_mod._normalize_integrity_target(None) is None


def test_queue_snapshot_enforces_phase_boundaries() -> None:
    state = {
        "issues": {
            "unused::a": {
                "id": "unused::a",
                "detector": "unused",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "unused import",
                "detail": {},
            }
        },
        "dimension_scores": {
            "Naming quality": {
                "score": 0.0,
                "strict": 0.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {"dimension_key": "naming_quality"}},
            }
        },
    }
    initial = snapshot_mod.build_queue_snapshot(state, plan=None)
    assert initial.phase == snapshot_mod.PHASE_REVIEW_INITIAL
    assert [item["id"] for item in initial.execution_items] == ["subjective::naming_quality"]

    execute = snapshot_mod.build_queue_snapshot(
        {
            **state,
            "dimension_scores": {
                "Naming quality": {
                    "score": 70.0,
                    "strict": 70.0,
                    "failing": 1,
                    "detectors": {"subjective_assessment": {"dimension_key": "naming_quality"}},
                }
            },
            "subjective_assessments": {
                "naming_quality": {"score": 70.0, "needs_review_refresh": True}
            },
        },
        plan={"queue_order": ["triage::observe"], "plan_start_scores": {"strict": 75.0}},
    )
    assert execute.phase == snapshot_mod.PHASE_SCAN
    assert [item["id"] for item in execute.execution_items] == ["workflow::run-scan"]
    backlog_ids = {item["id"] for item in execute.backlog_items}
    assert "triage::observe" in backlog_ids
    assert "unused::a" in backlog_ids


def test_queue_snapshot_keeps_executing_real_queue_items_before_postflight_scan() -> None:
    state = {
        "issues": {
            "unused::a": {
                "id": "unused::a",
                "detector": "unused",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "unused import",
                "detail": {},
            }
        }
    }
    plan = {
        "queue_order": ["unused::a", "workflow::communicate-score", "triage::observe"],
        "plan_start_scores": {"strict": 80.0},
        "refresh_state": {"lifecycle_phase": "execute"},
    }

    snapshot = snapshot_mod.build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == snapshot_mod.PHASE_EXECUTE
    assert [item["id"] for item in snapshot.execution_items] == ["unused::a"]


def test_queue_snapshot_does_not_execute_autofix_cluster_without_queue_ownership() -> None:
    state = {
        "issues": {
            "unused::a": {
                "id": "unused::a",
                "detector": "unused",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "unused import",
                "detail": {},
            }
        }
    }
    plan = {
        "queue_order": [],
        "clusters": {
            "auto/unused": {
                "issue_ids": ["unused::a"],
                "auto": True,
                "action": "desloppify autofix unused-imports --dry-run",
                "action_type": "auto_fix",
                "execution_policy": "ephemeral_autopromote",
            }
        },
        "plan_start_scores": {"strict": 80.0},
    }

    snapshot = snapshot_mod.build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == snapshot_mod.PHASE_SCAN
    assert "unused::a" not in [item["id"] for item in snapshot.execution_items]
    assert "unused::a" in {item["id"] for item in snapshot.backlog_items}


def test_queue_snapshot_legacy_autofix_cluster_stays_backlog_without_queue_ownership() -> None:
    state = {
        "issues": {
            "unused::a": {
                "id": "unused::a",
                "detector": "unused",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "unused import",
                "detail": {},
            }
        }
    }
    plan = {
        "queue_order": [],
        "clusters": {
            "auto/unused": {
                "name": "auto/unused",
                "issue_ids": ["unused::a"],
                "auto": True,
                "action": "desloppify autofix unused-imports --dry-run",
            }
        },
        "plan_start_scores": {"strict": 80.0},
    }

    snapshot = snapshot_mod.build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == snapshot_mod.PHASE_SCAN
    assert "unused::a" not in [item["id"] for item in snapshot.execution_items]
    assert "unused::a" in {item["id"] for item in snapshot.backlog_items}


def test_queue_snapshot_non_autofix_auto_cluster_does_not_execute_without_queueing() -> None:
    state = {
        "issues": {
            "dict_keys::a": {
                "id": "dict_keys::a",
                "detector": "dict_keys",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "dict key mismatch",
                "detail": {},
            }
        }
    }
    plan = {
        "queue_order": [],
        "clusters": {
            "auto/dict_keys": {
                "issue_ids": ["dict_keys::a"],
                "auto": True,
                "action": "review and refactor each issue",
                "action_type": "refactor",
                "execution_policy": "planned_only",
            }
        },
        "plan_start_scores": {"strict": 80.0},
    }

    snapshot = snapshot_mod.build_queue_snapshot(state, plan=plan)

    assert snapshot.phase != snapshot_mod.PHASE_EXECUTE
    assert "dict_keys::a" not in [item["id"] for item in snapshot.execution_items]
    assert "dict_keys::a" in {item["id"] for item in snapshot.backlog_items}


def test_queue_snapshot_orders_scan_assessment_workflow_and_triage_postflight() -> None:
    review_state = {
        "issues": {
            "review::src/a.py::naming": {
                "id": "review::src/a.py::naming",
                "detector": "review",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "review finding",
                "detail": {"dimension": "naming_quality"},
            }
        }
    }
    assessment_state = {
        "issues": {
            "review::src/a.py::naming": {
                "id": "review::src/a.py::naming",
                "detector": "review",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "review finding",
                "detail": {"dimension": "naming_quality"},
            },
            "subjective_review::naming_quality": {
                "id": "subjective_review::naming_quality",
                "detector": "subjective_review",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "rerun request",
                "detail": {"dimension": "naming_quality"},
            },
        },
        "dimension_scores": {
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
        "subjective_assessments": {
            "naming_quality": {
                "score": 70.0,
                "needs_review_refresh": True,
                "stale_since": "2026-01-01T00:00:00+00:00",
            },
        },
    }
    scan_plan = {
        "queue_order": ["workflow::run-scan", "workflow::communicate-score", "triage::observe"],
        "plan_start_scores": {"strict": 80.0},
    }
    scan_snapshot = snapshot_mod.build_queue_snapshot(review_state, plan=scan_plan)
    assert scan_snapshot.phase == snapshot_mod.PHASE_SCAN
    assert [item["id"] for item in scan_snapshot.execution_items] == ["workflow::run-scan"]

    review_plan = {
        "queue_order": ["workflow::communicate-score", "triage::observe"],
        "plan_start_scores": {"strict": 80.0},
        "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
    }
    review_snapshot = snapshot_mod.build_queue_snapshot(review_state, plan=review_plan)
    assert review_snapshot.phase == snapshot_mod.PHASE_WORKFLOW_POSTFLIGHT
    assert [item["id"] for item in review_snapshot.execution_items] == ["workflow::communicate-score"]
    assert "review::src/a.py::naming" in {item["id"] for item in review_snapshot.backlog_items}

    triage_snapshot = snapshot_mod.build_queue_snapshot(
        review_state,
        plan={
            "queue_order": ["triage::observe"],
            "plan_start_scores": {"strict": 80.0},
            "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
        },
    )
    assert triage_snapshot.phase == snapshot_mod.PHASE_TRIAGE_POSTFLIGHT
    assert [item["id"] for item in triage_snapshot.execution_items] == ["triage::observe"]

    assessment_with_review_snapshot = snapshot_mod.build_queue_snapshot(
        assessment_state,
        plan={
            "queue_order": [],
            "plan_start_scores": {"strict": 80.0},
            "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
            "epic_triage_meta": {"triaged_ids": ["review::src/a.py::naming"]},
        },
    )
    assert assessment_with_review_snapshot.phase == snapshot_mod.PHASE_ASSESSMENT_POSTFLIGHT
    # Subjective dimension item is suppressed when review issues cover the
    # same dimension — the assessment request alone surfaces.
    assert [item["id"] for item in assessment_with_review_snapshot.execution_items] == [
        "subjective_review::naming_quality",
    ]
    assert "review::src/a.py::naming" in {
        item["id"] for item in assessment_with_review_snapshot.backlog_items
    }
    assert "subjective::naming_quality" not in {
        item["id"] for item in assessment_with_review_snapshot.backlog_items
    }

    assessment_only_snapshot = snapshot_mod.build_queue_snapshot(
        {
            key: value
            for key, value in assessment_state.items()
            if key != "issues"
        }
        | {
            "issues": {
                "subjective_review::naming_quality": assessment_state["issues"][
                    "subjective_review::naming_quality"
                ]
            }
        },
        plan={
            "queue_order": [],
            "plan_start_scores": {"strict": 80.0},
            "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
        },
    )
    assert assessment_only_snapshot.phase == snapshot_mod.PHASE_ASSESSMENT_POSTFLIGHT
    assert [item["id"] for item in assessment_only_snapshot.execution_items] == [
        "subjective::naming_quality",
        "subjective_review::naming_quality",
    ]
    assert "review::src/a.py::naming" not in {
        item["id"] for item in assessment_only_snapshot.backlog_items
    }

    post_triage_snapshot = snapshot_mod.build_queue_snapshot(
        review_state,
        plan={
            "queue_order": [],
            "plan_start_scores": {"strict": 80.0},
            "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
            "epic_triage_meta": {"triaged_ids": ["review::src/a.py::naming"]},
        },
    )
    assert post_triage_snapshot.phase == snapshot_mod.PHASE_REVIEW_POSTFLIGHT
    assert [item["id"] for item in post_triage_snapshot.execution_items] == ["review::src/a.py::naming"]

    workflow_snapshot = snapshot_mod.build_queue_snapshot(
        {
            "dimension_scores": {
                "Naming quality": {
                    "score": 100.0,
                    "strict": 100.0,
                    "failing": 0,
                    "detectors": {
                        "subjective_assessment": {"dimension_key": "naming_quality"},
                    },
                }
            },
            "subjective_assessments": {
                "naming_quality": {
                    "score": 100.0,
                    "needs_review_refresh": False,
                }
            },
            "issues": {},
        },
        plan={
            "queue_order": ["workflow::communicate-score", "triage::observe"],
            "refresh_state": {"postflight_scan_completed_at_scan_count": 1},
        },
    )
    assert workflow_snapshot.phase == snapshot_mod.PHASE_WORKFLOW_POSTFLIGHT
    assert [item["id"] for item in workflow_snapshot.execution_items] == ["workflow::communicate-score"]

    assessment_beats_workflow_snapshot = snapshot_mod.build_queue_snapshot(
        assessment_state,
        plan={
            "queue_order": ["workflow::communicate-score", "triage::observe"],
            "refresh_state": {
                "postflight_scan_completed_at_scan_count": 1,
                "lifecycle_phase": "workflow",
            },
        },
    )
    assert assessment_beats_workflow_snapshot.phase == snapshot_mod.PHASE_WORKFLOW_POSTFLIGHT
    assert [item["id"] for item in assessment_beats_workflow_snapshot.execution_items] == [
        "workflow::communicate-score",
    ]


def test_build_subjective_items_suppresses_same_cycle_review_refresh_during_workflow() -> None:
    items = synthetic_mod.build_subjective_items(
        {
            "assessment_import_audit": [
                {"timestamp": "2026-03-13T04:19:00+00:00", "mode": "trusted_internal"}
            ],
            "dimension_scores": {
                "Naming quality": {
                    "score": 70.0,
                    "strict": 70.0,
                    "failing": 1,
                    "detectors": {
                        "subjective_assessment": {"dimension_key": "naming_quality"},
                    },
                }
            },
            "subjective_assessments": {
                "naming_quality": {
                    "score": 70.0,
                    "assessed_at": "2026-03-13T04:19:00+00:00",
                    "needs_review_refresh": True,
                    "refresh_reason": "review_issue_wontfix",
                    "stale_since": "2026-03-13T04:39:00+00:00",
                }
            },
        },
        {},
        threshold=95.0,
        plan={
            "refresh_state": {
                "lifecycle_phase": "workflow",
                "postflight_scan_completed_at_scan_count": 1,
            }
        },
    )

    assert items == []


def test_queue_snapshot_prefers_deferred_disposition_over_run_scan() -> None:
    plan = {
        "queue_order": [],
        "skipped": {"unused::a": {"kind": "temporary"}},
        "plan_start_scores": {"strict": 75.0},
    }
    state = {
        "issues": {
            "unused::a": {
                "id": "unused::a",
                "detector": "unused",
                "status": "open",
                "file": "src/a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "unused import",
                "detail": {},
            }
        }
    }
    snapshot = snapshot_mod.build_queue_snapshot(state, plan=plan)
    assert snapshot.phase == snapshot_mod.PHASE_SCAN
    assert [item["id"] for item in snapshot.execution_items] == ["workflow::deferred-disposition"]


def test_coarse_lifecycle_phase_collapses_internal_review_workflow_and_triage() -> None:
    from desloppify.engine._plan.refresh_lifecycle import COARSE_PHASE_MAP

    assert COARSE_PHASE_MAP[snapshot_mod.PHASE_REVIEW_INITIAL] == "review"
    assert COARSE_PHASE_MAP[snapshot_mod.PHASE_ASSESSMENT_POSTFLIGHT] == "review"
    assert COARSE_PHASE_MAP[snapshot_mod.PHASE_REVIEW_POSTFLIGHT] == "review"
    assert COARSE_PHASE_MAP[snapshot_mod.PHASE_WORKFLOW_POSTFLIGHT] == "workflow"
    assert COARSE_PHASE_MAP[snapshot_mod.PHASE_TRIAGE_POSTFLIGHT] == "triage"


def test_triage_playbook_commands_cover_runner_and_stage_validation() -> None:
    assert triage_playbook_mod.triage_run_stages_command() == (
        "desloppify plan triage --run-stages --runner codex"
    )
    assert triage_playbook_mod.triage_run_stages_command(
        runner="claude", only_stages=("observe", "reflect")
    ) == "desloppify plan triage --run-stages --runner claude --only-stages observe,reflect"

    try:
        triage_playbook_mod.triage_run_stages_command(runner="other")
    except ValueError as exc:
        assert "Unsupported triage runner" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected unsupported runner to raise")

    try:
        triage_playbook_mod.triage_run_stages_command(only_stages=("observe", "commit"))
    except ValueError as exc:
        assert "Unsupported triage stage" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected unsupported stage to raise")

    runner_cmds = triage_playbook_mod.triage_runner_commands(only_stages="observe")
    assert runner_cmds[0][0] == "Codex"
    assert runner_cmds[1][0] == "Claude"
    assert triage_playbook_mod.triage_manual_stage_command("reflect") == (
        triage_playbook_mod.TRIAGE_CMD_REFLECT
    )
    assert triage_playbook_mod.TRIAGE_STAGE_DEPENDENCIES["commit"] == {"sense-check"}

    try:
        triage_playbook_mod.triage_manual_stage_command("nope")
    except ValueError as exc:
        assert "Unsupported triage stage" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected invalid stage to raise")
