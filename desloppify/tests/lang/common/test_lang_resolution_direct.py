"""Direct tests for language resolution helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import desloppify.languages.framework.registry_state as registry_state
import desloppify.languages.framework.resolution as lang_resolution_mod


def test_make_lang_config_wraps_constructor_errors():
    class _BadConfig:
        def __init__(self):
            raise RuntimeError("boom")

    with pytest.raises(
        ValueError, match="Failed to instantiate language config 'bad'"
    ) as exc:
        lang_resolution_mod.make_lang_config("bad", _BadConfig)
    msg = str(exc.value)
    assert "bad" in msg
    assert "boom" in msg


def test_get_lang_uses_registry_and_reports_unknown(monkeypatch):
    sentinel_cls = object()
    monkeypatch.setattr(registry_state, "_registry", {"python": sentinel_cls})
    monkeypatch.setattr(lang_resolution_mod, "load_all", lambda: None)
    monkeypatch.setattr(
        lang_resolution_mod, "make_lang_config", lambda name, cfg_cls: (name, cfg_cls)
    )

    resolved = lang_resolution_mod.get_lang("python")
    assert resolved == ("python", sentinel_cls)
    assert resolved[0] == "python"
    assert resolved[1] is sentinel_cls
    assert "python" in registry_state._registry

    with pytest.raises(ValueError, match="Unknown language") as exc:
        lang_resolution_mod.get_lang("missing")
    assert "Available: python" in str(exc.value)


def test_auto_detect_lang_prefers_marker_candidates_with_most_sources(
    monkeypatch, tmp_path
):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "package.json").write_text("{}\n")

    monkeypatch.setattr(
        registry_state,
        "_registry",
        {"python": object(), "typescript": object()},
    )
    monkeypatch.setattr(lang_resolution_mod, "load_all", lambda: None)

    cfg_by_name = {
        "python": SimpleNamespace(
            detect_markers=["pyproject.toml"],
            file_finder=lambda _root: ["a.py", "b.py", "c.py"],
        ),
        "typescript": SimpleNamespace(
            detect_markers=["package.json"],
            file_finder=lambda _root: ["a.ts"],
        ),
    }
    monkeypatch.setattr(
        lang_resolution_mod,
        "make_lang_config",
        lambda name, _cfg_cls: cfg_by_name[name],
    )

    detected = lang_resolution_mod.auto_detect_lang(tmp_path)
    assert detected == "python"
    assert "python" in cfg_by_name
    assert "typescript" in cfg_by_name
    assert (tmp_path / "pyproject.toml").exists()
    assert (tmp_path / "package.json").exists()


def test_auto_detect_lang_markerless_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(
        registry_state,
        "_registry",
        {"python": object(), "typescript": object()},
    )
    monkeypatch.setattr(lang_resolution_mod, "load_all", lambda: None)

    cfg_by_name = {
        "python": SimpleNamespace(
            detect_markers=[], file_finder=lambda _root: ["a.py"]
        ),
        "typescript": SimpleNamespace(
            detect_markers=[], file_finder=lambda _root: ["a.ts", "b.ts"]
        ),
    }
    monkeypatch.setattr(
        lang_resolution_mod,
        "make_lang_config",
        lambda name, _cfg_cls: cfg_by_name[name],
    )

    detected = lang_resolution_mod.auto_detect_lang(tmp_path)
    assert detected == "typescript"
    assert len(cfg_by_name["python"].file_finder(tmp_path)) == 1
    assert len(cfg_by_name["typescript"].file_finder(tmp_path)) == 2


def test_available_langs_returns_sorted_list(monkeypatch):
    monkeypatch.setattr(
        registry_state, "_registry", {"zeta": object(), "alpha": object()}
    )
    monkeypatch.setattr(lang_resolution_mod, "load_all", lambda: None)

    langs = lang_resolution_mod.available_langs()
    assert langs == ["alpha", "zeta"]
    assert langs[0] < langs[1]
