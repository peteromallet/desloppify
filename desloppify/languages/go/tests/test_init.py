"""Scaffold sanity tests for the generated language plugin."""

from __future__ import annotations

from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.hook_registry import get_lang_hook
from desloppify.languages.go import GoConfig


def test_config_name():
    cfg = GoConfig()
    assert cfg.name == 'go'


def test_config_extensions_non_empty():
    cfg = GoConfig()
    assert '.go' in cfg.extensions


def test_detect_commands_non_empty():
    cfg = GoConfig()
    assert cfg.detect_commands


def test_test_coverage_hooks_registered():
    assert get_lang_hook("go", "test_coverage") is not None


def test_go_test_files_classified_as_test_zone():
    cfg = GoConfig()
    zone_map = FileZoneMap(
        ["pkg/foo.go", "pkg/foo_test.go"],
        cfg.zone_rules,
        rel_fn=lambda path: path,
    )
    assert zone_map.get("pkg/foo.go") == Zone.PRODUCTION
    assert zone_map.get("pkg/foo_test.go") == Zone.TEST
