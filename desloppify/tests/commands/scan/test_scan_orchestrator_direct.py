"""Direct behavior tests for scan orchestrator forwarding."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.app.commands.scan.workflow as scan_workflow_mod
from desloppify.app.commands.scan.orchestrator import ScanOrchestrator
from desloppify.app.commands.scan.workflow import ScanMergeResult, ScanNoiseSnapshot


def test_scan_orchestrator_forwards_runtime_and_payloads() -> None:
    runtime = SimpleNamespace(state={"issues": {}}, config={"issue_noise_budget": 10})
    calls: dict[str, object] = {}

    def _generate(rt):
        calls["generate"] = rt
        return ([{"id": "a"}], {"potential": 1}, {"loc": 10})

    def _merge(rt, issues, potentials, metrics):
        calls["merge"] = (rt, issues, potentials, metrics)
        return ScanMergeResult(
            diff={"open_delta": 1},
            prev_overall=80.0,
            prev_objective=95.0,
            prev_strict=75.0,
            prev_verified=70.0,
            prev_dim_scores={},
        )

    def _noise_snapshot(state, config):
        calls["noise"] = (state, config)
        return ScanNoiseSnapshot(
            noise_budget=10,
            global_noise_budget=0,
            budget_warning=None,
            hidden_by_detector={"smells": 1},
            hidden_total=1,
        )

    def _persist(rt, narrative):
        calls["persist"] = (rt, narrative)

    orchestrator = ScanOrchestrator(
        runtime=runtime,
        run_scan_generation_fn=_generate,
        merge_scan_results_fn=_merge,
        resolve_noise_snapshot_fn=_noise_snapshot,
        persist_reminder_history_fn=_persist,
    )

    issues, potentials, metrics = orchestrator.generate()
    assert issues == [{"id": "a"}]
    assert potentials == {"potential": 1}
    assert metrics == {"loc": 10}
    assert calls["generate"] is runtime

    merge_result = orchestrator.merge(issues, potentials, metrics)
    assert merge_result.diff == {"open_delta": 1}
    assert calls["merge"] == (runtime, issues, potentials, metrics)

    noise_snapshot = orchestrator.noise_snapshot()
    assert noise_snapshot.hidden_total == 1
    assert calls["noise"] == (runtime.state, runtime.config)

    reminder_payload = {"messages": ["re-run stale review dimensions"]}
    orchestrator.persist_reminders(reminder_payload)
    assert calls["persist"] == (runtime, reminder_payload)


def test_run_scan_generation_uses_planning_scan_surface(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(scan_workflow_mod, "enable_file_cache", lambda: calls.setdefault("file_cache_on", True))
    monkeypatch.setattr(scan_workflow_mod, "disable_file_cache", lambda: calls.setdefault("file_cache_off", True))
    monkeypatch.setattr(scan_workflow_mod, "enable_parse_cache", lambda: calls.setdefault("parse_cache_on", True))
    monkeypatch.setattr(scan_workflow_mod, "disable_parse_cache", lambda: calls.setdefault("parse_cache_off", True))
    monkeypatch.setattr(
        scan_workflow_mod,
        "generate_plan_issues",
        lambda path, *, lang, options: (
            calls.setdefault("generate", (path, lang, options)),
            ([{"id": "open-1"}], {"smells": 1}),
        )[1],
    )
    monkeypatch.setattr(
        scan_workflow_mod,
        "collect_codebase_metrics",
        lambda _lang, _path, **_kwargs: (
            calls.setdefault("metrics_kwargs", _kwargs),
            {"loc": 10},
        )[1],
    )
    monkeypatch.setattr(scan_workflow_mod, "warn_explicit_lang_with_no_files", lambda *_a, **_k: None)
    monkeypatch.setattr(scan_workflow_mod, "get_exclusions", lambda: [])
    monkeypatch.setattr(scan_workflow_mod, "_augment_stale_wontfix_impl", lambda issues, **_k: (issues, 0))

    runtime = SimpleNamespace(
        path=".",
        lang=SimpleNamespace(
            file_finder=None,
            zone_map=SimpleNamespace(all_files=lambda: ["src/a.py"]),
        ),
        effective_include_slow=True,
        zone_overrides={"src": "prod"},
        profile="full",
        args=SimpleNamespace(lang=None),
        state={},
        config={},
    )

    issues, potentials, metrics = scan_workflow_mod.run_scan_generation(runtime)

    assert issues == [{"id": "open-1"}]
    assert potentials["smells"] == 1
    assert potentials["stale_wontfix"] == 0
    assert metrics == {"loc": 10}
    assert calls["generate"][0] == "."
    assert calls["generate"][1] is runtime.lang
    assert calls["generate"][2].include_slow is True
    assert calls["generate"][2].zone_overrides == {"src": "prod"}
    assert calls["generate"][2].profile == "full"
    assert calls["metrics_kwargs"] == {"files": ["src/a.py"]}
    assert calls["file_cache_on"] is True
    assert calls["file_cache_off"] is True
    assert calls["parse_cache_on"] is True
    assert calls["parse_cache_off"] is True


def test_prepare_scan_runtime_resets_script_import_caches(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    args = SimpleNamespace(
        path=str(tmp_path),
        reset_subjective=False,
        skip_slow=False,
        profile=None,
        force_rescan=False,
    )

    monkeypatch.setattr(
        scan_workflow_mod,
        "command_runtime",
        lambda _args: SimpleNamespace(
            state_path=None,
            state={},
            config={},
        ),
    )
    monkeypatch.setattr(
        scan_workflow_mod,
        "resolve_lang",
        lambda _args: None,
    )
    monkeypatch.setattr(
        scan_workflow_mod,
        "resolve_scan_profile",
        lambda _profile, _lang: "full",
    )
    monkeypatch.setattr(
        scan_workflow_mod,
        "effective_include_slow",
        lambda include_slow, _profile: include_slow,
    )
    monkeypatch.setattr(
        scan_workflow_mod,
        "reset_script_import_caches",
        lambda scan_path: calls.append(scan_path),
    )
    monkeypatch.setattr(
        scan_workflow_mod,
        "_seed_runtime_coverage_warnings",
        lambda _lang: [],
    )

    runtime = scan_workflow_mod.prepare_scan_runtime(args)

    assert runtime.path == tmp_path
    assert calls == [str(tmp_path)]
