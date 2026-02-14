"""Tests for desloppify.lang — register_lang, get_lang, available_langs, auto_detect_lang."""

from pathlib import Path
from unittest.mock import patch

import pytest

import desloppify.lang as lang_mod
from desloppify.lang import _registry, auto_detect_lang, available_langs, get_lang, register_lang
from desloppify.lang.base import LangConfig


# ── register_lang ────────────────────────────────────────────


def test_register_lang_adds_to_registry():
    """register_lang decorator registers a class under the given name."""
    # Use a unique name so we don't collide with real registrations
    test_name = "_test_register_dummy"
    try:
        # Patch validation since the test module isn't a real lang plugin dir
        with patch.object(lang_mod, "_validate_lang_structure"):
            @register_lang(test_name)
            class DummyConfig:
                pass

        assert test_name in _registry
        assert _registry[test_name] is DummyConfig
    finally:
        _registry.pop(test_name, None)


def test_register_lang_returns_class_unchanged():
    """Decorator returns the original class unmodified."""
    test_name = "_test_register_identity"
    try:
        class OriginalClass:
            pass

        # The decorator validates module structure, which will fail for a
        # plain class not inside a lang package directory. Patch validation.
        with patch.object(lang_mod, "_validate_lang_structure"):
            result = register_lang(test_name)(OriginalClass)
        assert result is OriginalClass
    finally:
        _registry.pop(test_name, None)


# ── get_lang ─────────────────────────────────────────────────


def test_get_lang_python():
    """get_lang('python') returns a LangConfig for Python."""
    cfg = get_lang("python")
    assert isinstance(cfg, LangConfig)
    assert cfg.name == "python"
    assert ".py" in cfg.extensions


def test_get_lang_typescript():
    """get_lang('typescript') returns a LangConfig for TypeScript."""
    cfg = get_lang("typescript")
    assert isinstance(cfg, LangConfig)
    assert cfg.name == "typescript"
    assert any(ext in cfg.extensions for ext in [".ts", ".tsx"])


def test_get_lang_unknown_raises():
    """get_lang with unknown name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown language"):
        get_lang("_nonexistent_language_xyz")


def test_get_lang_returns_fresh_instances():
    """Each call to get_lang returns a new instance."""
    cfg1 = get_lang("python")
    cfg2 = get_lang("python")
    assert cfg1 is not cfg2


# ── available_langs ──────────────────────────────────────────


def test_available_langs_includes_python_and_typescript():
    """available_langs includes python, typescript, and csharp."""
    langs = available_langs()
    assert "python" in langs
    assert "typescript" in langs
    assert "csharp" in langs


def test_available_langs_returns_sorted():
    """available_langs returns a sorted list."""
    langs = available_langs()
    assert langs == sorted(langs)


# ── auto_detect_lang ─────────────────────────────────────────


def test_auto_detect_python_project(tmp_path):
    """Project with pyproject.toml auto-detects as python."""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
    # Create at least one .py file so the file count is > 0
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')")

    # Patch PROJECT_ROOT to tmp_path for file_finder
    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        result = auto_detect_lang(tmp_path)
    assert result == "python"


def test_auto_detect_typescript_project(tmp_path):
    """Project with package.json auto-detects as typescript."""
    (tmp_path / "package.json").write_text('{"name": "test"}')
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.ts").write_text("export const x = 1;")

    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        result = auto_detect_lang(tmp_path)
    assert result == "typescript"


def test_auto_detect_no_config_returns_none(tmp_path):
    """Project with no recognized config files returns None."""
    result = auto_detect_lang(tmp_path)
    assert result is None


def test_auto_detect_csharp_project(tmp_path):
    """Project with .sln and .cs files auto-detects as csharp."""
    (tmp_path / "Example.sln").write_text("Microsoft Visual Studio Solution File")
    src = tmp_path / "src"
    src.mkdir()
    (src / "Program.cs").write_text("namespace App; class Program {}")

    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        result = auto_detect_lang(tmp_path)
    assert result == "csharp"


# ── LangConfig basics ───────────────────────────────────────


def test_python_config_has_phases():
    """Python config has at least one detector phase."""
    cfg = get_lang("python")
    assert len(cfg.phases) > 0


def test_typescript_config_has_phases():
    """TypeScript config has at least one detector phase."""
    cfg = get_lang("typescript")
    assert len(cfg.phases) > 0


def test_python_config_has_extract_functions():
    """Python config has an extract_functions callable."""
    cfg = get_lang("python")
    assert cfg.extract_functions is not None
    assert callable(cfg.extract_functions)


def test_python_config_has_file_finder():
    """Python config has a file_finder callable."""
    cfg = get_lang("python")
    assert cfg.file_finder is not None
    assert callable(cfg.file_finder)


def test_typescript_config_has_file_finder():
    """TypeScript config has a file_finder callable."""
    cfg = get_lang("typescript")
    assert cfg.file_finder is not None
    assert callable(cfg.file_finder)
