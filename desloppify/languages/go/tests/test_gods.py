"""Tests for desloppify.languages.go.detectors.gods — Go god struct detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.engine.detectors.gods import detect_gods
from desloppify.languages.go.detectors.gods import (
    GO_GOD_RULES,
    extract_go_structs,
)


def _write(tmp_path: Path, name: str, content: str) -> str:
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return str(f)


def _extract(tmp_path: Path) -> list:
    files = [str(f) for f in tmp_path.rglob("*.go")]
    with patch(
        "desloppify.languages.go.detectors.gods.find_go_files",
        return_value=files,
    ):
        return extract_go_structs(tmp_path)


# ── extract_go_structs ─────────────────────────────────────


def test_extract_simple_struct(tmp_path):
    _write(
        tmp_path,
        "model.go",
        "package model\n\ntype User struct {\n    Name string\n    Age  int\n}\n",
    )
    structs = _extract(tmp_path)
    assert len(structs) == 1
    assert structs[0].name == "User"
    assert len(structs[0].attributes) == 2


def test_extract_struct_with_methods(tmp_path):
    _write(
        tmp_path,
        "model.go",
        "package model\n\n"
        "type User struct {\n    Name string\n}\n\n"
        "func (u *User) GetName() string {\n    return u.Name\n}\n\n"
        "func (u *User) SetName(name string) {\n    u.Name = name\n}\n",
    )
    structs = _extract(tmp_path)
    assert len(structs) == 1
    assert structs[0].name == "User"
    assert len(structs[0].methods) == 2


def test_extract_methods_across_files(tmp_path):
    _write(
        tmp_path,
        "model.go",
        "package model\n\ntype User struct {\n    Name string\n}\n",
    )
    _write(
        tmp_path,
        "user_methods.go",
        "package model\n\nfunc (u *User) Validate() error {\n    return nil\n}\n",
    )
    structs = _extract(tmp_path)
    assert len(structs) == 1
    assert len(structs[0].methods) == 1


def test_extract_multiple_structs(tmp_path):
    _write(
        tmp_path,
        "model.go",
        "package model\n\n"
        "type User struct {\n    Name string\n}\n\n"
        "type Order struct {\n    ID   int\n    Item string\n}\n",
    )
    structs = _extract(tmp_path)
    assert len(structs) == 2
    names = {s.name for s in structs}
    assert names == {"User", "Order"}


def test_extract_struct_skips_comments(tmp_path):
    _write(
        tmp_path,
        "model.go",
        "package model\n\n"
        "type User struct {\n"
        "    // Name is the user's name\n"
        "    Name string\n"
        "    Age  int\n"
        "}\n",
    )
    structs = _extract(tmp_path)
    assert len(structs) == 1
    # Comment lines should not count as fields
    assert "Name" in structs[0].attributes
    assert len(structs[0].attributes) == 2


def test_metrics_populated(tmp_path):
    _write(
        tmp_path,
        "model.go",
        "package model\n\n"
        "type User struct {\n    Name string\n    Age int\n}\n\n"
        "func (u *User) Hello() {}\n",
    )
    structs = _extract(tmp_path)
    assert structs[0].metrics["field_count"] == 2
    assert structs[0].metrics["method_count"] == 1


# ── God struct detection via detect_gods ────────────────────


def test_god_struct_triggered(tmp_path):
    """A struct with many methods AND many fields triggers god detection."""
    methods = "\n".join(
        f"func (s *Big) Method{i}() {{}}" for i in range(12)
    )
    fields = "\n".join(f"    Field{i} int" for i in range(16))
    _write(
        tmp_path,
        "big.go",
        f"package big\n\ntype Big struct {{\n{fields}\n}}\n\n{methods}\n",
    )
    structs = _extract(tmp_path)
    entries, total = detect_gods(structs, GO_GOD_RULES, min_reasons=2)
    assert total == 1
    assert len(entries) == 1
    assert entries[0]["name"] == "Big"
    assert len(entries[0]["reasons"]) >= 2


def test_small_struct_not_flagged(tmp_path):
    _write(
        tmp_path,
        "small.go",
        "package small\n\ntype Small struct {\n    X int\n}\n\n"
        "func (s *Small) Get() int { return s.X }\n",
    )
    structs = _extract(tmp_path)
    entries, _ = detect_gods(structs, GO_GOD_RULES, min_reasons=2)
    assert not entries


def test_god_rules_thresholds():
    """Verify the configured threshold values."""
    rules_by_name = {r.name: r for r in GO_GOD_RULES}
    assert rules_by_name["method_count"].threshold == 10
    assert rules_by_name["field_count"].threshold == 15
    assert rules_by_name["loc"].threshold == 300
