"""Tests for desloppify.search and desloppify.versioning modules."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import desloppify.search as search_mod
from desloppify.search import (
    grep_count_files,
    grep_files,
    grep_files_containing,
)
from desloppify.versioning import check_tool_staleness, compute_tool_hash

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def fake_read(monkeypatch):
    """Provide a helper that patches read_file_text to return controlled content.

    Usage: fake_read({"/abs/path/a.py": "line one\\nline two"})
    """

    def _setup(file_contents: dict[str, str | None]):
        def _read(filepath: str) -> str | None:
            return file_contents.get(filepath)

        monkeypatch.setattr(search_mod, "read_file_text", _read)
        # Also make all paths resolve as absolute so PROJECT_ROOT fallback isn't needed
        monkeypatch.setattr(search_mod.os.path, "isabs", lambda p: True)

    return _setup


# ── grep_files ────────────────────────────────────────────────


def test_grep_files_returns_matching_lines(fake_read):
    """Matching lines are returned with correct filepath, line number, and text."""
    fake_read({"/a.py": "foo bar\nbaz\nfoo again"})
    results = grep_files("foo", ["/a.py"])
    assert results == [("/a.py", 1, "foo bar"), ("/a.py", 3, "foo again")]


def test_grep_files_skips_unreadable_files(fake_read):
    """Files returning None from read_file_text are silently skipped."""
    fake_read({"/a.py": None, "/b.py": "match here"})
    results = grep_files("match", ["/a.py", "/b.py"])
    assert len(results) == 1
    assert results[0][0] == "/b.py"


def test_grep_files_respects_regex_flags(fake_read):
    """The flags argument is forwarded to re.compile (e.g. IGNORECASE)."""
    import re

    fake_read({"/a.py": "Hello World\nhello world"})
    # Without IGNORECASE, only lowercase matches
    results_case = grep_files("hello", ["/a.py"], flags=0)
    assert len(results_case) == 1
    assert results_case[0][1] == 2

    # With IGNORECASE, both lines match
    results_nocase = grep_files("hello", ["/a.py"], flags=re.IGNORECASE)
    assert len(results_nocase) == 2


def test_grep_files_empty_file_list(fake_read):
    """Empty file list returns empty results."""
    fake_read({})
    results = grep_files("anything", [])
    assert results == []


# ── grep_files_containing ────────────────────────────────────


def test_grep_files_containing_finds_names_in_files(fake_read):
    """Each name maps to the set of files that contain it."""
    fake_read({
        "/a.py": "import foo\nuse bar",
        "/b.py": "only foo here",
    })
    result = grep_files_containing({"foo", "bar"}, ["/a.py", "/b.py"])
    assert result["foo"] == {"/a.py", "/b.py"}
    assert result["bar"] == {"/a.py"}


def test_grep_files_containing_empty_names_returns_empty(fake_read):
    """Passing an empty set of names short-circuits to empty dict."""
    fake_read({"/a.py": "content"})
    result = grep_files_containing(set(), ["/a.py"])
    assert result == {}


def test_grep_files_containing_word_boundary(fake_read):
    """With word_boundary=True, partial matches within words are excluded."""
    fake_read({"/a.py": "foobar is not foo"})
    result = grep_files_containing({"foo"}, ["/a.py"], word_boundary=True)
    assert "/a.py" in result["foo"]

    # "foobar" should NOT match the name "foo" with word boundaries
    fake_read({"/b.py": "foobar"})
    result2 = grep_files_containing({"foo"}, ["/b.py"], word_boundary=True)
    assert "foo" not in result2


def test_grep_files_containing_no_word_boundary(fake_read):
    """With word_boundary=False, substrings inside words also match."""
    fake_read({"/a.py": "foobar"})
    result = grep_files_containing({"foo"}, ["/a.py"], word_boundary=False)
    assert "/a.py" in result["foo"]


# ── grep_count_files ─────────────────────────────────────────


def test_grep_count_files_returns_matching_filepaths(fake_read):
    """Files containing the name are returned."""
    fake_read({"/a.py": "hello world", "/b.py": "goodbye"})
    result = grep_count_files("hello", ["/a.py", "/b.py"])
    assert result == ["/a.py"]


def test_grep_count_files_word_boundary_on(fake_read):
    """With word_boundary=True (default), partial matches are excluded."""
    fake_read({"/a.py": "helloworld"})
    result = grep_count_files("hello", ["/a.py"], word_boundary=True)
    assert result == []


def test_grep_count_files_word_boundary_off(fake_read):
    """With word_boundary=False, substrings match."""
    fake_read({"/a.py": "helloworld"})
    result = grep_count_files("hello", ["/a.py"], word_boundary=False)
    assert result == ["/a.py"]


def test_grep_count_files_skips_unreadable(fake_read):
    """Unreadable files are silently skipped."""
    fake_read({"/a.py": None, "/b.py": "target"})
    result = grep_count_files("target", ["/a.py", "/b.py"])
    assert result == ["/b.py"]


# ── compute_tool_hash ────────────────────────────────────────


def test_compute_tool_hash_returns_12_char_hex():
    """Hash is a 12-character hexadecimal string."""
    h = compute_tool_hash()
    assert len(h) == 12
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_tool_hash_is_deterministic():
    """Calling compute_tool_hash twice gives the same result."""
    assert compute_tool_hash() == compute_tool_hash()


def test_compute_tool_hash_excludes_test_files(tmp_path):
    """Files under a 'tests' directory are excluded from the hash."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("x = 1")
    tests = pkg / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text("assert True")

    import desloppify.versioning as versioning_mod

    with patch.object(versioning_mod, "TOOL_DIR", pkg):
        hash_with_test = compute_tool_hash()

    # Change only the test file
    (tests / "test_core.py").write_text("assert False")

    with patch.object(versioning_mod, "TOOL_DIR", pkg):
        hash_after_test_change = compute_tool_hash()

    assert hash_with_test == hash_after_test_change


def test_compute_tool_hash_changes_on_source_change(tmp_path):
    """Changing a non-test .py file produces a different hash."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("x = 1")

    import desloppify.versioning as versioning_mod

    with patch.object(versioning_mod, "TOOL_DIR", pkg):
        hash_before = compute_tool_hash()

    (pkg / "core.py").write_text("x = 2")

    with patch.object(versioning_mod, "TOOL_DIR", pkg):
        hash_after = compute_tool_hash()

    assert hash_before != hash_after


def test_compute_tool_hash_handles_unreadable_file(tmp_path):
    """Unreadable files produce a fallback hash entry instead of crashing."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("x = 1")
    unreadable = pkg / "broken.py"
    unreadable.write_text("content")
    unreadable.chmod(0o000)

    import desloppify.versioning as versioning_mod

    try:
        with patch.object(versioning_mod, "TOOL_DIR", pkg):
            h = compute_tool_hash()
        assert len(h) == 12
    finally:
        # Restore permissions so tmp_path cleanup succeeds
        unreadable.chmod(0o644)


# ── check_tool_staleness ─────────────────────────────────────


def test_check_tool_staleness_returns_none_when_no_stored_hash():
    """If state has no tool_hash key, no staleness warning is produced."""
    assert check_tool_staleness({}) is None
    assert check_tool_staleness({"tool_hash": ""}) is None


def test_check_tool_staleness_returns_none_when_hash_matches():
    """If stored hash matches current, no warning is produced."""
    current = compute_tool_hash()
    assert check_tool_staleness({"tool_hash": current}) is None


def test_check_tool_staleness_returns_warning_when_hash_differs():
    """If stored hash differs from current, a warning string is returned."""
    result = check_tool_staleness({"tool_hash": "000000000000"})
    assert result is not None
    assert "Tool code changed" in result
    assert "000000000000" in result
    assert "next scan" in result
