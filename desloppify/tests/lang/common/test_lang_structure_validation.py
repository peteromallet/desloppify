"""Focused tests for language plugin structure validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.languages.framework.policy import REQUIRED_DIRS, REQUIRED_FILES
from desloppify.languages.framework.structure_validation import validate_lang_structure


def _write_layout(root: Path) -> None:
    for filename in REQUIRED_FILES:
        (root / filename).write_text("\n")

    for dirname in REQUIRED_DIRS:
        d = root / dirname
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text("\n")
        if dirname == "tests":
            (d / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")


def test_validate_lang_structure_reports_missing_required_file(tmp_path):
    lang_dir = tmp_path / "dummy"
    lang_dir.mkdir()
    _write_layout(lang_dir)
    (lang_dir / "commands.py").unlink()

    with pytest.raises(ValueError, match="missing required file: commands.py"):
        validate_lang_structure(lang_dir, "dummy")


def test_validate_lang_structure_accepts_valid_layout(tmp_path):
    lang_dir = tmp_path / "dummy"
    lang_dir.mkdir()
    _write_layout(lang_dir)

    validate_lang_structure(lang_dir, "dummy")
    assert (lang_dir / "commands.py").exists()
    assert (lang_dir / "tests" / "test_smoke.py").exists()
