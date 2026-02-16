"""Tests for `desloppify explain` command handler."""

import json
from types import SimpleNamespace

from desloppify.commands.scan import cmd_explain


def _fake_state() -> dict:
    return {
        "findings": {
            "a": {
                "status": "wontfix",
                "detector": "structural",
                "file": "desloppify/review/prepare.py",
                "summary": "Needs decomposition: large",
            },
            "b": {
                "status": "open",
                "detector": "smells",
                "file": "desloppify/utils.py",
                "summary": "Broad except",
            },
            "c": {
                "status": "open",
                "detector": "smells",
                "file": "desloppify/utils.py",
                "summary": "Monster function",
            },
        },
        "dimension_scores": {
            "Type Safety": {"score": 82.0, "strict": 82.0, "checks": 10},
            "Error Consistency": {"score": 84.0, "strict": 84.0, "checks": 10},
            "File health": {"score": 99.0, "strict": 85.0, "checks": 143},
        },
    }


def test_cmd_explain_json(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    state = _fake_state() | {"overall_score": 95.3, "objective_score": 98.5, "strict_score": 93.8}
    state_path.write_text(json.dumps(state))

    args = SimpleNamespace(top=5, subjective_threshold=89.0, json=True, state=str(state_path), lang=None)
    cmd_explain(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict_gap"] == 1.5
    assert payload["wontfix_total"] == 1
    assert payload["top_wontfix_hotspots"][0]["detector"] == "structural"
    assert [row["dimension"] for row in payload["subjective_below_threshold"]] == [
        "Type Safety",
        "Error Consistency"
    ]


def test_cmd_explain_text_writes_query(tmp_path, monkeypatch, capsys):
    from desloppify.commands import scan as explain_mod

    state_path = tmp_path / "state.json"
    state = _fake_state() | {"overall_score": 95.3, "objective_score": 98.5, "strict_score": 93.8}
    state_path.write_text(json.dumps(state))
    written = []

    monkeypatch.setattr(explain_mod, "_write_query", lambda payload: written.append(payload))

    args = SimpleNamespace(top=3, subjective_threshold=89.0, json=False, state=str(state_path), lang=None)
    cmd_explain(args)
    out = capsys.readouterr().out
    assert "Score Attribution" in out
    assert "Subjective < 89" in out
    assert "Type Safety: 82.0" in out
    assert written and written[0]["command"] == "explain"
