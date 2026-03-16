"""Tests for lifecycle transition messages."""

from __future__ import annotations

import pytest

from desloppify.app.commands.helpers import transition_messages as mod


@pytest.fixture()
def _config_with_messages(monkeypatch):
    """Patch load_config to return transition messages."""
    def _make(messages: dict):
        monkeypatch.setattr(mod, "load_config", lambda: {"transition_messages": messages})
    return _make


def test_emit_exact_phase_match(_config_with_messages, capsys):
    _config_with_messages({"execute": "Switch to Sonnet for speed."})
    assert mod.emit_transition_message("execute") is True
    assert "Switch to Sonnet for speed." in capsys.readouterr().out


def test_emit_coarse_fallback(_config_with_messages, capsys):
    _config_with_messages({"review": "Use blind packet."})
    assert mod.emit_transition_message("review_initial") is True
    assert "Use blind packet." in capsys.readouterr().out


def test_exact_phase_takes_priority_over_coarse(_config_with_messages, capsys):
    _config_with_messages({
        "review_initial": "Exact message.",
        "review": "Coarse message.",
    })
    assert mod.emit_transition_message("review_initial") is True
    out = capsys.readouterr().out
    assert "Exact message." in out
    assert "Coarse message." not in out


def test_no_message_configured(_config_with_messages, capsys):
    _config_with_messages({})
    assert mod.emit_transition_message("execute") is False
    assert capsys.readouterr().out == ""


def test_no_transition_messages_key(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_config", lambda: {})
    assert mod.emit_transition_message("execute") is False
    assert capsys.readouterr().out == ""


def test_empty_string_message_skipped(_config_with_messages, capsys):
    _config_with_messages({"execute": "  "})
    assert mod.emit_transition_message("execute") is False
    assert capsys.readouterr().out == ""


def test_non_string_message_skipped(_config_with_messages, capsys):
    _config_with_messages({"execute": 42})
    assert mod.emit_transition_message("execute") is False
    assert capsys.readouterr().out == ""


def test_postflight_fallback_for_review_phase(_config_with_messages, capsys):
    _config_with_messages({"postflight": "Summarise what you fixed."})
    assert mod.emit_transition_message("review_initial") is True
    assert "Summarise what you fixed." in capsys.readouterr().out


def test_postflight_fallback_for_triage_phase(_config_with_messages, capsys):
    _config_with_messages({"postflight": "Stop and review."})
    assert mod.emit_transition_message("triage_postflight") is True
    assert "Stop and review." in capsys.readouterr().out


def test_postflight_does_not_fire_for_execute(_config_with_messages, capsys):
    _config_with_messages({"postflight": "Should not appear."})
    assert mod.emit_transition_message("execute") is False
    assert capsys.readouterr().out == ""


def test_postflight_does_not_fire_for_scan(_config_with_messages, capsys):
    _config_with_messages({"postflight": "Should not appear."})
    assert mod.emit_transition_message("scan") is False
    assert capsys.readouterr().out == ""


def test_coarse_takes_priority_over_postflight(_config_with_messages, capsys):
    _config_with_messages({"review": "Specific.", "postflight": "Generic."})
    assert mod.emit_transition_message("review_initial") is True
    out = capsys.readouterr().out
    assert "Specific." in out
    assert "Generic." not in out


def test_config_load_failure_returns_false(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_config", lambda: (_ for _ in ()).throw(OSError("nope")))
    assert mod.emit_transition_message("execute") is False
    assert capsys.readouterr().out == ""
