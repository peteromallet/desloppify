"""Tests for desloppify.commands.dev_cmd."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import desloppify.commands.dev_cmd as dev_mod


REQUIRED_SCAFFOLD_PATHS = [
    "__init__.py",
    "commands.py",
    "extractors.py",
    "phases.py",
    "move.py",
    "review.py",
    "test_coverage.py",
    "detectors/__init__.py",
    "detectors/deps.py",
    "fixers/__init__.py",
    "tests/__init__.py",
    "tests/test_init.py",
]


def _args(**overrides):
    payload = {
        "dev_action": "scaffold-lang",
        "name": "ruby",
        "extension": [".rb"],
        "marker": ["Gemfile"],
        "default_src": "lib",
        "force": False,
        "wire_pyproject": False,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_scaffold_lang_creates_standard_files(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_mod, "PROJECT_ROOT", tmp_path)
    dev_mod.cmd_dev(_args())

    lang_dir = tmp_path / "desloppify" / "lang" / "ruby"
    assert lang_dir.is_dir()
    for rel_path in REQUIRED_SCAFFOLD_PATHS:
        assert (lang_dir / rel_path).exists(), f"missing scaffold path: {rel_path}"

    init_text = (lang_dir / "__init__.py").read_text()
    assert '@register_lang("ruby")' in init_text


def test_scaffold_lang_requires_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_mod, "PROJECT_ROOT", tmp_path)
    with pytest.raises(SystemExit, match="at least one --extension is required"):
        dev_mod.cmd_dev(_args(extension=[]))


def test_scaffold_lang_rejects_invalid_name(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_mod, "PROJECT_ROOT", tmp_path)
    with pytest.raises(SystemExit, match="language name must match"):
        dev_mod.cmd_dev(_args(name="123ruby"))


def test_scaffold_lang_force_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_mod, "PROJECT_ROOT", tmp_path)
    dev_mod.cmd_dev(_args())

    target = tmp_path / "desloppify" / "lang" / "ruby" / "commands.py"
    target.write_text("SENTINEL\n")

    with pytest.raises(SystemExit, match="Language directory already exists"):
        dev_mod.cmd_dev(_args())
    assert target.read_text() == "SENTINEL\n"

    dev_mod.cmd_dev(_args(force=True))
    assert "placeholder detector command" in target.read_text()


def test_scaffold_lang_wires_pyproject_once(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_mod, "PROJECT_ROOT", tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.setuptools.packages.find]\n"
        "exclude = [\n"
        "  \"existing\",\n"
        "]\n\n"
        "[tool.pytest.ini_options]\n"
        "testpaths = [\n"
        "  \"tests\",\n"
        "]\n"
    )

    dev_mod.cmd_dev(_args(wire_pyproject=True))
    first = pyproject.read_text()
    assert 'desloppify.lang.ruby.tests*' in first
    assert 'desloppify/lang/ruby/tests' in first

    dev_mod.cmd_dev(_args(force=True, wire_pyproject=True))
    second = pyproject.read_text()
    assert second.count('desloppify.lang.ruby.tests*') == 1
    assert second.count('desloppify/lang/ruby/tests') == 1
