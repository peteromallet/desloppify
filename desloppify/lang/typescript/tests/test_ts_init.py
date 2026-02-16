"""Tests for desloppify.lang.typescript — TypeScriptConfig instantiation and fields."""

from desloppify.lang.typescript import TypeScriptConfig


# ── TypeScriptConfig basic fields ─────────────────────────────


def test_config_name():
    """TypeScriptConfig.name is 'typescript'."""
    cfg = TypeScriptConfig()
    assert cfg.name == "typescript"


def test_config_extensions():
    """TypeScriptConfig.extensions contains .ts and .tsx."""
    cfg = TypeScriptConfig()
    assert cfg.extensions == [".ts", ".tsx"]


def test_config_exclusions():
    """TypeScriptConfig.exclusions includes node_modules and .d.ts."""
    cfg = TypeScriptConfig()
    assert "node_modules" in cfg.exclusions
    assert ".d.ts" in cfg.exclusions


def test_config_default_src():
    """TypeScriptConfig.default_src is 'src'."""
    cfg = TypeScriptConfig()
    assert cfg.default_src == "src"


def test_config_phases_non_empty():
    """TypeScriptConfig.phases is a non-empty list."""
    cfg = TypeScriptConfig()
    assert len(cfg.phases) > 0


def test_config_phases_have_names():
    """Each phase has a non-empty label/name."""
    cfg = TypeScriptConfig()
    for phase in cfg.phases:
        assert phase.label, f"Phase missing label: {phase}"


def test_config_barrel_names():
    """TypeScriptConfig.barrel_names includes index.ts and index.tsx."""
    cfg = TypeScriptConfig()
    assert "index.ts" in cfg.barrel_names
    assert "index.tsx" in cfg.barrel_names


def test_config_fixers_dict():
    """TypeScriptConfig.fixers is a dict with at least 'unused-imports'."""
    cfg = TypeScriptConfig()
    assert isinstance(cfg.fixers, dict)
    assert "unused-imports" in cfg.fixers


def test_config_detect_commands_dict():
    """TypeScriptConfig.detect_commands is a dict with string keys."""
    cfg = TypeScriptConfig()
    assert isinstance(cfg.detect_commands, dict)
    assert len(cfg.detect_commands) > 0
    for key in cfg.detect_commands:
        assert isinstance(key, str)


def test_config_zone_rules():
    """TypeScriptConfig.zone_rules is a non-empty list."""
    cfg = TypeScriptConfig()
    assert len(cfg.zone_rules) > 0


def test_config_large_threshold():
    """TypeScriptConfig.large_threshold is 500."""
    cfg = TypeScriptConfig()
    assert cfg.large_threshold == 500


def test_config_extract_functions_callable():
    """TypeScriptConfig.extract_functions is a callable."""
    cfg = TypeScriptConfig()
    assert callable(cfg.extract_functions)


def test_config_build_dep_graph_callable():
    """TypeScriptConfig.build_dep_graph is a callable."""
    cfg = TypeScriptConfig()
    assert callable(cfg.build_dep_graph)
