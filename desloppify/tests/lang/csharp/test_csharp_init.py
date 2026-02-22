"""Tests for desloppify.languages.csharp — CSharpConfig and discovery behavior."""

import pytest

import desloppify.core._internal.text_utils as utils_text_mod
import desloppify.file_discovery as file_discovery_mod
import desloppify.utils as utils_mod
from desloppify.languages.csharp import CSharpConfig


@pytest.fixture
def patch_project_root(monkeypatch):
    """Patch PROJECT_ROOT across all modules that define/import it."""
    def _patch(tmp_path):
        monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(utils_text_mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(file_discovery_mod, "PROJECT_ROOT", tmp_path)
        file_discovery_mod._find_source_files_cached.cache_clear()
    return _patch


def test_config_name():
    """CSharpConfig.name is 'csharp'."""
    cfg = CSharpConfig()
    assert cfg.name == "csharp"


def test_config_extensions():
    """CSharpConfig.extensions contains .cs."""
    cfg = CSharpConfig()
    assert cfg.extensions == [".cs"]


def test_config_detect_commands_populated():
    """CSharpConfig.detect_commands has at least one command."""
    cfg = CSharpConfig()
    for name in ("deps", "cycles", "orphaned", "dupes", "large", "complexity"):
        assert name in cfg.detect_commands


def test_config_has_phases():
    """CSharpConfig has a non-empty scan pipeline."""
    cfg = CSharpConfig()
    assert len(cfg.phases) > 0
    assert any(p.label == "Structural analysis" for p in cfg.phases)


def test_config_entry_patterns_include_mobile_bootstrap_files():
    """C# config should treat MAUI/Xamarin bootstrap files as entrypoints."""
    cfg = CSharpConfig()
    assert "/MauiProgram.cs" in cfg.entry_patterns
    assert "/MainActivity.cs" in cfg.entry_patterns
    assert "/AppDelegate.cs" in cfg.entry_patterns
    assert "/SceneDelegate.cs" in cfg.entry_patterns
    assert "/WinUIApplication.cs" in cfg.entry_patterns


def test_file_finder_excludes_build_artifacts(tmp_path, patch_project_root):
    """C# file discovery skips bin/ and obj/ build output."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.cs").write_text("class App {}")
    (tmp_path / "obj").mkdir()
    (tmp_path / "obj" / "Generated.cs").write_text("class Generated {}")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "Compiled.cs").write_text("class Compiled {}")

    cfg = CSharpConfig()
    patch_project_root(tmp_path)
    files = cfg.file_finder(tmp_path)

    assert files == ["src/App.cs"]
