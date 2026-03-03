"""Tests for desloppify.languages.go.detectors.smells — Go code smell detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.go.detectors.smells import detect_smells


def _write(tmp_path: Path, name: str, content: str) -> str:
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return str(f)


def _detect(tmp_path: Path) -> tuple[list[dict], int]:
    files = [str(f) for f in tmp_path.rglob("*.go") if "_test.go" not in f.name]
    with patch(
        "desloppify.languages.go.detectors.smells.find_go_files",
        return_value=files,
    ):
        return detect_smells(tmp_path)


# ── Regex-based smells ──────────────────────────────────────


def test_ignored_error_underscore(tmp_path):
    _write(tmp_path, "main.go", "package main\n\nfunc f() {\n    _ = pkg.DoSomething()\n}\n")
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "ignored_error" in ids


def test_ignored_error_assigned_err(tmp_path):
    _write(tmp_path, "main.go", "package main\n\nfunc f() {\n    _ = someErr\n}\n")
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "ignored_error" in ids


def test_naked_return(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f() (x int) {\n    x = 1\n    return\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "naked_return" in ids


def test_global_var(tmp_path):
    _write(tmp_path, "lib.go", "package lib\n\nvar GlobalState int\n")
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "global_var" in ids


def test_hardcoded_url(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        'package lib\n\nfunc f() string {\n    return "https://api.example.com/v1"\n}\n',
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "hardcoded_url" in ids


def test_hardcoded_url_constant_skipped(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        'package lib\n\nconst BaseURL = "https://api.example.com/v1"\n',
    )
    entries, _ = _detect(tmp_path)
    url_entries = [e for e in entries if e["id"] == "hardcoded_url"]
    assert not url_entries


def test_todo_fixme(tmp_path):
    _write(tmp_path, "lib.go", "package lib\n\nfunc f() {\n    // TODO fix this\n}\n")
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "todo_fixme" in ids


def test_magic_number(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f(x int) bool {\n    return x >= 9999\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "magic_number" in ids


# ── Multi-line smells ───────────────────────────────────────


def test_empty_error_branch(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f() {\n    err := doSomething()\n    if err != nil {\n    }\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "empty_error_branch" in ids


def test_panic_in_lib(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f() {\n    panic(\"oh no\")\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "panic_in_lib" in ids


def test_panic_in_main_not_flagged(tmp_path):
    _write(
        tmp_path,
        "main.go",
        "package main\n\nfunc main() {\n    panic(\"expected\")\n}\n",
    )
    entries, _ = _detect(tmp_path)
    panic_entries = [e for e in entries if e["id"] == "panic_in_lib"]
    assert not panic_entries


def test_defer_in_loop(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f() {\n    for i := 0; i < 10; i++ {\n        defer cleanup()\n    }\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "defer_in_loop" in ids


def test_monster_function(tmp_path):
    body_lines = "\n".join(f"    x{i} := {i}" for i in range(105))
    _write(
        tmp_path,
        "lib.go",
        f"package lib\n\nfunc BigFunc() {{\n{body_lines}\n}}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "monster_function" in ids


def test_dead_function(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc Noop() {\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "dead_function" in ids


def test_dead_function_with_comment_only(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc Noop() {\n    // placeholder\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "dead_function" in ids


def test_init_side_effects(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nimport \"net/http\"\n\nfunc init() {\n    http.Get(\"https://example.com\")\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "init_side_effects" in ids


def test_unreachable_code(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f() int {\n    return 1\n    x := 2\n}\n",
    )
    entries, _ = _detect(tmp_path)
    ids = {e["id"] for e in entries}
    assert "unreachable_code" in ids


def test_unreachable_code_closing_brace_not_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc f() int {\n    return 1\n}\n",
    )
    entries, _ = _detect(tmp_path)
    unreachable = [e for e in entries if e["id"] == "unreachable_code"]
    assert not unreachable


# ── Skipping / filtering ────────────────────────────────────


def test_test_files_skipped(tmp_path):
    _write(
        tmp_path,
        "lib_test.go",
        "package lib\n\nfunc f() {\n    panic(\"test panic\")\n}\n",
    )
    # Also add a file that find_go_files would return
    files = [str(tmp_path / "lib_test.go")]
    with patch(
        "desloppify.languages.go.detectors.smells.find_go_files",
        return_value=files,
    ):
        entries, _ = detect_smells(tmp_path)
    panic_entries = [e for e in entries if e["id"] == "panic_in_lib"]
    assert not panic_entries


def test_clean_code_no_smells(tmp_path):
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\nfunc Add(a, b int) int {\n    return a + b\n}\n",
    )
    entries, total = _detect(tmp_path)
    assert total == 1
    assert not entries


def test_entries_sorted_by_severity(tmp_path):
    # Write code that triggers both high and low severity smells
    _write(
        tmp_path,
        "lib.go",
        "package lib\n\n"
        "// TODO fix\n"
        "func f() {\n"
        "    _ = doSomething()\n"
        "}\n",
    )
    entries, _ = _detect(tmp_path)
    if len(entries) >= 2:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        severities = [severity_order.get(e["severity"], 9) for e in entries]
        assert severities == sorted(severities)
