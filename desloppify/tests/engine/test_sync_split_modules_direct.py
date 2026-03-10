"""Direct tests for split engine plan/scoring/lifecycle helper modules."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.engine._plan.auto_cluster_sync_issue as auto_cluster_sync_mod
import desloppify.engine._plan.constants as plan_constants_mod
import desloppify.engine._plan.reconcile_review_import as reconcile_import_mod
import desloppify.engine._plan.schema.helpers as schema_helpers_mod
import desloppify.engine._plan.sync.auto_prune as sync_auto_prune_mod
import desloppify.engine._plan.sync.context as sync_context_mod
import desloppify.engine._plan.sync.triage_start_policy as triage_start_policy_mod
import desloppify.engine._plan.sync.workflow as sync_workflow_mod
import desloppify.engine._plan.triage.dismiss as triage_dismiss_mod
import desloppify.engine._plan.triage.playbook as triage_playbook_mod
import desloppify.engine._scoring.state_integration_subjective as scoring_subjective_mod
import desloppify.engine._work_queue.lifecycle as lifecycle_mod


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
        epics=[{"dismissed": ["id2"]}],
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
        {"unused": {"name": "unused"}},
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
        {"unused": {"name": "unused"}},
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
        policy=SimpleNamespace(unscored_ids={"subjective::x"}, has_objective_backlog=True),
        scores_just_imported=True,
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


def test_sync_communicate_score_reinjects_after_trusted_score_import() -> None:
    plan = {
        "queue_order": ["triage::observe"],
        "plan_start_scores": {
            "strict": 70.0,
            "overall": 70.0,
            "objective": 80.0,
            "verified": 80.0,
        },
        "previous_plan_start_scores": {"strict": 65.0},
    }

    result = sync_workflow_mod.sync_communicate_score_needed(
        plan,
        state={"issues": {}},
        scores_just_imported=True,
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


def test_subjective_integrity_helpers_apply_penalty_threshold(monkeypatch) -> None:
    monkeypatch.setattr(scoring_subjective_mod, "matches_target_score", lambda score, target: score >= target)

    assessments = {
        "naming_quality": {"score": 95},
        "design_coherence": {"score": 96},
        "error_consistency": {"score": 60},
    }
    adjusted, meta = scoring_subjective_mod._apply_subjective_integrity_policy(
        assessments,
        target=95,
    )
    assert meta["status"] == "penalized"
    assert set(meta["reset_dimensions"]) == {"design_coherence", "naming_quality"}
    assert adjusted["naming_quality"]["score"] == 0.0

    assert scoring_subjective_mod._coerce_subjective_score({"score": "101"}) == 100.0
    assert scoring_subjective_mod._normalize_integrity_target(120.0) == 100.0
    assert scoring_subjective_mod._normalize_integrity_target(None) is None


def test_lifecycle_filter_respects_initial_reviews_triage_and_endgame_rules() -> None:
    initial_items = [
        {"kind": "subjective_dimension", "id": "subjective::naming", "initial_review": True},
        {"kind": "issue", "id": "unused::a", "detector": "unused"},
    ]
    filtered_initial = lifecycle_mod.apply_lifecycle_filter(initial_items)
    assert filtered_initial == [initial_items[0]]

    triage_and_objective = [
        {"kind": "workflow_stage", "id": "triage::observe"},
        {"kind": "issue", "id": "unused::a", "detector": "unused"},
        {"kind": "subjective_dimension", "id": "subjective::naming", "initial_review": False},
    ]
    filtered_mid = lifecycle_mod.apply_lifecycle_filter(triage_and_objective)
    assert all(not str(item.get("id", "")).startswith("triage::") for item in filtered_mid)
    assert all(item.get("kind") != "subjective_dimension" for item in filtered_mid)

    endgame_items = [
        {"kind": "workflow_stage", "id": "triage::observe"},
        {"kind": "workflow_action", "id": "workflow::create-plan"},
    ]
    filtered_endgame = lifecycle_mod.apply_lifecycle_filter(endgame_items)
    assert filtered_endgame == endgame_items

    subjective_before_score_and_triage = [
        {"kind": "workflow_action", "id": "workflow::communicate-score"},
        {"kind": "workflow_stage", "id": "triage::observe"},
        {"kind": "subjective_dimension", "id": "subjective::naming", "initial_review": False},
    ]
    filtered_subjective_phase = lifecycle_mod.apply_lifecycle_filter(
        subjective_before_score_and_triage
    )
    assert filtered_subjective_phase == [subjective_before_score_and_triage[2]]

    forced_items = [
        {
            "kind": "workflow_stage",
            "id": "triage::observe",
            "force_visible": True,
        },
        {"kind": "issue", "id": "unused::a", "detector": "unused"},
        {
            "kind": "subjective_dimension",
            "id": "subjective::naming",
            "initial_review": False,
            "force_visible": True,
        },
    ]
    filtered_forced = lifecycle_mod.apply_lifecycle_filter(forced_items)
    forced_ids = {str(item.get("id", "")) for item in filtered_forced}
    assert "triage::observe" in forced_ids
    assert "subjective::naming" in forced_ids


def test_lifecycle_filter_treats_clusters_as_objective() -> None:
    """Clusters containing objective issues should prevent triage from forcing."""
    items = [
        {"kind": "workflow_stage", "id": "triage::observe"},
        {"kind": "cluster", "id": "auto/complexity_reduction", "detector": "complexity"},
    ]
    filtered = lifecycle_mod.apply_lifecycle_filter(items)
    # Cluster is objective work — triage should be hidden, cluster shown
    assert any(item["kind"] == "cluster" for item in filtered)
    assert all(not str(item.get("id", "")).startswith("triage::") for item in filtered)


def test_lifecycle_filter_forces_triage_when_only_subjective_clusters() -> None:
    """When only subjective clusters remain, triage should still be forced."""
    items = [
        {"kind": "workflow_stage", "id": "triage::observe"},
        {"kind": "cluster", "id": "auto/subjective_review", "detector": "subjective_assessment"},
    ]
    filtered = lifecycle_mod.apply_lifecycle_filter(items)
    # Subjective cluster is not objective — triage should be forced
    assert any(str(item.get("id", "")).startswith("triage::") for item in filtered)


def test_endgame_only_detectors_is_subset_of_non_objective() -> None:
    """ENDGAME_ONLY_DETECTORS must be a subset of NON_OBJECTIVE_DETECTORS."""
    from desloppify.engine.plan_queue import NON_OBJECTIVE_DETECTORS

    assert lifecycle_mod.ENDGAME_ONLY_DETECTORS <= NON_OBJECTIVE_DETECTORS
    # Verify the constant is non-empty (guard against accidental clearing)
    assert len(lifecycle_mod.ENDGAME_ONLY_DETECTORS) >= 1


def test_is_endgame_only_uses_endgame_detectors_constant() -> None:
    """_is_endgame_only should match items by the ENDGAME_ONLY_DETECTORS set."""
    for det in lifecycle_mod.ENDGAME_ONLY_DETECTORS:
        item = {"kind": "issue", "id": f"{det}::x", "detector": det}
        assert lifecycle_mod._is_endgame_only(item) is True

    # Non-endgame non-objective detectors should NOT be endgame-only
    from desloppify.engine.plan_queue import NON_OBJECTIVE_DETECTORS

    for det in NON_OBJECTIVE_DETECTORS - lifecycle_mod.ENDGAME_ONLY_DETECTORS:
        item = {"kind": "issue", "id": f"{det}::x", "detector": det}
        assert lifecycle_mod._is_endgame_only(item) is False


def test_lifecycle_filter_hides_subjective_review_issue_while_objective_work_exists() -> None:
    items = [
        {"kind": "issue", "id": "unused::a", "detector": "unused"},
        {
            "kind": "issue",
            "id": "subjective_review::src/a.py::changed",
            "detector": "subjective_review",
        },
    ]

    filtered = lifecycle_mod.apply_lifecycle_filter(items)

    ids = {str(item.get("id", "")) for item in filtered}
    assert "unused::a" in ids
    assert "subjective_review::src/a.py::changed" not in ids


def test_lifecycle_filter_hides_subjective_review_cluster_while_objective_work_exists() -> None:
    items = [
        {"kind": "issue", "id": "unused::a", "detector": "unused"},
        {"kind": "cluster", "id": "auto/subjective_review", "detector": "subjective_review"},
    ]

    filtered = lifecycle_mod.apply_lifecycle_filter(items)

    ids = {str(item.get("id", "")) for item in filtered}
    assert "unused::a" in ids
    assert "auto/subjective_review" not in ids


def test_lifecycle_filter_shows_subjective_review_when_objective_queue_is_drained() -> None:
    items = [
        {"kind": "workflow_stage", "id": "triage::observe"},
        {
            "kind": "issue",
            "id": "subjective_review::src/a.py::changed",
            "detector": "subjective_review",
        },
    ]

    filtered = lifecycle_mod.apply_lifecycle_filter(items)

    assert filtered == [items[1]]


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
