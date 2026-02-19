"""Focused unit tests for test_coverage.heuristics helpers."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.engine.detectors.test_coverage import heuristics as heuristics_mod


def test_load_lang_test_coverage_module_falls_back_to_object(monkeypatch):
    monkeypatch.setattr(heuristics_mod, "get_lang_hook", lambda *_args, **_kwargs: None)

    loaded = heuristics_mod._load_lang_test_coverage_module("python")

    assert loaded.__class__ is object


def test_has_testable_logic_uses_language_hook(tmp_path, monkeypatch):
    source = tmp_path / "module.ts"
    source.write_text("export function run() { return 1; }\n")

    def _hook(_filepath: str, content: str) -> bool:
        return "run" in content

    monkeypatch.setattr(
        heuristics_mod,
        "_load_lang_test_coverage_module",
        lambda _lang: SimpleNamespace(has_testable_logic=_hook),
    )

    assert heuristics_mod._has_testable_logic(str(source), "typescript") is True


def test_runtime_entrypoint_uses_hook_when_available(tmp_path, monkeypatch):
    source = tmp_path / "entry.ts"
    source.write_text("const app = {};\n")

    monkeypatch.setattr(
        heuristics_mod,
        "_load_lang_test_coverage_module",
        lambda _lang: SimpleNamespace(
            is_runtime_entrypoint=lambda _filepath, _content: True
        ),
    )

    assert heuristics_mod._is_runtime_entrypoint(str(source), "typescript") is True


def test_runtime_entrypoint_uses_typescript_fallback_for_supabase(tmp_path, monkeypatch):
    source = tmp_path / "supabase" / "functions" / "create-user" / "index.ts"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const handler = () => {};\n")

    monkeypatch.setattr(
        heuristics_mod,
        "_load_lang_test_coverage_module",
        lambda _lang: object(),
    )

    assert heuristics_mod._is_runtime_entrypoint(str(source), "typescript") is True


def test_runtime_entrypoint_hook_failure_falls_back_without_throwing(
    tmp_path, monkeypatch
):
    source = tmp_path / "src" / "module.ts"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("const value = 1;\n")

    monkeypatch.setattr(
        heuristics_mod,
        "_load_lang_test_coverage_module",
        lambda _lang: SimpleNamespace(
            is_runtime_entrypoint=lambda _filepath, _content: (_ for _ in ()).throw(
                TypeError("bad hook")
            )
        ),
    )

    assert heuristics_mod._is_runtime_entrypoint(str(source), "typescript") is False

