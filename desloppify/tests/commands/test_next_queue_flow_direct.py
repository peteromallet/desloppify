"""Direct tests for next queue flow helpers."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

import desloppify.app.commands.next.queue_flow as queue_flow_mod
from desloppify.engine._plan.constants import WORKFLOW_RUN_SCAN_ID
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.models import QueueBuildOptions
from desloppify.engine.planning.queue_policy import build_execution_queue


def _args(**overrides):
    base = {
        "count": 1,
        "scope": None,
        "status": "open",
        "group": "item",
        "explain": False,
        "cluster": None,
        "include_skipped": False,
        "output": None,
        "format": "terminal",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _issue(
    issue_id: str,
    *,
    detector: str = "smells",
    file: str = "src/a.py",
    summary: str | None = None,
) -> dict:
    return {
        "id": issue_id,
        "detector": detector,
        "file": file,
        "tier": 3,
        "confidence": "medium",
        "summary": summary or issue_id,
        "status": "open",
        "detail": {},
    }


def test_build_next_payload_includes_scores_and_subjective_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        queue_flow_mod,
        "score_snapshot",
        lambda _state: SimpleNamespace(overall=91.0, objective=93.5, strict=90.2),
    )
    monkeypatch.setattr(
        queue_flow_mod,
        "scorecard_dimensions_payload",
        lambda *_a, **_k: [
            {"name": "Test health", "subjective": False},
            {"name": "Naming quality", "subjective": True},
        ],
    )
    monkeypatch.setattr(
        queue_flow_mod.next_output_mod,
        "build_query_payload",
        lambda *_a, **_k: {"command": "next"},
    )

    payload = queue_flow_mod._build_next_payload(
        queue={"items": []},
        items=[],
        state={},
        narrative={},
        plan_data=None,
    )

    assert payload["command"] == "next"
    assert payload["overall_score"] == 91.0
    assert payload["objective_score"] == 93.5
    assert payload["strict_score"] == 90.2
    assert len(payload["scorecard_dimensions"]) == 2
    assert payload["scorecard_dimensions"][0]["name"] == "Test health"
    assert payload["scorecard_dimensions"][1]["name"] == "Naming quality"
    assert payload["subjective_measures"] == [
        {"name": "Naming quality", "subjective": True}
    ]


def test_emit_requested_output_supports_json_and_markdown(capsys) -> None:
    payload = {"command": "next", "items": []}
    items = [
        {
            "id": "smells::a.py::x",
            "kind": "issue",
            "confidence": "medium",
            "summary": "Fix x",
            "primary_command": "desloppify plan resolve x",
        }
    ]

    json_opts = queue_flow_mod.NextOptions(output_file=None, output_format="json")
    assert queue_flow_mod._emit_requested_output(json_opts, payload, items) is True
    json_out = capsys.readouterr().out
    assert '"command": "next"' in json_out
    assert '"items": []' in json_out

    md_opts = queue_flow_mod.NextOptions(output_file=None, output_format="md")
    assert queue_flow_mod._emit_requested_output(md_opts, payload, items) is True
    md_out = capsys.readouterr().out
    assert "# Desloppify Execution Queue" in md_out
    assert "| issue | medium | Fix x | desloppify plan resolve x |" in md_out


def test_emit_requested_output_raises_when_output_file_write_fails(monkeypatch) -> None:
    opts = queue_flow_mod.NextOptions(output_file="out.json", output_format="terminal")
    monkeypatch.setattr(
        queue_flow_mod.next_output_mod,
        "write_output_file",
        lambda *_a, **_k: False,
    )

    with pytest.raises(queue_flow_mod.CommandError):
        queue_flow_mod._emit_requested_output(opts, payload={}, items=[])


def test_write_next_payload_adds_guardrail_warnings(monkeypatch) -> None:
    written: list[dict] = []
    monkeypatch.setattr(
        queue_flow_mod,
        "_build_next_payload",
        lambda **_k: {"command": "next", "items": []},
    )

    payload = queue_flow_mod._write_next_payload(
        queue={"items": []},
        items=[],
        state={},
        narrative={},
        plan_data=None,
        guardrail_warnings=["triage pending"],
        write_query_fn=lambda data: written.append(data),
        command_name="next",
    )

    assert payload["command"] == "next"
    assert payload["items"] == []
    assert payload["warnings"] == ["triage pending"]
    assert written == [payload]


def test_build_and_render_execution_queue_renders_real_issue_and_payload(capsys) -> None:
    written: list[dict] = []
    item = {
        "id": "smells::a.py::x",
        "detector": "smells",
        "file": "a.py",
        "summary": "Fix x",
        "primary_command": 'desloppify plan resolve "smells::a.py::x" --note "fixed" --confirm',
    }

    def _build_queue(_state, *, options):
        assert options.context is not None
        assert options.status == "open"
        assert options.include_subjective is True
        return {"items": [item], "total": 1}

    queue_flow_mod.build_and_render_execution_queue(
        _args(),
        state={
            "issues": {"x": {"status": "open"}},
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 0,
        },
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            resolve_lang_fn=lambda _args: SimpleNamespace(name="python"),
            load_plan_fn=lambda: {},
            build_work_queue_fn=_build_queue,
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert "Queue: 1 item" in out
    assert "Fix x" in out
    assert "Resolve with:" in out
    assert 'desloppify plan resolve "smells::a.py::x"' in out
    assert "Start planning: `desloppify plan`" in out
    assert written[0]["command"] == "next"
    assert written[0]["queue"]["mode"] == "execution"
    assert written[0]["items"][0]["summary"] == "Fix x"
    assert written[0]["items"][0]["file"] == "a.py"


def test_build_and_render_execution_queue_uses_real_execution_policy(capsys) -> None:
    written: list[dict] = []
    planned = _issue(
        "smells::src/a.py::planned",
        summary="Planned issue",
    )
    unplanned = _issue(
        "smells::src/b.py::unplanned",
        file="src/b.py",
        summary="Unplanned issue",
    )
    plan = empty_plan()
    plan["queue_order"] = [planned["id"]]

    queue_flow_mod.build_and_render_execution_queue(
        _args(),
        state={
            "issues": {
                planned["id"]: planned,
                unplanned["id"]: unplanned,
            },
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 0,
        },
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            resolve_lang_fn=lambda _args: SimpleNamespace(name="python"),
            load_plan_fn=lambda: plan,
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert "Planned issue" in out
    assert "Unplanned issue" not in out
    assert written[0]["items"][0]["id"] == planned["id"]
    assert written[0]["items"][0]["summary"] == "Planned issue"
    assert written[0]["plan"]["active"] is True
    assert written[0]["plan"]["total_ordered"] == 1


def test_build_and_render_backlog_queue_uses_real_backlog_policy(capsys) -> None:
    written: list[dict] = []
    planned = _issue(
        "smells::src/a.py::planned",
        summary="Planned issue",
    )
    unplanned = _issue(
        "smells::src/b.py::unplanned",
        file="src/b.py",
        summary="Unplanned issue",
    )
    plan = empty_plan()
    plan["queue_order"] = [planned["id"]]

    queue_flow_mod.build_and_render_backlog_queue(
        _args(),
        state={
            "issues": {
                planned["id"]: planned,
                unplanned["id"]: unplanned,
            },
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 0,
        },
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            resolve_lang_fn=lambda _args: SimpleNamespace(name="python"),
            load_plan_fn=lambda: plan,
            build_work_queue_fn=queue_flow_mod.build_backlog_queue,
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert "Unplanned issue" in out
    assert "Planned issue" not in out
    assert written[0]["items"][0]["id"] == unplanned["id"]


def test_build_and_render_backlog_queue_reports_empty_scope(capsys) -> None:
    planned = _issue(
        "smells::src/a.py::planned",
        summary="Planned issue",
    )
    unplanned = _issue(
        "smells::src/b.py::unplanned",
        file="src/b.py",
        summary="Unplanned issue",
    )
    plan = empty_plan()
    plan["queue_order"] = [planned["id"]]

    written: list[dict] = []
    queue_flow_mod.build_and_render_backlog_queue(
        _args(scope="missing"),
        state={
            "issues": {
                planned["id"]: planned,
                unplanned["id"]: unplanned,
            },
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 0,
        },
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            load_plan_fn=lambda: plan,
            build_work_queue_fn=queue_flow_mod.build_backlog_queue,
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert written[0]["items"] == []
    assert "No items match scope 'missing'." in out
    assert "Nothing to do!" not in out


def test_build_and_render_backlog_queue_hides_execution_prompt(capsys) -> None:
    written: list[dict] = []
    item = {
        "id": "smells::b.py::y",
        "detector": "smells",
        "file": "b.py",
        "summary": "Backlog item",
        "primary_command": 'desloppify plan resolve "smells::b.py::y" --note "fixed" --confirm',
    }

    queue_flow_mod.build_and_render_backlog_queue(
        _args(),
        state={
            "issues": {"y": {"status": "open"}},
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 0,
        },
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            resolve_lang_fn=lambda _args: SimpleNamespace(name="python"),
            load_plan_fn=lambda: {"queue_order": ["smells::planned"]},
            build_work_queue_fn=lambda _state, *, options: {
                "items": [item],
                "total": 1,
            },
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert "Backlog item" in out
    assert "Start working on the task above." not in out
    assert "Queue: 1 item" in out
    assert written[0]["command"] == "backlog"
    assert written[0]["queue"]["mode"] == "backlog"
    assert "plan" not in written[0]


def test_build_and_render_queue_respects_explicit_view_flags(capsys) -> None:
    written: list[dict] = []
    item = {
        "id": "smells::b.py::y",
        "detector": "smells",
        "file": "b.py",
        "summary": "Custom backlog item",
        "primary_command": 'desloppify plan resolve "smells::b.py::y" --note "fixed" --confirm',
    }

    queue_flow_mod.build_and_render_queue(
        _args(),
        state={
            "issues": {"y": {"status": "open"}},
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 0,
        },
        config={},
        view=queue_flow_mod.QueueViewConfig(
            command_name="custom-backlog",
            show_plan_context=False,
            collapse_plan_clusters=False,
            show_execution_prompt=False,
        ),
        deps=queue_flow_mod.QueueRenderDeps(
            resolve_lang_fn=lambda _args: SimpleNamespace(name="python"),
            load_plan_fn=lambda: {"queue_order": ["smells::planned"]},
            build_work_queue_fn=lambda _state, *, options: {
                "items": [item],
                "total": 1,
            },
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert "Custom backlog item" in out
    assert "Start working on the task above." not in out
    assert written[0]["command"] == "custom-backlog"
    assert "plan" not in written[0]


def test_scoped_view_filters_postflight_scan_but_global_queue_keeps_it(capsys) -> None:
    plan = empty_plan()
    plan["refresh_state"]["lifecycle_phase"] = "execute"
    state = {
        "issues": {},
        "work_items": {},
        "dimension_scores": {},
        "scan_path": ".",
        "scan_count": 5,
        "subjective_assessments": {},
        "assessment_import_audit": [],
    }

    global_queue = build_execution_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            plan=plan,
            include_subjective=True,
        ),
    )
    assert [item["id"] for item in global_queue["items"]] == [WORKFLOW_RUN_SCAN_ID]

    written: list[dict] = []
    queue_flow_mod.build_and_render_execution_queue(
        _args(scope="missing"),
        state=state,
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            load_plan_fn=lambda: plan,
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert written[0]["items"] == []
    assert "No items match scope 'missing'." in out
    assert "The full queue still has 1 item" in out
    assert "Queue cleared!" not in out


@pytest.mark.parametrize(
    ("case", "args_overrides", "issue_statuses", "cluster"),
    [
        ("scope", {"scope": "missing"}, ("open",), None),
        ("cluster", {}, ("fixed", "open"), "auth"),
        ("status", {"scope": "missing", "status": "fixed"}, ("open",), None),
        ("status_only", {"status": "fixed"}, ("open",), None),
    ],
    ids=["scope", "cluster", "status", "status_only"],
)
def test_empty_execution_view_respects_filter_context(
    case,
    args_overrides,
    issue_statuses,
    cluster,
    capsys,
) -> None:
    issues = [
        dict(
            _issue(
                f"smells::src/{chr(97 + index)}.py::issue",
                file=f"src/{chr(97 + index)}.py",
            ),
            status=status,
        )
        for index, status in enumerate(issue_statuses)
    ]
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 75.0}
    plan["queue_order"] = [issue["id"] for issue in issues]
    # Keep the real global queue at the completed post-flight boundary so the
    # scoped view reaches the empty renderer instead of adding a scan action.
    plan["refresh_state"]["postflight_scan_completed_at_scan_count"] = 5
    if cluster:
        plan["clusters"] = {cluster: {"issue_ids": [issues[0]["id"]]}}
        plan["active_cluster"] = cluster

    written: list[dict] = []
    queue_flow_mod.build_and_render_execution_queue(
        _args(**args_overrides),
        state={
            "issues": {issue["id"]: issue for issue in issues},
            "dimension_scores": {},
            "scan_path": ".",
            "potentials": {},
            "scan_count": 5,
        },
        config={},
        deps=queue_flow_mod.QueueRenderDeps(
            load_plan_fn=lambda: plan,
            write_query_fn=lambda payload: written.append(payload),
        ),
    )

    out = capsys.readouterr().out
    assert written[0]["items"] == []
    assert "Queue cleared!" not in out
    assert "Run `desloppify scan` now" not in out
    if case == "status":
        assert "No items match scope 'missing' with status 'fixed'." in out
        assert "full queue still has" not in out
    elif case == "status_only":
        assert "No items match status 'fixed'." in out
        assert "full queue still has" not in out
    else:
        filter_name = "scope 'missing'" if case == "scope" else "cluster 'auth'"
        assert f"No items match {filter_name}." in out
        assert "The full queue still has 1 item" in out
        if case == "cluster":
            assert "desloppify plan focus --clear" in out
