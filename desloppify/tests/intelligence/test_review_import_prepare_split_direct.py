"""Direct tests for review importing/preparation split helper modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.intelligence.review.importing.contracts_validation as contracts_validation_mod
import desloppify.intelligence.review.importing.holistic_cache as holistic_cache_mod
import desloppify.intelligence.review.importing.holistic_issue_flow as issue_flow_mod
import desloppify.intelligence.review.importing.resolution as resolution_mod
import desloppify.intelligence.review.importing.state_helpers as state_helpers_mod
import desloppify.intelligence.review.prepare_batches_core as prepare_batches_core_mod
import desloppify.intelligence.review.prepare_batches_collectors_quality as collectors_quality_mod
import desloppify.intelligence.review.prepare_batches_collectors_structure as collectors_structure_mod
import desloppify.intelligence.review.prepare_holistic_batches as holistic_batches_mod
import desloppify.intelligence.review.prepare_holistic_orchestration as orchestration_mod
import desloppify.intelligence.review.prepare_holistic_payload_parts as payload_parts_mod
import desloppify.intelligence.review.prepare_holistic_scope as scope_mod


def test_contract_validation_accepts_valid_payload_and_dismissed_entries() -> None:
    valid_issue, errors = contracts_validation_mod.validate_review_issue_payload(
        {
            "dimension": "naming_quality",
            "identifier": "id1",
            "summary": "Rename variable",
            "confidence": "high",
            "suggestion": "Use descriptive name",
            "related_files": ["src/a.py"],
            "evidence": ["line 10"],
        },
        label="issues[0]",
        allowed_dimensions={"naming_quality"},
    )
    assert errors == []
    assert valid_issue is not None

    dismissed, errors = contracts_validation_mod.validate_review_issue_payload(
        {
            "concern_verdict": "dismissed",
            "concern_fingerprint": "fp1",
        },
        label="issues[1]",
        allow_dismissed=True,
    )
    assert errors == []
    assert dismissed is not None
    assert dismissed["concern_verdict"] == "dismissed"


def test_holistic_cache_update_and_resolution_helpers(monkeypatch) -> None:
    monkeypatch.setattr(holistic_cache_mod, "load_dimensions_for_lang", lambda _name: ([], {"naming_quality": {}}, "sys"))

    state: dict = {
        "issues": {
            "subjective_review::.::naming_quality": {
                "id": "subjective_review::.::naming_quality",
                "detector": "subjective_review",
                "status": "open",
                "file": ".",
                "detail": {"reason": "unassessed", "dimension": "naming_quality"},
            },
            "subjective_review::.::logic_clarity": {
                "id": "subjective_review::.::logic_clarity",
                "detector": "subjective_review",
                "status": "open",
                "file": ".",
                "detail": {"reason": "stale", "dimension": "logic_clarity"},
            },
        },
        "review_cache": {"files": {"src/a.py": {}, "src/b.py": {}}},
        "subjective_assessments": {
            "naming_quality": {"score": 70},
        },
    }

    holistic_cache_mod.update_holistic_review_cache(
        state,
        issues_data=[
            {"dimension": "naming_quality", "identifier": "id1", "summary": "x", "confidence": "high"}
        ],
        lang_name="python",
        review_scope={"total_files": 10, "reviewed_files_count": 2, "full_sweep_included": True},
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
    )
    assert state["review_cache"]["holistic"]["issue_count"] == 1
    assert holistic_cache_mod._resolve_total_files(state, "python") == 2

    # resolve_holistic_coverage_issues marks dimension-level issues fixed for assessed dims
    diff = {"auto_resolved": 0}
    holistic_cache_mod.resolve_holistic_coverage_issues(
        state,
        diff,
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
    )
    # naming_quality is assessed, so its issue should be resolved
    assert diff["auto_resolved"] == 1
    assert state["work_items"]["subjective_review::.::naming_quality"]["status"] == "fixed"

    # resolve_reviewed_file_coverage_issues is now a no-op
    diff = {"auto_resolved": 0}
    holistic_cache_mod.resolve_reviewed_file_coverage_issues(
        state,
        diff,
        reviewed_files=["src/a.py"],
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
    )
    assert diff["auto_resolved"] == 0


def test_issue_flow_build_collect_and_auto_resolve_paths(monkeypatch) -> None:
    monkeypatch.setattr(issue_flow_mod, "validate_review_issue_payload", contracts_validation_mod.validate_review_issue_payload)
    monkeypatch.setattr(issue_flow_mod, "normalize_review_confidence", lambda c: str(c))
    monkeypatch.setattr(issue_flow_mod, "review_tier", lambda _c, holistic=True: 2)

    issues, skipped, dismissed = issue_flow_mod.validate_and_build_issues(
        [
            {
                "dimension": "naming_quality",
                "identifier": "id1",
                "summary": "Rename variable",
                "confidence": "high",
                "suggestion": "Use descriptive name",
                "related_files": ["src/a.py"],
                "evidence": ["line 10"],
            },
            {
                "concern_verdict": "dismissed",
                "concern_fingerprint": "fp2",
            },
        ],
        {"naming_quality": {}},
        "python",
    )
    assert len(issues) == 1
    assert skipped == []
    assert dismissed and dismissed[0]["fingerprint"] == "fp2"
    assert issues[0]["detail"]["summary_hash"]
    assert "content_hash" not in issues[0]["detail"]

    imported = issue_flow_mod.collect_imported_dimensions(
        issues_list=[{"dimension": "Naming Quality"}],
        review_issues=issues,
        assessments={"naming_quality": 80},
        review_scope={"imported_dimensions": ["naming_quality"]},
        valid_dimensions={"naming_quality"},
    )
    assert imported == {"naming_quality"}

    state = {
        "issues": {
            "review::old": {
                "id": "review::old",
                "detector": "review",
                "status": "open",
                "detail": {"holistic": True, "dimension": "naming_quality"},
            }
        }
    }
    diff = {"auto_resolved": 0}
    issue_flow_mod.auto_resolve_stale_holistic(
        state,
        new_ids=set(),
        diff=diff,
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
        imported_dimensions={"naming_quality"},
        full_sweep_included=False,
    )
    assert diff["auto_resolved"] == 1
    assert state["work_items"]["review::old"]["status"] == "fixed"


def test_resolution_and_state_helper_utilities() -> None:
    state: dict = {
        "issues": {
            "id1": {"status": "open", "detector": "review"},
            "id2": {"status": "fixed", "detector": "review"},
        }
    }
    diff = {"auto_resolved": 0}
    resolution_mod.auto_resolve_review_issues(
        state,
        new_ids=set(),
        diff=diff,
        note="reimported",
        should_resolve=lambda issue: issue.get("detector") == "review",
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
    )
    assert diff["auto_resolved"] == 1
    assert state["work_items"]["id1"]["status"] == "fixed"

    cache = state_helpers_mod.ensure_review_file_cache({})
    assert cache == {}
    potentials = state_helpers_mod.ensure_lang_potentials({}, "python")
    assert potentials == {}


def test_collectors_scope_payload_parts_and_orchestration_helpers(monkeypatch, tmp_path) -> None:
    ctx = SimpleNamespace(
        architecture={"god_modules": [{"file": "src/a.py"}]},
        coupling={"module_level_io": [{"file": "src/b.py"}], "boundary_violations": []},
        dependencies={"deferred_import_density": [], "cycle_summaries": []},
        conventions={"sibling_behavior": {}, "duplicate_clusters": [], "naming_drift": []},
        errors={"strategy_by_directory": {}, "exception_hotspots": []},
        abstractions={"util_files": [], "pass_through_wrappers": []},
        testing={"critical_untested": [{"file": "src/t.py"}]},
        api_surface={"sync_async_mix": ["src/api.py"]},
        authorization={"route_auth_coverage": {}, "service_role_usage": [], "rls_coverage": {}},
        ai_debt_signals={"file_signals": {"src/debt.py": {}}},
        migration_signals={"deprecated_markers": {"files": []}, "migration_todos": []},
        structure={"flat_dir_issues": [], "root_files": [], "directory_profiles": {}, "coupling_matrix": {}},
        scan_evidence={"mutable_globals": [], "complexity_hotspots": [], "error_hotspots": [], "signal_density": []},
        index=SimpleNamespace(files={}),
    )

    assert collectors_quality_mod._arch_coupling_files(ctx)
    assert collectors_quality_mod._testing_api_files(ctx)
    assert collectors_structure_mod._ai_debt_files(ctx)

    allowed = scope_mod.collect_allowed_review_files(["src/a.py", "tests/a_test.py"], SimpleNamespace(zone_map=None), base_path=tmp_path)
    assert "src/a.py" in allowed
    assert scope_mod.file_in_allowed_scope("src/a.py", allowed) is True

    batches = [
        {
            "dimensions": ["naming_quality"],
            "concern_signals": [{"file": "src/a.py"}, {"file": "tests/a_test.py"}],
            "historical_issue_focus": {"issues": [{"related_files": ["src/a.py", "tests/a_test.py"]}]},
        }
    ]
    scoped_batches = scope_mod.filter_batches_to_file_scope(batches, allowed_files={"src/a.py"})
    assert scoped_batches[0]["concern_signals"] == [{"file": "src/a.py"}]

    selected = payload_parts_mod._build_selected_prompts(
        ["naming_quality"],
        {"naming_quality": {"prompt": "a"}},
        {},
    )
    assert "naming_quality" in selected

    monkeypatch.setattr(payload_parts_mod, "build_issue_history_context", lambda _state, options: {"issues": [{"id": "i1"}]})
    monkeypatch.setattr(payload_parts_mod, "build_batch_issue_focus", lambda _history, **_kw: {"issues": [{"related_files": ["src/a.py"]}]})

    payload: dict = {}
    history_batches = payload_parts_mod._attach_issue_history_context(
        payload,
        [{"dimensions": ["naming_quality"], "files_to_read": ["src/a.py"]}],
        state={},
        options=SimpleNamespace(include_issue_history=True, issue_history_max_issues=10, issue_history_max_batch_items=5),
        allowed_review_files={"src/a.py"},
    )
    assert payload["historical_review_issues"]["issues"][0]["id"] == "i1"
    assert history_batches

    files, allowed_files = orchestration_mod._resolve_review_files(
        tmp_path,
        SimpleNamespace(file_finder=lambda _p: ["src/a.py"], name="python"),
        SimpleNamespace(files=None),
    )
    assert files == ["src/a.py"]
    assert "src/a.py" in allowed_files

    dim_ctx = orchestration_mod._resolve_dimension_context(
        "python",
        SimpleNamespace(dimensions=["naming_quality"]),
        load_dimensions_for_lang_fn=lambda _name: (["naming_quality"], {"naming_quality": {"prompt": "x"}}, "sys"),
        resolve_dimensions_fn=lambda cli_dimensions, default_dimensions: cli_dimensions or default_dimensions,
        get_lang_guidance_fn=lambda _name: "guide",
    )
    assert dim_ctx.dims == ["naming_quality"]
    assert dim_ctx.lang_guide == "guide"


def test_authorization_collector_includes_with_auth_siblings_same_directory() -> None:
    ctx = SimpleNamespace(
        authorization={
            "route_auth_coverage": {
                "api/health.py": {"handlers": 1, "with_auth": 1, "without_auth": 0},
                "routes/admin.py": {"handlers": 2, "with_auth": 0, "without_auth": 2},
                "routes/reports.py": {"handlers": 3, "with_auth": 3, "without_auth": 0},
                "routes/users.py": {"handlers": 2, "with_auth": 2, "without_auth": 0},
            },
            "service_role_usage": ["lib/supabase.ts"],
            "rls_coverage": {},
        }
    )

    files = collectors_structure_mod._authorization_files(ctx, max_files=10)

    assert files[:4] == [
        "routes/admin.py",
        "routes/reports.py",
        "routes/users.py",
        "lib/supabase.ts",
    ]


def test_prepare_holistic_payload_compacts_batch_dimension_contexts() -> None:
    deps = orchestration_mod.HolisticPrepareDependencies(
        is_file_cache_enabled_fn=lambda: False,
        enable_file_cache_fn=lambda: None,
        disable_file_cache_fn=lambda: None,
        build_holistic_context_fn=lambda *_args, **_kwargs: {"codebase_stats": {"total_files": 1}},
        build_review_context_fn=lambda *_args, **_kwargs: SimpleNamespace(),
        load_dimensions_for_lang_fn=lambda _name: (
            ["naming_quality"],
            {"naming_quality": {"prompt": "Assess naming"}},
            "sys",
        ),
        resolve_dimensions_fn=lambda cli_dimensions, default_dimensions: cli_dimensions or default_dimensions,
        get_lang_guidance_fn=lambda _name: "guide",
        assemble_holistic_batches_fn=lambda *_args, **_kwargs: [
            {
                "name": "Naming",
                "dimensions": ["naming_quality"],
                "files_to_read": ["src/a.py"],
                "why": "seed",
            }
        ],
        holistic_batch_deps=holistic_batches_mod.HolisticBatchAssemblyDependencies(
            build_investigation_batches_fn=lambda *_args, **_kwargs: [],
            batch_concerns_fn=lambda *_args, **_kwargs: None,
            filter_batches_to_dimensions_fn=lambda batches, _dims, **_kwargs: batches,
            append_full_sweep_batch_fn=lambda **_kwargs: None,
            log_best_effort_failure_fn=lambda *_args, **_kwargs: None,
            logger=object(),
        ),
        serialize_context_fn=lambda _ctx: {},
    )
    payload = orchestration_mod.prepare_holistic_review_payload(
        Path("."),
        SimpleNamespace(name="python", file_finder=lambda _path: ["src/a.py"], zone_map=None),
        state={
            "dimension_contexts": {
                "naming_quality": {
                    "insights": [
                        {
                            "header": "Names map to command intent",
                            "description": "Full rationale should remain packet-level only.",
                            "settled": True,
                            "positive": True,
                        }
                    ]
                }
            }
        },
        options=SimpleNamespace(
            files=["src/a.py"],
            dimensions=["naming_quality"],
            include_full_sweep=False,
            max_files_per_batch=10,
            include_issue_history=False,
            issue_history_max_issues=10,
            issue_history_max_batch_items=5,
        ),
        deps=deps,
    )

    assert payload["dimension_contexts"]["naming_quality"]["insights"][0]["description"]
    batch_ctx = payload["investigation_batches"][0]["dimension_contexts"]["naming_quality"]
    assert batch_ctx["insights"] == [
        {
            "header": "Names map to command intent",
            "settled": True,
            "positive": True,
        }
    ]


def test_holistic_batch_assembly_skips_concerns_for_inactive_dimension() -> None:
    deps = holistic_batches_mod.HolisticBatchAssemblyDependencies(
        build_investigation_batches_fn=lambda *_args, **_kwargs: [
            {
                "name": "high_level_elegance",
                "dimensions": ["high_level_elegance"],
                "files_to_read": ["src/a.py"],
                "why": "seed",
            }
        ],
        batch_concerns_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("concern batching should stay inactive")
        ),
        filter_batches_to_dimensions_fn=lambda batches, _dims, **_kwargs: batches,
        append_full_sweep_batch_fn=lambda **_kwargs: None,
        log_best_effort_failure_fn=lambda *_args, **_kwargs: None,
        logger=object(),
    )

    batches = holistic_batches_mod.assemble_holistic_batches(
        {},
        lang=SimpleNamespace(name="python"),
        repo_root=Path("."),
        state={},
        dims=["high_level_elegance"],
        all_files=["src/a.py"],
        allowed_review_files={"src/a.py"},
        include_full_sweep=False,
        max_files_per_batch=10,
        deps=deps,
    )

    assert batches == [
        {
            "name": "high_level_elegance",
            "dimensions": ["high_level_elegance"],
            "files_to_read": ["src/a.py"],
            "why": "seed",
            "concern_signals": [],
        }
    ]


def test_authorization_collector_uses_module_fallback_for_with_auth_siblings() -> None:
    ctx = SimpleNamespace(
        authorization={
            "route_auth_coverage": {
                "routes/admin/audit.py": {"handlers": 2, "with_auth": 0, "without_auth": 2},
                "routes/internal/guarded.py": {"handlers": 2, "with_auth": 2, "without_auth": 0},
                "ui/home.py": {"handlers": 1, "with_auth": 1, "without_auth": 0},
            },
            "service_role_usage": [],
            "rls_coverage": {},
        }
    )

    files = collectors_structure_mod._authorization_files(ctx, max_files=10)

    assert "routes/admin/audit.py" in files
    assert "routes/internal/guarded.py" in files
    assert "ui/home.py" not in files


def test_authorization_collector_excludes_guidance_like_runtime_paths() -> None:
    ctx = SimpleNamespace(
        authorization={
            "route_auth_coverage": {
                "guidance/auth_examples.py": {
                    "handlers": 1,
                    "with_auth": 0,
                    "without_auth": 1,
                },
                "src/routes/admin.py": {"handlers": 1, "with_auth": 0, "without_auth": 1},
            },
            "service_role_usage": ["prompts/security_prompt.ts", "src/lib/supabase.ts"],
            "rls_coverage": {
                "files": {
                    "accounts": ["docs/rls_examples.sql", "db/schema.sql"],
                }
            },
        }
    )

    files = collectors_structure_mod._authorization_files(ctx, max_files=10)

    assert files == ["src/routes/admin.py", "src/lib/supabase.ts", "db/schema.sql"]


def test_prepare_batches_core_path_normalization_rules() -> None:
    assert prepare_batches_core_mod._normalize_file_path(" src/app.py ") == "src/app.py"
    assert prepare_batches_core_mod._normalize_file_path('"README",') == "README"
    assert prepare_batches_core_mod._normalize_file_path("'Dockerfile'") == "Dockerfile"
    assert prepare_batches_core_mod._normalize_file_path("src/config") is None
    assert prepare_batches_core_mod._normalize_file_path("src/dir/") is None
    assert prepare_batches_core_mod._normalize_file_path(".") is None
    assert prepare_batches_core_mod._normalize_file_path("..") is None
    assert prepare_batches_core_mod._normalize_file_path(123) is None


def test_prepare_batches_core_collectors_preserve_order_and_limits() -> None:
    files = prepare_batches_core_mod._collect_unique_files(
        [
            [
                {"file": "src/a.py"},
                {"file": "src/b.py"},
                {"file": "src/a.py"},
            ],
            [
                {"file": "'README'"},
                {"file": "src/noext"},
                {"file": "src/c.py,"},
            ],
        ],
        max_files=4,
    )
    assert files == ["src/a.py", "src/b.py", "README", "src/c.py"]

    files_from_batches = prepare_batches_core_mod._collect_files_from_batches(
        [
            {"files_to_read": ["src/a.py", "src/a.py", "src/noext"]},
            {"files_to_read": ["src/b.py,", '"README"']},
            {"files_to_read": ["src/c.py"]},
        ],
        max_files=3,
    )
    assert files_from_batches == ["src/a.py", "src/b.py", "README"]


def test_prepare_batches_core_directory_profile_mapping_and_context_coercion() -> None:
    context = prepare_batches_core_mod._ensure_holistic_context(
        {
            "structure": {
                "directory_profiles": {
                    "src/": {
                        "files": ["a.py", "b.py", "README", "noext", "nested/"],
                    },
                    ".": {"files": ["main.py", "README", "config"]},
                }
            }
        }
    )

    assert prepare_batches_core_mod._representative_files_for_directory(
        context,
        "src",
        max_files=2,
    ) == ["src/a.py", "src/b.py"]
    assert prepare_batches_core_mod._representative_files_for_directory(
        context,
        ".",
        max_files=3,
    ) == ["main.py", "README"]
    assert (
        prepare_batches_core_mod._representative_files_for_directory(
            context,
            "missing",
        )
        == []
    )
