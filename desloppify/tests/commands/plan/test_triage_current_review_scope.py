"""Canonical review context and current-cluster organize gates."""

from __future__ import annotations

import argparse
import copy
from types import SimpleNamespace

import pytest

from desloppify.app.commands.plan.triage.observe_batches import (
    group_issues_into_observe_batches,
)
from desloppify.app.commands.plan.triage.runner.stage_prompts_observe import (
    build_observe_batch_prompt,
)
from desloppify.app.commands.plan.triage.stages import organize
from desloppify.app.commands.plan.triage.validation.organize_policy import (
    _manual_clusters_or_error,
)
from desloppify.engine._plan.triage.snapshot import manual_clusters_with_issues
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.schema import empty_state
from desloppify.engine.plan_state import empty_plan
from desloppify.engine.plan_triage import (
    collect_triage_input,
    detect_recurring_patterns,
)


def _review(name: str = "holistic::type_safety::public_entrypoint_contract"):
    return make_issue(
        "review",
        ".",
        name,
        tier=2,
        confidence="high",
        summary="Public entrypoints lack argument and return contracts",
        detail={
            "dimension": "type_safety",
            "related_files": ["src/commands.py", "src/client.py"],
            "evidence": [
                "src/commands.py main omits its argument annotation.",
                "src/client.py run omits its exit contract. "
                + "Evidence remains complete. " * 20,
            ],
            "suggestion": "Annotate the actual command and client entrypoints.",
        },
    )


def test_normalized_review_context_survives_collection_batching_and_prompt(
    set_project_root,
):
    issue = _review()
    state = empty_state()
    state["work_items"][issue["id"]] = issue
    plan = empty_plan()
    before = copy.deepcopy(issue)
    batches = group_issues_into_observe_batches(collect_triage_input(plan, state))
    assert len(batches) == 1
    dimensions, subset = batches[0]
    prompt = build_observe_batch_prompt(
        1, 1, dimensions, subset, repo_root=set_project_root
    )
    assert issue["summary"] in prompt
    assert f"Issue ID: {issue['id']}" in prompt
    assert f"— `{issue['file']}`" in prompt
    for path in issue["detail"]["related_files"]:
        assert path in prompt
    for claim in issue["detail"]["evidence"]:
        assert claim in prompt
    assert issue["detail"]["suggestion"] in prompt
    assert subset[issue["id"]] is issue
    assert issue == before
    assert "Do NOT run any `desloppify` commands" in prompt


def test_canonical_display_fields_take_priority_over_legacy_fields(tmp_path):
    issue = _review()
    issue.update(
        {
            "title": "Stale legacy title",
            "description": "Retained legacy description",
            "file": "src/commands.py",
        }
    )
    issue["detail"]["file_path"] = "src/old.py"
    prompt = build_observe_batch_prompt(
        1, 1, ["type_safety"], {issue["id"]: issue}, repo_root=tmp_path
    )
    assert issue["summary"] in prompt
    assert "— `src/commands.py`" in prompt
    assert "Stale legacy title" not in prompt
    assert "src/old.py" not in prompt
    assert "Retained legacy description" in prompt


def test_legacy_display_fallback_retains_full_identity(tmp_path):
    fid = "review::src/legacy.py::abcdef12"
    legacy = {
        "title": "Legacy title",
        "description": "Legacy detail",
        "detail": {"dimension": "naming_quality", "file_path": "src/legacy.py"},
    }
    prompt = build_observe_batch_prompt(
        1, 1, ["naming_quality"], {fid: legacy}, repo_root=tmp_path
    )
    for value in ["Legacy title", "Legacy detail", "src/legacy.py", f"Issue ID: {fid}"]:
        assert value in prompt


def test_full_ids_remain_distinguishable_when_display_prefixes_collide(tmp_path):
    rows = {
        f"review::src/{name}.py::abcdef12": {"title": f"{name} issue", "detail": {}}
        for name in ["one", "two"]
    }
    prompt = build_observe_batch_prompt(1, 1, ["type_safety"], rows, repo_root=tmp_path)
    for fid in rows:
        assert prompt.count(f"Issue ID: {fid}") == 1
    assert prompt.index("one issue") < prompt.index("two issue")


def test_optional_review_details_only_render_supported_strings(tmp_path):
    issue = _review()
    issue["detail"].update(
        {
            "related_files": ["src/current.py", 42, None],
            "evidence": [None, 42, "Actual source evidence"],
            "suggestion": {"invalid": "suggestion"},
        }
    )
    prompt = build_observe_batch_prompt(
        1, 1, ["type_safety"], {issue["id"]: issue}, repo_root=tmp_path
    )
    assert "Related files: `src/current.py`" in prompt
    assert "Evidence: Actual source evidence" in prompt
    assert "Suggestion:" not in prompt
    assert "42" not in prompt


def _fixture(operation_count=3):
    issue = _review()
    state = empty_state()
    state["work_items"][issue["id"]] = issue
    plan = empty_plan()
    plan["queue_order"] = ["triage::organize", issue["id"]]
    meta = plan["epic_triage_meta"]
    meta["active_triage_issue_ids"] = [issue["id"]]
    meta["triage_stages"] = {
        "observe": {
            "report": "Observed current command contract.",
            "confirmed_at": "2026-01-01T00:00:00Z",
        },
        "reflect": {
            "timestamp": "2026-01-01T00:00:00Z",
            "confirmed_at": "2026-01-01T00:00:00Z",
            "report": f'## Coverage Ledger\n- {issue["id"]} -> cluster "current"\n## Strategy\nGive the current command owner a concrete action, and preserve historical completed work.',
            "disposition_ledger": [
                {"issue_id": issue["id"], "decision": "cluster", "target": "current"}
            ],
        },
    }
    plan["clusters"] = {
        "current": {
            "issue_ids": [issue["id"]],
            "description": "Admit public CLI contracts.",
            "action_steps": ["Annotate src/commands.py and verify command behavior."],
        },
        **{
            f"history-{i}": {"issue_ids": [f"review::src/retired{i}.py::resolved"]}
            for i in range(4)
        },
        "auto/current": {"auto": True, "issue_ids": [issue["id"]]},
    }
    # Public synthetic log fixture: no native state or commands are executed.
    plan["execution_log"] = [
        {
            "timestamp": "2026-01-01T00:01:00Z",
            "action": "cluster_update",
            "cluster_name": "current",
        }
        for _ in range(operation_count)
    ]
    collect_triage_input(
        plan, state
    )  # Admit the fixture through real plan normalization.
    saved = []
    services = SimpleNamespace(
        command_runtime=lambda _args: SimpleNamespace(state=state),
        load_plan=lambda: plan,
        save_plan=lambda value: saved.append(copy.deepcopy(value)),
        collect_triage_input=collect_triage_input,
        detect_recurring_patterns=detect_recurring_patterns,
        append_log_entry=lambda _plan, action, **kwargs: saved.append(
            {"action": action, **kwargs}
        ),
    )
    return plan, state, issue, services, saved


def _submit(plan, state, services, attestation=None):
    return organize._validate_organize_submission(
        args=argparse.Namespace(),
        plan=plan,
        state=state,
        stages=plan["epic_triage_meta"]["triage_stages"],
        report="Cluster current has first priority: admit its command boundary, verify behavior and retain all unrelated completed history. The next action is ready for execution.",
        attestation=attestation,
        is_reuse=False,
        services=services,
    )


def test_organize_uses_current_review_clusters_without_requiring_history_mutations(
    capsys,
):
    plan, state, issue, services, _saved = _fixture()
    history = {
        name: copy.deepcopy(cluster)
        for name, cluster in plan["clusters"].items()
        if name.startswith("history-")
    }
    result = _submit(plan, state, services)
    assert result is not None
    assert result[0] == ["current"]
    assert _manual_clusters_or_error(plan, open_review_ids={issue["id"]}) == ["current"]
    assert manual_clusters_with_issues(plan) == ["current", *history]
    assert _manual_clusters_or_error(plan) == ["current", *history]
    assert {name: plan["clusters"][name] for name in history} == history
    assert "Cannot organize" not in capsys.readouterr().out


def test_recorded_organize_counts_current_clusters_and_preserves_historical_records():
    plan, _state, _issue, services, saved = _fixture()
    organize.cmd_stage_organize(
        argparse.Namespace(
            report="Cluster current has first priority because its concrete source action and tests unblock the current work. Preserve completed historical clusters and their membership.",
            attestation=None,
        ),
        services=services,
    )
    assert "organize" in plan["epic_triage_meta"]["triage_stages"]
    log = next(entry for entry in saved if entry.get("action") == "triage_organize")
    assert log["detail"]["cluster_count"] == 1
    assert len(plan["clusters"]) == 6


def test_empty_current_review_scope_does_not_count_history():
    plan, _state, _issue, _services, _saved = _fixture()
    assert _manual_clusters_or_error(plan, open_review_ids=set()) == []
    assert len(manual_clusters_with_issues(plan)) == 5


@pytest.mark.parametrize("operation_count", [0, 1, 2])
def test_current_cluster_still_requires_minimum_three_operations(
    operation_count, capsys
):
    plan, state, _issue, services, _saved = _fixture(operation_count)
    assert _submit(plan, state, services) is None
    assert "need 3+" in capsys.readouterr().out


def test_existing_activity_attestation_retains_its_minimum_and_override(capsys):
    plan, state, _issue, services, _saved = _fixture(1)
    assert _submit(plan, state, services, "short reason") is None
    assert (
        _submit(
            plan,
            state,
            services,
            "Only the current cluster needs work; completed history remains preserved without dummy operations.",
        )
        is not None
    )
    assert "Proceeding with attestation override" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["description", "action_steps"])
def test_current_cluster_enrichment_remains_required(missing, capsys):
    plan, state, _issue, services, _saved = _fixture()
    del plan["clusters"]["current"][missing]
    assert _submit(plan, state, services) is None
    assert "need enrichment" in capsys.readouterr().out


def test_unclustered_current_review_still_blocks_organize(capsys):
    plan, state, issue, services, _saved = _fixture()
    plan["clusters"]["current"]["issue_ids"] = []
    assert _manual_clusters_or_error(plan, open_review_ids={issue["id"]}) is None
    assert _submit(plan, state, services) is None
    assert organize._unclustered_review_issues_or_error(plan, state) is False
    assert "have no cluster" in capsys.readouterr().out


def test_reflect_ledger_mismatch_still_blocks_organize(capsys):
    plan, state, _issue, services, _saved = _fixture()
    plan["epic_triage_meta"]["triage_stages"]["reflect"]["disposition_ledger"][0][
        "target"
    ] = "other-current"
    assert _submit(plan, state, services) is None
    assert "diverge from the reflect plan" in capsys.readouterr().out


@pytest.mark.parametrize("operation_count", [3, 4])
def test_activity_floor_grows_with_all_current_clusters(operation_count, capsys):
    plan, state, issue, services, _saved = _fixture(operation_count)
    for index in range(1, 4):
        current = _review(f"holistic::type_safety::entrypoint_contract_{index}")
        name = f"current-{index}"
        state["work_items"][current["id"]] = current
        plan["queue_order"].append(current["id"])
        plan["epic_triage_meta"]["active_triage_issue_ids"].append(current["id"])
        plan["clusters"][name] = {
            "issue_ids": [current["id"]],
            "description": "Admit this current command boundary.",
            "action_steps": [
                "Annotate the command and check its observed exit status."
            ],
        }
        plan["epic_triage_meta"]["triage_stages"]["reflect"][
            "disposition_ledger"
        ].append({"issue_id": current["id"], "decision": "cluster", "target": name})
        reflect = plan["epic_triage_meta"]["triage_stages"]["reflect"]
        reflect["report"] = reflect["report"].replace(
            "## Strategy", f'- {current["id"]} -> cluster "{name}"\n## Strategy'
        )
    result = organize._validate_organize_submission(
        args=argparse.Namespace(),
        plan=plan,
        state=state,
        stages=plan["epic_triage_meta"]["triage_stages"],
        report="Clusters current, current-1, current-2 and current-3 each have concrete source actions and command checks. Execute them in that order while preserving completed history.",
        attestation=None,
        is_reuse=False,
        services=services,
    )
    if operation_count == 3:
        assert result is None
        assert "need 4+" in capsys.readouterr().out
    else:
        assert result is not None
        assert set(result[0]) == {"current", "current-1", "current-2", "current-3"}
    assert _manual_clusters_or_error(plan, open_review_ids={issue["id"]}) == ["current"]
