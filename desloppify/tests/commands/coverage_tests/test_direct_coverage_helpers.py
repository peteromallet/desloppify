"""Direct, low-mock coverage tests for resolve/scan helper modules."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.app.commands.resolve.apply as resolve_apply_mod
import desloppify.app.commands.resolve.cmd as resolve_cmd_mod
import desloppify.app.commands.resolve.selection as resolve_selection_mod
import desloppify.app.commands.scan.scan_agent_env as agent_env_mod
import desloppify.app.commands.scan.scan_skill_sync as skill_sync_mod
import desloppify.state as state_mod


def _base_state() -> dict:
    state = state_mod.empty_state()
    state["findings"] = {
        "f1": {
            "id": "f1",
            "detector": "smells",
            "file": "desloppify/app/commands/resolve/cmd.py",
            "status": "open",
            "tier": 3,
            "confidence": "medium",
            "summary": "sample finding",
            "detail": {},
        },
        "f2": {
            "id": "f2",
            "detector": "smells",
            "file": "desloppify/app/commands/resolve/apply.py",
            "status": "open",
            "tier": 3,
            "confidence": "medium",
            "summary": "sample finding",
            "detail": {},
        },
    }
    return state


def test_agent_environment_detection_and_interface(monkeypatch) -> None:
    tracked_env = [
        "CLAUDE_CODE",
        "DESLOPPIFY_AGENT",
        "GEMINI_CLI",
        "CODEX_SANDBOX_NETWORK_DISABLED",
        "CODEX_SANDBOX",
        "CURSOR_TRACE_ID",
    ]
    for key in tracked_env:
        monkeypatch.delenv(key, raising=False)

    assert agent_env_mod.is_agent_environment() is False
    assert agent_env_mod.detect_agent_interface() is None

    monkeypatch.setenv("CODEX_SANDBOX", "1")
    assert agent_env_mod.is_agent_environment() is True
    assert agent_env_mod.detect_agent_interface() == "codex"

    monkeypatch.setenv("CLAUDE_CODE", "1")
    assert agent_env_mod.detect_agent_interface() == "claude"


def test_auto_update_skill_short_circuits_outside_agent(monkeypatch) -> None:
    called = {"value": False}

    monkeypatch.setattr(skill_sync_mod, "is_agent_environment", lambda: False)
    monkeypatch.setattr(
        skill_sync_mod,
        "_try_auto_update_skill",
        lambda: called.__setitem__("value", True),
    )

    skill_sync_mod.auto_update_skill()
    assert called["value"] is False


def test_resolve_helpers_resolve_patterns_and_attestation_rules() -> None:
    state = _base_state()
    args = SimpleNamespace(patterns=["f1"], status="fixed", note="done")

    resolved = resolve_apply_mod._resolve_all_patterns(
        state,
        args,
        attestation="I have actually fixed this and I am not gaming the score.",
    )
    assert resolved == ["f1"]
    assert state["findings"]["f1"]["status"] == "fixed"
    assert state["findings"]["f2"]["status"] == "open"

    assert (
        resolve_selection_mod.validate_attestation(
            "I have actually addressed this and I am not gaming the score."
        )
        is True
    )
    assert resolve_selection_mod.validate_attestation("done") is False
    assert resolve_selection_mod._missing_attestation_keywords("done") == [
        "i have actually",
        "not gaming",
    ]


def test_resolve_module_exports_are_callable() -> None:
    assert callable(resolve_cmd_mod.cmd_resolve)
    assert callable(resolve_cmd_mod.cmd_ignore_pattern)
