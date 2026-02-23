"""Tests for Go function extraction.

Go plugin originally contributed by tinker495 (PR #128).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.go.extractors import (
    extract_functions,
    extract_go_functions,
    normalize_go_body,
)


def _write_go_file(tmp_path: Path, name: str, content: str) -> str:
    f = tmp_path / name
    f.write_text(content)
    return str(f)


def test_extract_simple_function(tmp_path):
    filepath = _write_go_file(
        tmp_path,
        "main.go",
        """\
package main

func Hello(name string) string {
    return "Hello, " + name
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "Hello"
    assert funcs[0].loc >= 3


def test_extract_method_receiver(tmp_path):
    filepath = _write_go_file(
        tmp_path,
        "server.go",
        """\
package server

type Server struct{}

func (s *Server) Start() error {
    return nil
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "Start"


def test_extract_generics(tmp_path):
    filepath = _write_go_file(
        tmp_path,
        "generics.go",
        """\
package generics

func Map[T any, U any](items []T, fn func(T) U) []U {
    result := make([]U, len(items))
    for i, item := range items {
        result[i] = fn(item)
    }
    return result
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "Map"


def test_extract_backtick_string(tmp_path):
    filepath = _write_go_file(
        tmp_path,
        "template.go",
        """\
package template

func GetTemplate() string {
    return `
        <html>
        <body>{{ .Title }}</body>
        </html>
    `
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "GetTemplate"


def test_extract_string_with_braces(tmp_path):
    filepath = _write_go_file(
        tmp_path,
        "format.go",
        """\
package format

func Format() string {
    return "{}" + "{{nested}}"
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "Format"


def test_extract_multiple_functions(tmp_path):
    filepath = _write_go_file(
        tmp_path,
        "multi.go",
        """\
package multi

func First() int {
    return 1
}

func Second() int {
    return 2
}

func Third() int {
    return 3
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 3
    names = [f.name for f in funcs]
    assert names == ["First", "Second", "Third"]


def test_extract_functions_directory(tmp_path):
    _write_go_file(
        tmp_path,
        "a.go",
        """\
package pkg

func Alpha() {}
""",
    )
    _write_go_file(
        tmp_path,
        "b.go",
        """\
package pkg

func Beta() {}
""",
    )
    with patch(
        "desloppify.languages.go.extractors.find_source_files",
        return_value=[str(tmp_path / "a.go"), str(tmp_path / "b.go")],
    ), patch(
        "desloppify.languages.go.extractors.resolve_path",
        side_effect=lambda p: p,
    ):
        funcs = extract_functions(tmp_path)
    assert len(funcs) == 2
    names = {f.name for f in funcs}
    assert names == {"Alpha", "Beta"}


def test_normalize_go_body_strips_comments_and_logging():
    body = """\
func Foo() {
    // this is a comment
    log.Println("debug")
    fmt.Println("info")
    x := 1
    return x
}"""
    normalized = normalize_go_body(body)
    assert "// this is a comment" not in normalized
    assert "log.Println" not in normalized
    assert "fmt.Print" not in normalized
    assert "x := 1" in normalized


def test_extract_struct_return_type(tmp_path):
    """Braces in return types like map[K]struct{} must not confuse extraction."""
    filepath = _write_go_file(
        tmp_path,
        "cache.go",
        """\
package cache

func NewSet() map[string]struct{} {
    return make(map[string]struct{})
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "NewSet"
    assert "make(map[string]struct{})" in funcs[0].body


def test_extract_multi_return(tmp_path):
    """Functions with multiple return values (parenthesized)."""
    filepath = _write_go_file(
        tmp_path,
        "multi_ret.go",
        """\
package pkg

func Parse(s string) (int, error) {
    return 0, nil
}
""",
    )
    funcs = extract_go_functions(filepath)
    assert len(funcs) == 1
    assert funcs[0].name == "Parse"


def test_extract_nonexistent_file():
    funcs = extract_go_functions("/nonexistent/path/foo.go")
    assert funcs == []
