"""Focused tests for language discovery state handling."""

from __future__ import annotations

import importlib

import pytest

from desloppify.languages import discovery as discovery_mod
from desloppify.languages import registry_state
from desloppify.languages.framework.discovery import load_all, raise_load_errors


def test_raise_load_errors_includes_module_name_and_exception_type(monkeypatch):
    monkeypatch.setattr(registry_state, "_load_errors", {".dummy": ImportError("boom")})

    with pytest.raises(ImportError, match=r"\.dummy: ImportError: boom"):
        raise_load_errors()


def test_raise_load_errors_noop_when_no_errors(monkeypatch):
    monkeypatch.setattr(registry_state, "_load_errors", {})
    raise_load_errors()
    assert registry_state._load_errors == {}


def test_load_all_uses_plugin_file_naming_convention(monkeypatch, tmp_path):
    plugin_file = tmp_path / "plugin_rust.py"
    helper_file = tmp_path / "policy.py"
    plugin_file.write_text("# plugin placeholder\n")
    helper_file.write_text("# helper placeholder\n")

    imported: list[str] = []

    def fake_import_module(name, package=None):
        imported.append(name)
        return object()

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    monkeypatch.setattr(discovery_mod, "__file__", str(tmp_path / "discovery.py"))
    monkeypatch.setattr(registry_state, "_load_attempted", False)
    monkeypatch.setattr(registry_state, "_load_errors", {})

    load_all()
    assert ".plugin_rust" in imported
    assert ".policy" not in imported
    assert registry_state._load_attempted is True
    assert registry_state._load_errors == {}
    assert len(imported) == 1


def test_discovery_module_exports_expected_callables():
    assert callable(discovery_mod.load_all)
    assert callable(discovery_mod.raise_load_errors)
    assert isinstance(registry_state._load_errors, dict)
    assert isinstance(registry_state._load_attempted, bool)
