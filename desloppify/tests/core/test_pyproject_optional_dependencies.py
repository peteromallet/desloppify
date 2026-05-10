"""Packaging metadata invariants for optional dependency extras."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def _optional_dependencies() -> dict[str, list[str]]:
    pyproject_path = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    optional = project.get("optional-dependencies", {})
    assert isinstance(optional, dict), "project.optional-dependencies must be a table"
    return optional


def _package_names(specs: list[str]) -> set[str]:
    names: set[str] = set()
    for spec in specs:
        name = re.split(r"[<>=!~;\s\[]", str(spec), maxsplit=1)[0].strip().lower()
        if name:
            names.add(name)
    return names


def test_full_extra_matches_union_of_other_extras() -> None:
    optional = _optional_dependencies()
    full_specs = optional.get("full")
    assert isinstance(full_specs, list), "optional extra 'full' must be a list"

    other_extra_names = [name for name in optional if name != "full"]
    expected = sorted(
        {
            str(spec)
            for extra_name in other_extra_names
            for spec in optional.get(extra_name, [])
        }
    )
    actual = sorted(str(spec) for spec in full_specs)
    assert actual == expected


def test_treesitter_extra_declares_runtime_and_language_pack() -> None:
    optional = _optional_dependencies()
    treesitter_specs = optional.get("treesitter")
    assert isinstance(treesitter_specs, list), "optional extra 'treesitter' must be a list"
    package_names = _package_names(treesitter_specs)
    assert "tree-sitter" in package_names
    assert "tree-sitter-language-pack" in package_names


def test_treesitter_language_pack_is_capped_below_incompatible_release() -> None:
    optional = _optional_dependencies()
    treesitter_specs = optional.get("treesitter")
    assert isinstance(treesitter_specs, list), "optional extra 'treesitter' must be a list"

    language_pack_specs = [
        str(spec)
        for spec in treesitter_specs
        if str(spec).startswith("tree-sitter-language-pack")
    ]

    assert language_pack_specs == ["tree-sitter-language-pack>=0.3,<1.8"]
