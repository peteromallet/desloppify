"""Tests for detector hook registry behavior."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import desloppify.hook_registry as registry_mod
from desloppify.hook_registry import clear_lang_hooks_for_tests, get_lang_hook


def test_get_lang_hook_lazy_loads_language_hooks() -> None:
    clear_lang_hooks_for_tests()

    hook = get_lang_hook("python", "test_coverage")

    assert hook is not None
    assert hasattr(hook, "has_testable_logic")


def test_get_lang_hook_reloads_after_test_clear() -> None:
    # Ensure module is imported at least once.
    importlib.import_module("desloppify.languages.python")

    clear_lang_hooks_for_tests()
    hook = get_lang_hook("python", "test_coverage")

    assert hook is not None
    assert hasattr(hook, "parse_test_import_specs")


def test_get_lang_hook_retries_after_import_failure(monkeypatch) -> None:
    clear_lang_hooks_for_tests()

    sentinel = object()
    attempts = {"count": 0}
    real_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == "desloppify.languages.retrylang":
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ImportError("transient")
            registry_mod.register_lang_hooks("retrylang", test_coverage=sentinel)
            return SimpleNamespace()
        if package is None:
            return real_import_module(name)
        return real_import_module(name, package)

    monkeypatch.setattr(registry_mod.importlib, "import_module", _fake_import_module)

    assert get_lang_hook("retrylang", "test_coverage") is None
    assert get_lang_hook("retrylang", "test_coverage") is sentinel
