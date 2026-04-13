"""Packaging metadata invariants for required package data."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _package_data() -> dict[str, list[str]]:
    pyproject_path = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert isinstance(package_data, dict), (
        "tool.setuptools.package-data must be a table"
    )
    return package_data


def test_visualization_template_is_packaged() -> None:
    package_data = _package_data()
    template_files = package_data.get("desloppify.app.output")
    assert isinstance(template_files, list), (
        "desloppify.app.output package data must be declared in pyproject.toml"
    )
    assert "_viz_template.html" in template_files
