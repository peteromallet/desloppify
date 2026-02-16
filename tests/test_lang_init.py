"""Tests for desloppify.lang — register_lang, get_lang, available_langs, auto_detect_lang."""

from pathlib import Path
from unittest.mock import patch

import pytest

import desloppify.lang as lang_mod
from desloppify.lang import _registry, auto_detect_lang, available_langs, get_lang, register_lang
from desloppify.lang.base import DetectorPhase, LangConfig


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
    """available_langs includes at least python and typescript."""
    langs = available_langs()
    assert "python" in langs
    assert "typescript" in langs


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


# ── structural validation ────────────────────────────────────


def _write_lang_layout(
    root: Path,
    *,
    missing_files: set[str] | None = None,
    missing_dirs: set[str] | None = None,
    missing_dir_inits: set[str] | None = None,
    include_tests: bool = True,
):
    missing_files = missing_files or set()
    missing_dirs = missing_dirs or set()
    missing_dir_inits = missing_dir_inits or set()

    for filename in lang_mod.REQUIRED_FILES:
        if filename in missing_files:
            continue
        (root / filename).write_text("\n")

    for dirname in lang_mod.REQUIRED_DIRS:
        if dirname in missing_dirs:
            continue
        d = root / dirname
        d.mkdir(parents=True, exist_ok=True)
        if dirname not in missing_dir_inits:
            (d / "__init__.py").write_text("\n")
        if dirname == "tests" and include_tests:
            (d / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")


def test_validate_lang_structure_missing_file(tmp_path):
    lang_dir = tmp_path / "dummy_lang"
    lang_dir.mkdir()
    _write_lang_layout(lang_dir, missing_files={"commands.py"})

    with pytest.raises(ValueError, match="missing required file: commands.py"):
        lang_mod._validate_lang_structure(lang_dir, "dummy")


def test_validate_lang_structure_missing_dir(tmp_path):
    lang_dir = tmp_path / "dummy_lang"
    lang_dir.mkdir()
    _write_lang_layout(lang_dir, missing_dirs={"detectors"})

    with pytest.raises(ValueError, match=r"missing required directory: detectors/"):
        lang_mod._validate_lang_structure(lang_dir, "dummy")


def test_validate_lang_structure_missing_dir_init(tmp_path):
    lang_dir = tmp_path / "dummy_lang"
    lang_dir.mkdir()
    _write_lang_layout(lang_dir, missing_dir_inits={"fixers"})

    with pytest.raises(ValueError, match=r"missing fixers/__init__\.py"):
        lang_mod._validate_lang_structure(lang_dir, "dummy")


def test_validate_lang_structure_missing_tests_file(tmp_path):
    lang_dir = tmp_path / "dummy_lang"
    lang_dir.mkdir()
    _write_lang_layout(lang_dir, include_tests=False)

    with pytest.raises(ValueError, match=r"tests directory must contain at least one test_\*\.py file"):
        lang_mod._validate_lang_structure(lang_dir, "dummy")


def test_validate_lang_structure_valid(tmp_path):
    lang_dir = tmp_path / "dummy_lang"
    lang_dir.mkdir()
    _write_lang_layout(lang_dir)

    lang_mod._validate_lang_structure(lang_dir, "dummy")


def test_get_lang_rejects_invalid_contract():
    class BadConfig(LangConfig):
        def __init__(self):
            super().__init__(
                name="_bad_contract",
                extensions=[".bad"],
                exclusions=[],
                default_src=".",
                build_dep_graph=lambda _p: {},
                entry_patterns=[],
                barrel_names=set(),
                phases=[],  # invalid: empty
                fixers={},
                detect_commands={},  # invalid: empty
                extract_functions=None,  # invalid: not callable
                file_finder=None,  # invalid: not callable
                detect_markers=["bad.toml"],
                zone_rules=[],
            )

    _registry["_bad_contract"] = BadConfig
    try:
        with pytest.raises(ValueError, match="invalid LangConfig contract"):
            get_lang("_bad_contract")
    finally:
        _registry.pop("_bad_contract", None)


def test_get_lang_rejects_non_snake_case_detect_command_key():
    class BadKeyConfig(LangConfig):
        def __init__(self):
            super().__init__(
                name="_bad_key",
                extensions=[".bad"],
                exclusions=[],
                default_src=".",
                build_dep_graph=lambda _p: {},
                entry_patterns=[],
                barrel_names=set(),
                phases=[DetectorPhase("phase", lambda _p, _l: ([], {}))],
                fixers={},
                detect_commands={"single-use": lambda _a: None},
                extract_functions=lambda _p: [],
                file_finder=lambda _p: [],
                detect_markers=["bad.toml"],
                zone_rules=[object()],
            )

    _registry["_bad_key"] = BadKeyConfig
    try:
        with pytest.raises(ValueError, match="snake_case"):
            get_lang("_bad_key")
    finally:
        _registry.pop("_bad_key", None)


def test_load_all_surfaces_import_failures(monkeypatch):
    import importlib

    original_registry = dict(_registry)
    real_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == ".python":
            raise ImportError("simulated import failure")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    monkeypatch.setattr(lang_mod, "_load_attempted", False)
    monkeypatch.setattr(lang_mod, "_load_errors", {})
    _registry.clear()

    try:
        with pytest.raises(ImportError, match="Language plugin import failures"):
            lang_mod._load_all()
    finally:
        _registry.clear()
        _registry.update(original_registry)
