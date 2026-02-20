"""Tests for Go function extraction."""

from __future__ import annotations

import textwrap
from pathlib import Path

from desloppify.languages.go import GoConfig
from desloppify.languages.go.extractors import extract_go_functions


def _write_go(tmp_path: Path, name: str, code: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(code))
    return path


def test_go_config_extract_functions_scans_directory(tmp_path):
    _write_go(
        tmp_path,
        "alpha.go",
        """\
        package example

        func Alpha() {
            a := 1
            b := 2
            _ = a + b
        }
        """,
    )
    _write_go(
        tmp_path,
        "beta.go",
        """\
        package example

        func Beta() {
            x := 10
            y := x * 2
            _ = y
        }
        """,
    )

    cfg = GoConfig()
    names = {fn.name for fn in cfg.extract_functions(tmp_path)}
    assert names == {"Alpha", "Beta"}


def test_extract_go_functions_supports_generics(tmp_path):
    path = _write_go(
        tmp_path,
        "generic.go",
        """\
        package example

        func Map[T any](items []T) []T {
            out := make([]T, 0, len(items))
            for _, item := range items {
                out = append(out, item)
            }
            return out
        }
        """,
    )

    names = {fn.name for fn in extract_go_functions(path)}
    assert "Map" in names


def test_extract_go_functions_multiline_strings(tmp_path):
    path = _write_go(
        tmp_path,
        "multiline.go",
        """\
        package example

        func Multiline() {
            query := `
            SELECT * FROM users
            WHERE {id: 1} /* {ignore} */
            `
            _ = query
        }

        func NextFunc() {
            _ = 1
        }
        """,
    )

    names = {fn.name for fn in extract_go_functions(path)}
    assert names == {"Multiline", "NextFunc"}


def test_extract_go_functions_strings_with_braces(tmp_path):
    path = _write_go(
        tmp_path,
        "strings_braces.go",
        """\
        package example

        func WithBraces() {
            a := 1
            s := "x"; }
        
        func Another() {
            a := 1
            b := 2
            _ = a + b
        }
        """,
    )

    names = {fn.name for fn in extract_go_functions(path)}
    assert names == {"WithBraces", "Another"}
