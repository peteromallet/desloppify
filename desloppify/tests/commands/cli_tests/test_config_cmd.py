"""Direct tests for config command routing and dispatch."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.app.commands import config_cmd


def test_cmd_config_routes_set(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(config_cmd, "_config_set", lambda _args: calls.append("set"))
    monkeypatch.setattr(
        config_cmd, "_config_unset", lambda _args: calls.append("unset")
    )
    monkeypatch.setattr(config_cmd, "_config_show", lambda _args: calls.append("show"))

    config_cmd.cmd_config(SimpleNamespace(config_action="set"))
    assert calls == ["set"]
    assert len(calls) == 1
    assert "unset" not in calls
    assert "show" not in calls
    assert "unset" not in calls
    assert "show" not in calls
    assert len(calls) == 1


def test_cmd_config_routes_unset(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(config_cmd, "_config_set", lambda _args: calls.append("set"))
    monkeypatch.setattr(
        config_cmd, "_config_unset", lambda _args: calls.append("unset")
    )
    monkeypatch.setattr(config_cmd, "_config_show", lambda _args: calls.append("show"))

    config_cmd.cmd_config(SimpleNamespace(config_action="unset"))
    assert calls == ["unset"]
    assert len(calls) == 1
    assert "set" not in calls
    assert "show" not in calls
    assert "set" not in calls
    assert "show" not in calls
    assert len(calls) == 1


def test_cmd_config_routes_show_for_default(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(config_cmd, "_config_set", lambda _args: calls.append("set"))
    monkeypatch.setattr(
        config_cmd, "_config_unset", lambda _args: calls.append("unset")
    )
    monkeypatch.setattr(config_cmd, "_config_show", lambda _args: calls.append("show"))

    config_cmd.cmd_config(SimpleNamespace(config_action=None))
    assert calls == ["show"]
    assert len(calls) == 1
    assert "set" not in calls
    assert "unset" not in calls
    assert "set" not in calls
    assert "unset" not in calls
    assert len(calls) == 1
