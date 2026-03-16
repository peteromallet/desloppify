"""Tests for ``desloppify.languages.ruby`` configuration wiring.

These tests verify that the Ruby plugin is wired correctly — they do NOT run
RuboCop or any external tool.  They are pure in-process checks of the LangConfig
object that ``generic_lang`` produces.
"""

from __future__ import annotations

import pytest

from desloppify.languages import get_lang


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ruby_cfg():
    """Return the registered Ruby LangConfig (loaded once per test session)."""
    return get_lang("ruby")


# ---------------------------------------------------------------------------
# Basic identity
# ---------------------------------------------------------------------------

def test_config_name(ruby_cfg):
    assert ruby_cfg.name == "ruby"


def test_config_extensions(ruby_cfg):
    assert ruby_cfg.extensions == [".rb"]


def test_default_src_is_lib(ruby_cfg):
    """Ruby convention: library source lives in lib/, not the project root."""
    assert ruby_cfg.default_src == "lib"


# ---------------------------------------------------------------------------
# Project detection markers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("marker", [
    "Gemfile",       # Bundler manifest
    "Rakefile",      # Build/task file
    ".ruby-version", # rbenv/rvm version pin
    "*.gemspec",     # Gem specification (glob — supported by resolution.py)
])
def test_detect_markers_present(ruby_cfg, marker):
    assert marker in ruby_cfg.detect_markers, (
        f"Expected detect_marker {marker!r} to be registered"
    )


# ---------------------------------------------------------------------------
# Tool wiring
# ---------------------------------------------------------------------------

def test_rubocop_detect_command_registered(ruby_cfg):
    """rubocop_offense must be present so the RuboCop phase can run."""
    assert "rubocop_offense" in ruby_cfg.detect_commands


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "Structural analysis",
    "Coupling + cycles + orphaned",
    "rubocop",
])
def test_has_required_phases(ruby_cfg, label):
    labels = {p.label for p in ruby_cfg.phases}
    assert label in labels, f"Expected phase {label!r} to be present"


# ---------------------------------------------------------------------------
# File finder exclusions
# ---------------------------------------------------------------------------

_EXCLUDED_DIRS = [".bundle", "coverage", "tmp", "log", "vendor", "bin"]


def test_file_finder_skips_excluded_dirs(tmp_path, ruby_cfg):
    """Files inside excluded directories must not appear in scan results."""
    # Create one legitimate source file.
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "app.rb").write_text("class App; end\n")

    # Create an .rb file inside each excluded directory.
    for name in _EXCLUDED_DIRS:
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        (d / "noise.rb").write_text("# should be ignored\n")

    from desloppify.base.runtime_state import RuntimeContext, runtime_scope
    from desloppify.base.discovery.source import clear_source_file_cache_for_tests

    ctx = RuntimeContext(project_root=tmp_path)
    with runtime_scope(ctx):
        clear_source_file_cache_for_tests()
        files = ruby_cfg.file_finder(tmp_path)

    assert files == ["lib/app.rb"], (
        f"Expected only lib/app.rb but got: {files}"
    )


def test_external_test_dirs_includes_spec(ruby_cfg):
    """Ruby projects frequently use spec/ for RSpec tests."""
    assert "spec" in ruby_cfg.external_test_dirs
    assert "test" in ruby_cfg.external_test_dirs
