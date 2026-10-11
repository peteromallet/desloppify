"""Direct tests for external review session start/submit helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from desloppify.app.commands.review import external as external_mod
from desloppify.app.commands.review import runtime_paths as runtime_paths_mod
from desloppify.app.commands.review.prompt_sections import (
    render_scan_evidence_note,
    render_scope_enums,
    render_scoring_frame,
)
from desloppify.base.exception_sets import CommandError
from desloppify.state import empty_state as build_empty_state


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def test_external_start_creates_session_and_template(tmp_path, monkeypatch):
    packet = {"dimensions": ["naming_quality", "logic_clarity"]}
    packet_path = tmp_path / "packets" / "packet.json"
    blind_path = tmp_path / "packets" / "review_packet_blind.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps({"ok": True}))
    blind_payload = {"command": "review", "dimensions": ["naming_quality"]}
    blind_path.write_text(json.dumps(blind_payload))

    monkeypatch.setattr(
        external_mod,
        "_prepare_packet_snapshot",
        lambda *_args, **_kwargs: (packet, packet_path, blind_path),
    )
    monkeypatch.setattr(runtime_paths_mod, "EXTERNAL_SESSION_ROOT", tmp_path / "sessions")

    args = SimpleNamespace(
        external_runner="claude",
        session_ttl_hours=6,
        path=".",
        dimensions=None,
    )
    lang = MagicMock()
    lang.name = "python"

    external_mod.do_external_start(args, build_empty_state(), lang, config={})

    session_files = list((tmp_path / "sessions").glob("*/session.json"))
    assert len(session_files) == 1
    session = json.loads(session_files[0].read_text())
    assert session["runner"] == "claude"
    assert session["status"] == "open"
    assert session["packet_sha256"] == hashlib.sha256(blind_path.read_bytes()).hexdigest()
    template = Path(session["template_path"])
    assert template.exists()
    template_payload = json.loads(template.read_text())
    assert "session" in template_payload
    assert template_payload["session"]["id"] == session["session_id"]
    assert template_payload["session"]["token"] == session["token"]
    assert sorted(template_payload["assessments"]) == ["logic_clarity", "naming_quality"]
    launch_prompt = Path(session["launch_prompt_path"])
    assert launch_prompt.exists()
    prompt_text = launch_prompt.read_text()
    assert f"session.id` exactly `{session['session_id']}`" in prompt_text
    assert f"session.token` exactly `{session['token']}`" in prompt_text
    assert "## Execution Constraints" in prompt_text
    assert "Do not extract code into new files or functions" in prompt_text
    assert "Net line count must decrease or stay flat" in prompt_text


def test_external_submit_rejects_missing_session_metadata(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions" / "ext_x"
    session_dir.mkdir(parents=True, exist_ok=True)
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps({"command": "review"}))
    session_payload = {
        "session_id": "ext_x",
        "status": "open",
        "runner": "claude",
        "created_at": _iso(datetime.now(UTC)),
        "expires_at": _iso(datetime.now(UTC) + timedelta(hours=2)),
        "token": "secret-token",
        "attest": external_mod.EXTERNAL_ATTEST_TEXT,
        "blind_packet_path": str(blind),
        "packet_sha256": hashlib.sha256(blind.read_bytes()).hexdigest(),
    }
    session_path = session_dir / "session.json"
    session_path.write_text(json.dumps(session_payload))
    issues = tmp_path / "issues.json"
    issues.write_text(json.dumps({"assessments": {"naming_quality": 100}, "issues": []}))

    monkeypatch.setattr(runtime_paths_mod, "EXTERNAL_SESSION_ROOT", tmp_path / "sessions")
    lang = MagicMock()
    lang.name = "python"

    with pytest.raises(CommandError) as exc_info:
        external_mod.do_external_submit(
            import_file=str(issues),
            session_id="ext_x",
            state=build_empty_state(),
            lang=lang,
            state_file=tmp_path / "state.json",
            config={},
        )
    assert exc_info.value.exit_code == 1


@pytest.mark.parametrize("scan_after_import", [False, True])
def test_external_submit_canonicalizes_and_imports(tmp_path, monkeypatch, scan_after_import):
    session_dir = tmp_path / "sessions" / "ext_x"
    session_dir.mkdir(parents=True, exist_ok=True)
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps({"command": "review"}))
    session_payload = {
        "session_id": "ext_x",
        "status": "open",
        "runner": "claude",
        "created_at": _iso(datetime.now(UTC)),
        "expires_at": _iso(datetime.now(UTC) + timedelta(hours=2)),
        "token": "secret-token",
        "attest": external_mod.EXTERNAL_ATTEST_TEXT,
        "blind_packet_path": str(blind),
        "packet_sha256": hashlib.sha256(blind.read_bytes()).hexdigest(),
    }
    session_path = session_dir / "session.json"
    session_path.write_text(json.dumps(session_payload))
    issues = tmp_path / "issues.json"
    issues.write_text(
        json.dumps(
            {
                "session": {"id": "ext_x", "token": "secret-token"},
                "provenance": {"kind": "fake"},
                "assessments": {"naming_quality": 100},
                "issues": [],
            }
        )
    )

    captured: dict[str, object] = {}

    def _capture_import(import_path, *_args, **kwargs):
        captured["import_path"] = import_path
        captured["kwargs"] = kwargs

    monkeypatch.setattr(runtime_paths_mod, "EXTERNAL_SESSION_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(external_mod, "do_import", _capture_import)
    followup = MagicMock(return_value=0)
    monkeypatch.setattr(external_mod, "run_followup_scan", followup)

    lang = MagicMock()
    lang.name = "python"
    state = build_empty_state()
    external_mod.do_external_submit(
        import_file=str(issues),
        session_id="ext_x",
        state=state,
        lang=lang,
        state_file=tmp_path / ".desloppify/custom/state.json",
        config={},
        scan_after_import=scan_after_import,
    )

    assert "import_path" in captured
    payload = json.loads(Path(str(captured["import_path"])).read_text())
    assert "session" not in payload
    assert payload["provenance"]["runner"] == "claude"
    assert payload["provenance"]["packet_sha256"] == session_payload["packet_sha256"]
    kwargs = captured["kwargs"]
    ic = kwargs["import_config"]
    assert ic.attested_external is True
    assert ic.manual_attest == external_mod.EXTERNAL_ATTEST_TEXT

    persisted = json.loads(session_path.read_text())
    assert persisted["status"] == "submitted"
    assert "submitted_at" in persisted
    if scan_after_import:
        assert followup.call_args.kwargs["state_file"] == tmp_path / ".desloppify/custom/state.json"
    else:
        followup.assert_not_called()


def test_external_submit_dry_run_uses_validate_import(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions" / "ext_x"
    session_dir.mkdir(parents=True, exist_ok=True)
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps({"command": "review"}))
    session_payload = {
        "session_id": "ext_x",
        "status": "open",
        "runner": "claude",
        "created_at": _iso(datetime.now(UTC)),
        "expires_at": _iso(datetime.now(UTC) + timedelta(hours=2)),
        "token": "secret-token",
        "attest": external_mod.EXTERNAL_ATTEST_TEXT,
        "blind_packet_path": str(blind),
        "packet_sha256": hashlib.sha256(blind.read_bytes()).hexdigest(),
    }
    (session_dir / "session.json").write_text(json.dumps(session_payload))
    issues = tmp_path / "issues.json"
    issues.write_text(
        json.dumps(
            {
                "session": {"id": "ext_x", "token": "secret-token"},
                "assessments": {"naming_quality": 100},
                "issues": [],
            }
        )
    )

    calls: dict[str, int] = {"validate": 0, "import": 0}

    def _capture_validate(*_args, **_kwargs):
        calls["validate"] += 1

    def _capture_import(*_args, **_kwargs):
        calls["import"] += 1

    monkeypatch.setattr(runtime_paths_mod, "EXTERNAL_SESSION_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(external_mod, "do_validate_import", _capture_validate)
    monkeypatch.setattr(external_mod, "do_import", _capture_import)

    lang = MagicMock()
    lang.name = "python"
    external_mod.do_external_submit(
        import_file=str(issues),
        session_id="ext_x",
        state=build_empty_state(),
        lang=lang,
        state_file=tmp_path / "state.json",
        config={},
        dry_run=True,
    )

    assert calls["validate"] == 1
    assert calls["import"] == 0


def test_template_payload_includes_dimension_notes():
    packet = {"dimensions": ["naming_quality", "logic_clarity"]}
    payload = external_mod._build_template_payload(
        packet, session_id="s1", token="t1"
    )
    assert "dimension_notes" in payload
    assert payload["dimension_notes"] == {}
    assert payload["dimension_judgment"] == {}
    assert payload["context_updates"] == {}


def test_external_launch_prompt_contains_shared_sections():
    packet = {
        "dimensions": ["naming_quality"],
        "investigation_batches": [
            {
                "name": "B1",
                "dimensions": ["naming_quality"],
                "why": "test",
                "dimension_contexts": {
                    "naming_quality": {
                        "insights": [
                            {
                                "header": "Naming follows CLI verbs",
                                "description": "Commands align to user intent.",
                                "settled": True,
                            }
                        ]
                    }
                },
            }
        ],
    }
    prompt = external_mod._build_claude_launch_prompt(
        session_id="s1",
        token="t1",
        blind_path=Path("/tmp/blind.json"),
        template_path=Path("/tmp/template.json"),
        output_path=Path("/tmp/output.json"),
        packet=packet,
    )
    assert render_scoring_frame() in prompt
    assert render_scan_evidence_note() in prompt
    assert render_scope_enums() in prompt
    assert "--- Batch 1: B1 ---" in prompt
    assert "Codebase Characteristics" in prompt
    assert "dimension_judgment" in prompt
    assert "context_updates" in prompt


def test_external_launch_prompt_with_historical_and_concern_signals():
    packet = {
        "dimensions": ["naming_quality"],
        "investigation_batches": [
            {
                "name": "B1",
                "dimensions": ["naming_quality"],
                "why": "test",
                "files_to_read": [],
                "historical_issue_focus": {
                    "selected_count": 1,
                    "issues": [{"status": "open", "summary": "bad names"}],
                },
                "concern_signals": [
                    {
                        "file": "x.py",
                        "type": "naming",
                        "summary": "inconsistent",
                        "question": "why?",
                        "evidence": ["line 1"],
                    }
                ],
            }
        ],
    }
    prompt = external_mod._build_claude_launch_prompt(
        session_id="s1",
        token="t1",
        blind_path=Path("/tmp/blind.json"),
        template_path=Path("/tmp/template.json"),
        output_path=Path("/tmp/output.json"),
        packet=packet,
    )
    assert "bad names" in prompt
    assert "inconsistent" in prompt


def test_external_start_template_has_dimension_notes(tmp_path, monkeypatch):
    packet = {"dimensions": ["naming_quality", "logic_clarity"]}
    packet_path = tmp_path / "packets" / "packet.json"
    blind_path = tmp_path / "packets" / "review_packet_blind.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps({"ok": True}))
    blind_payload = {"command": "review", "dimensions": ["naming_quality"]}
    blind_path.write_text(json.dumps(blind_payload))

    monkeypatch.setattr(
        external_mod,
        "_prepare_packet_snapshot",
        lambda *_args, **_kwargs: (packet, packet_path, blind_path),
    )
    monkeypatch.setattr(runtime_paths_mod, "EXTERNAL_SESSION_ROOT", tmp_path / "sessions")

    args = SimpleNamespace(
        external_runner="claude",
        session_ttl_hours=6,
        path=".",
        dimensions=None,
    )
    lang = MagicMock()
    lang.name = "python"

    external_mod.do_external_start(args, build_empty_state(), lang, config={})

    template_files = list((tmp_path / "sessions").glob("*/review_result.template.json"))
    assert len(template_files) == 1
    template = json.loads(template_files[0].read_text())
    assert "dimension_notes" in template
    assert template["dimension_notes"] == {}
