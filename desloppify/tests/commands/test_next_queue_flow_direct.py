"""Direct tests for next queue flow helpers."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

import desloppify.app.commands.next.queue_flow as queue_flow_mod
from desloppify.engine._plan.schema import empty_plan


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


@pytest.mark.parametrize("count", [1, 3])
def test_next_keeps_singleton_prerequisites_before_a_manual_cluster(count, capsys) -> None:
    written: list[dict] = []
    issues = [_issue(f"smells::src/a.py::{name}") for name in ["target", "billing", "n1", "n2"]]
    plan = empty_plan()
    plan["queue_order"] = [issue["id"] for issue in issues]
    plan["clusters"] = {
        "native-records": {
            "auto": False,
            "issue_ids": [issue["id"] for issue in issues[2:]],
            "depends_on_clusters": ["billing"],
        },
        "billing": {"auto": False, "issue_ids": [issues[1]["id"]]},
        "target": {"auto": False, "issue_ids": [issues[0]["id"]]},
    }

    queue_flow_mod.build_and_render_execution_queue(
        _args(count=count),
        state={
            "issues": {issue["id"]: issue for issue in issues},
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

    capsys.readouterr()
    expected = [issues[0]["id"], issues[1]["id"], "native-records"]
    assert [item["id"] for item in written[0]["items"]] == expected[:count]
    if count == 3:
        assert written[0]["items"][2]["member_count"] == 2


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
