"""Tests for desloppify.languages.go.detectors.unused — staticcheck-based unused detection."""

from __future__ import annotations

from unittest.mock import patch

from desloppify.languages.go.detectors.unused import (
    _extract_name,
    _parse_staticcheck_output,
    detect_unused,
)


# ── _extract_name ───────────────────────────────────────────


def test_extract_name_quoted():
    assert _extract_name('"MyFunc" is unused') == "MyFunc"


def test_extract_name_unquoted():
    assert _extract_name("MyFunc is unused") == "MyFunc"


def test_extract_name_assigned():
    assert _extract_name('"x" is assigned but never used') == "x"


def test_extract_name_fallback():
    assert _extract_name("something else entirely") == "something"


# ── _parse_staticcheck_output ───────────────────────────────


def test_parse_u1000_unused():
    lines = [
        "pkg/handler.go:10:6: U1000 func handleRequest is unused",
    ]
    entries = _parse_staticcheck_output(lines, "all", "/project")
    assert len(entries) == 1
    assert entries[0]["name"] == "handleRequest"
    assert entries[0]["category"] == "exports"
    assert entries[0]["line"] == 10
    assert entries[0]["file"] == "/project/pkg/handler.go"


def test_parse_sa4006_unused_var():
    lines = [
        'pkg/handler.go:15:2: SA4006 "result" is assigned but never used',
    ]
    entries = _parse_staticcheck_output(lines, "all", "/project")
    assert len(entries) == 1
    assert entries[0]["name"] == "result"
    assert entries[0]["category"] == "vars"


def test_parse_filters_category():
    lines = [
        "pkg/handler.go:10:6: U1000 func handleRequest is unused",
        'pkg/handler.go:15:2: SA4006 "result" is assigned but never used',
    ]
    exports = _parse_staticcheck_output(lines, "exports", "/project")
    assert len(exports) == 1
    assert exports[0]["category"] == "exports"

    vars_ = _parse_staticcheck_output(lines, "vars", "/project")
    assert len(vars_) == 1
    assert vars_[0]["category"] == "vars"


def test_parse_skips_test_files():
    lines = [
        "pkg/handler_test.go:10:6: U1000 func testHelper is unused",
    ]
    entries = _parse_staticcheck_output(lines, "all", "/project")
    assert not entries


def test_parse_skips_underscore_prefix():
    lines = [
        "pkg/handler.go:10:6: U1000 func _internalHelper is unused",
    ]
    entries = _parse_staticcheck_output(lines, "all", "/project")
    assert not entries


def test_parse_absolute_paths():
    lines = [
        "/abs/path/handler.go:10:6: U1000 func Unused is unused",
    ]
    entries = _parse_staticcheck_output(lines, "all", "/project")
    assert entries[0]["file"] == "/abs/path/handler.go"


def test_parse_malformed_lines_ignored():
    lines = [
        "not a valid staticcheck line",
        "",
        "# some comment",
    ]
    entries = _parse_staticcheck_output(lines, "all", "/project")
    assert not entries


# ── detect_unused (integration with subprocess mock) ────────


def test_detect_unused_staticcheck_not_installed(tmp_path):
    """Graceful fallback when staticcheck is not available."""
    with patch(
        "desloppify.languages.go.detectors.unused.find_go_files",
        return_value=["a.go"],
    ), patch(
        "desloppify.languages.go.detectors.unused._try_staticcheck",
        return_value=None,
    ):
        entries, total, available = detect_unused(tmp_path)
    assert entries == []
    assert total == 1
    assert available is False


def test_detect_unused_returns_staticcheck_results(tmp_path):
    """When staticcheck is available, returns parsed results."""
    mock_entries = [
        {"file": "a.go", "line": 5, "col": 1, "name": "unused", "category": "exports"},
    ]
    with patch(
        "desloppify.languages.go.detectors.unused.find_go_files",
        return_value=["a.go", "b.go"],
    ), patch(
        "desloppify.languages.go.detectors.unused._try_staticcheck",
        return_value=(mock_entries, True),
    ):
        entries, total, available = detect_unused(tmp_path)
    assert entries == mock_entries
    assert total == 2
    assert available is True
