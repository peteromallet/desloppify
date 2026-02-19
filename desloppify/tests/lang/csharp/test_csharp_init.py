"""Tests for desloppify.languages.csharp — CSharpConfig and discovery behavior."""

from unittest.mock import patch

from desloppify.languages.csharp import CSharpConfig


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


def test_file_finder_excludes_build_artifacts(tmp_path):
    """C# file discovery skips bin/ and obj/ build output."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.cs").write_text("class App {}")
    (tmp_path / "obj").mkdir()
    (tmp_path / "obj" / "Generated.cs").write_text("class Generated {}")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "Compiled.cs").write_text("class Compiled {}")

    cfg = CSharpConfig()
    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        files = cfg.file_finder(tmp_path)

    assert files == ["src/App.cs"]
