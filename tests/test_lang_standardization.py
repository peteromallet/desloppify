"""Cross-language contract checks to keep plugin structure standardized."""

from __future__ import annotations

import importlib

from desloppify.lang import available_langs, get_lang


TOP_LEVEL_MODULES = (
    "commands",
    "extractors",
    "phases",
    "move",
    "review",
    "test_coverage",
)

REVIEW_CALLABLES = (
    "module_patterns",
    "api_surface",
)

REVIEW_CONSTANTS = (
    "REVIEW_GUIDANCE",
    "MIGRATION_PATTERN_PAIRS",
    "MIGRATION_MIXED_EXTENSIONS",
    "LOW_VALUE_PATTERN",
)

TEST_COVERAGE_CALLABLES = (
    "has_testable_logic",
    "resolve_import_spec",
    "resolve_barrel_reexports",
    "parse_test_import_specs",
    "map_test_to_source",
    "strip_test_markers",
    "strip_comments",
)

TEST_COVERAGE_CONSTANTS = (
    "ASSERT_PATTERNS",
    "MOCK_PATTERNS",
    "SNAPSHOT_PATTERNS",
    "TEST_FUNCTION_RE",
    "BARREL_BASENAMES",
)


def test_each_language_has_standard_top_level_modules():
    for lang in available_langs():
        for module_name in TOP_LEVEL_MODULES:
            mod = importlib.import_module(f"desloppify.lang.{lang}.{module_name}")
            assert mod is not None


def test_each_language_review_module_contract():
    for lang in available_langs():
        mod = importlib.import_module(f"desloppify.lang.{lang}.review")
        for const_name in REVIEW_CONSTANTS:
            assert hasattr(mod, const_name), f"{lang}.review missing {const_name}"
        for fn_name in REVIEW_CALLABLES:
            assert callable(getattr(mod, fn_name, None)), f"{lang}.review missing callable {fn_name}"


def test_each_language_test_coverage_module_contract():
    for lang in available_langs():
        mod = importlib.import_module(f"desloppify.lang.{lang}.test_coverage")
        for const_name in TEST_COVERAGE_CONSTANTS:
            assert hasattr(mod, const_name), f"{lang}.test_coverage missing {const_name}"
        for fn_name in TEST_COVERAGE_CALLABLES:
            assert callable(
                getattr(mod, fn_name, None)
            ), f"{lang}.test_coverage missing callable {fn_name}"


def test_detect_command_keys_use_canonical_snake_case():
    for lang in available_langs():
        cfg = get_lang(lang)
        assert cfg.detect_commands, f"{lang} has no detect commands"
        for key in cfg.detect_commands:
            assert key == key.lower(), f"{lang} detect command key must be lowercase: {key}"
            assert "-" not in key, f"{lang} detect command key must use underscore: {key}"


def test_detect_command_registry_owned_by_language_commands_module():
    for lang in available_langs():
        cfg = get_lang(lang)
        expected_module = f"desloppify.lang.{lang}.commands"
        for key, fn in cfg.detect_commands.items():
            assert fn.__module__ == expected_module, (
                f"{lang} detect command '{key}' must be defined in {expected_module}"
            )
