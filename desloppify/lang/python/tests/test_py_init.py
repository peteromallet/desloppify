"""Tests for desloppify.lang.python — PythonConfig and configuration data."""

import pytest

from desloppify.lang.python import (
    PythonConfig,
    PY_COMPLEXITY_SIGNALS,
    PY_GOD_RULES,
    PY_SKIP_NAMES,
    PY_ENTRY_PATTERNS,
    PY_ZONE_RULES,
)


class TestPythonConfig:
    def test_instantiation(self):
        config = PythonConfig()
        assert config is not None

    def test_name(self):
        config = PythonConfig()
        assert config.name == "python"

    def test_extensions(self):
        config = PythonConfig()
        assert config.extensions == [".py"]

    def test_exclusions_non_empty(self):
        config = PythonConfig()
        assert len(config.exclusions) > 0
        assert "__pycache__" in config.exclusions

    def test_phases_non_empty(self):
        config = PythonConfig()
        assert len(config.phases) > 0

    def test_phase_labels(self):
        config = PythonConfig()
        phase_labels = [p.label for p in config.phases]
        assert "Unused (ruff)" in phase_labels
        assert "Structural analysis" in phase_labels
        assert "Coupling + cycles + orphaned" in phase_labels
        assert "Code smells" in phase_labels

    def test_detect_commands_populated(self):
        config = PythonConfig()
        assert isinstance(config.detect_commands, dict)
        assert len(config.detect_commands) > 0

    def test_file_finder_callable(self):
        config = PythonConfig()
        assert callable(config.file_finder)

    def test_extract_functions_callable(self):
        config = PythonConfig()
        assert callable(config.extract_functions)

    def test_build_dep_graph_callable(self):
        config = PythonConfig()
        assert callable(config.build_dep_graph)

    def test_barrel_names(self):
        config = PythonConfig()
        assert "__init__.py" in config.barrel_names

    def test_large_threshold(self):
        config = PythonConfig()
        assert config.large_threshold == 300

    def test_complexity_threshold(self):
        config = PythonConfig()
        assert config.complexity_threshold == 25

    def test_zone_rules_set(self):
        config = PythonConfig()
        assert config.zone_rules is not None
        assert len(config.zone_rules) > 0


class TestComplexitySignals:
    def test_non_empty(self):
        assert len(PY_COMPLEXITY_SIGNALS) > 0

    def test_signal_names(self):
        names = {s.name for s in PY_COMPLEXITY_SIGNALS}
        assert "imports" in names
        assert "many_params" in names
        assert "deep_nesting" in names

    def test_all_have_weight(self):
        for s in PY_COMPLEXITY_SIGNALS:
            assert isinstance(s.weight, int)
            assert s.weight >= 1

    def test_compute_or_pattern(self):
        """Each signal has either a pattern or a compute function."""
        for s in PY_COMPLEXITY_SIGNALS:
            assert s.pattern is not None or s.compute is not None


class TestGodRules:
    def test_non_empty(self):
        assert len(PY_GOD_RULES) > 0

    def test_rule_names(self):
        names = {r.name for r in PY_GOD_RULES}
        assert "methods" in names
        assert "attributes" in names

    def test_all_have_threshold(self):
        for r in PY_GOD_RULES:
            assert isinstance(r.threshold, int)
            assert r.threshold > 0

    def test_extract_callable(self):
        for r in PY_GOD_RULES:
            assert callable(r.extract)


class TestSkipNames:
    def test_non_empty(self):
        assert len(PY_SKIP_NAMES) > 0

    def test_init_in_skip(self):
        assert "__init__.py" in PY_SKIP_NAMES

    def test_conftest_in_skip(self):
        assert "conftest.py" in PY_SKIP_NAMES


class TestEntryPatterns:
    def test_non_empty(self):
        assert len(PY_ENTRY_PATTERNS) > 0

    def test_main_pattern(self):
        assert "__main__.py" in PY_ENTRY_PATTERNS

    def test_test_patterns(self):
        assert any("test" in p for p in PY_ENTRY_PATTERNS)


class TestZoneRules:
    def test_non_empty(self):
        assert len(PY_ZONE_RULES) > 0

    def test_generated_zone_present(self):
        from desloppify.zones import Zone
        zones = {r.zone for r in PY_ZONE_RULES}
        assert Zone.GENERATED in zones

    def test_test_zone_present(self):
        from desloppify.zones import Zone
        zones = {r.zone for r in PY_ZONE_RULES}
        assert Zone.TEST in zones

    def test_test_prefix_pattern_present(self):
        from desloppify.zones import Zone
        test_rule = next((r for r in PY_ZONE_RULES if r.zone == Zone.TEST), None)
        assert test_rule is not None
        assert "test_" in test_rule.patterns
