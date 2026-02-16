"""Tests for desloppify.utils — paths, exclusions, file discovery, grep, hashing."""

import os
import textwrap
from pathlib import Path

import pytest

import desloppify.utils as utils_mod
from desloppify.utils import (
    check_tool_staleness,
    compute_tool_hash,
    find_source_files,
    grep_count_files,
    grep_files,
    grep_files_containing,
    matches_exclusion,
    read_code_snippet,
    rel,
    resolve_path,
    set_exclusions,
)


# ── rel() ────────────────────────────────────────────────────


def test_rel_absolute_under_project_root(monkeypatch):
    """Absolute path under PROJECT_ROOT is converted to relative."""
    root = utils_mod.PROJECT_ROOT
    abs_path = str(root / "foo" / "bar.py")
    assert rel(abs_path) == "foo/bar.py"


def test_rel_path_outside_project_root(tmp_path, monkeypatch):
    """Path outside PROJECT_ROOT is returned as a relative path from PROJECT_ROOT."""
    import os
    outside = str(tmp_path / "unrelated" / "file.py")
    result = rel(outside)
    # Path outside PROJECT_ROOT should be normalized to a relative path
    try:
        expected = os.path.relpath(outside, str(utils_mod.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        # Windows cross-drive fallback: rel() should return absolute normalized path.
        expected = str(Path(outside).resolve()).replace("\\", "/")
    assert result == expected


# ── resolve_path() ───────────────────────────────────────────


def test_resolve_path_relative(monkeypatch):
    """Relative path is resolved to absolute under PROJECT_ROOT."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", utils_mod.PROJECT_ROOT)
    result = resolve_path("src/foo.py")
    assert os.path.isabs(result)
    assert result == str((utils_mod.PROJECT_ROOT / "src" / "foo.py").resolve())


def test_resolve_path_absolute(tmp_path):
    """Absolute path stays absolute and is resolved."""
    abs_path = str(tmp_path / "bar.py")
    result = resolve_path(abs_path)
    assert os.path.isabs(result)
    assert result == str(tmp_path / "bar.py")


# ── matches_exclusion() ─────────────────────────────────────


def test_matches_exclusion_component_prefix():
    """'test' matches 'test/foo.py' — component at start."""
    assert matches_exclusion("test/foo.py", "test") is True


def test_matches_exclusion_component_middle():
    """'test' matches 'src/test/bar.py' — component in the middle."""
    assert matches_exclusion("src/test/bar.py", "test") is True


def test_matches_exclusion_no_substring():
    """'test' does NOT match 'testimony.py' — not a component boundary."""
    assert matches_exclusion("testimony.py", "test") is False


def test_matches_exclusion_directory_prefix():
    """'src/test' matches 'src/test/bar.py' — multi-segment prefix."""
    assert matches_exclusion("src/test/bar.py", "src/test") is True


def test_matches_exclusion_no_match():
    """'lib' does not match 'src/test/bar.py'."""
    assert matches_exclusion("src/test/bar.py", "lib") is False


def test_matches_exclusion_partial_dir_no_match():
    """'src/tes' should NOT match 'src/test/bar.py' — partial component."""
    assert matches_exclusion("src/test/bar.py", "src/tes") is False


# ── find_source_files() ─────────────────────────────────────


def test_find_source_files_extensions(tmp_path, monkeypatch):
    """Only files with matching extensions are returned."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    # Clear the lru_cache so our monkeypatched PROJECT_ROOT takes effect
    utils_mod._find_source_files_cached.cache_clear()

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hello')")
    (src / "readme.txt").write_text("docs")
    (src / "lib.py").write_text("x = 1")

    files = find_source_files(str(src), [".py"])
    assert len(files) == 2
    assert all(f.endswith(".py") for f in files)
    # Verify no .txt files
    assert not any(f.endswith(".txt") for f in files)


def test_find_source_files_excludes_default_dirs(tmp_path, monkeypatch):
    """Directories in DEFAULT_EXCLUSIONS (like __pycache__) are pruned."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()

    src = tmp_path / "pkg"
    src.mkdir()
    (src / "main.py").write_text("x = 1")

    cache_dir = src / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "main.cpython-312.pyc.py").write_text("cached")

    files = find_source_files(str(src), [".py"])
    assert len(files) == 1
    assert any("main.py" in f for f in files)
    assert not any("__pycache__" in f for f in files)


def test_find_source_files_with_explicit_exclusion(tmp_path, monkeypatch):
    """Explicit exclusions filter out matching paths."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()

    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.py").write_text("keep")

    gen = src / "generated"
    gen.mkdir()
    (gen / "auto.py").write_text("auto")

    files = find_source_files(str(src), [".py"], exclusions=["generated"])
    assert len(files) == 1
    assert any("keep.py" in f for f in files)
    assert not any("generated" in f for f in files)


def test_find_source_files_excludes_prefixed_virtualenv_dirs(tmp_path, monkeypatch):
    """Prefixed virtualenv directories (.venv-*, venv-*) are pruned."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()

    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.py").write_text("keep")

    hidden_venv = src / ".venv-custom"
    hidden_venv.mkdir()
    (hidden_venv / "skip_hidden.py").write_text("skip")

    named_venv = src / "venv-project"
    named_venv.mkdir()
    (named_venv / "skip_named.py").write_text("skip")

    files = find_source_files(str(src), [".py"])
    assert files == ["src/keep.py"]


# ── set_exclusions() ─────────────────────────────────────────


def test_set_exclusions(monkeypatch):
    """set_exclusions() updates the module-level _extra_exclusions."""
    # Save original
    original = utils_mod._extra_exclusions
    try:
        set_exclusions(["vendor", "third_party"])
        assert utils_mod._extra_exclusions == ("vendor", "third_party")
    finally:
        # Restore
        utils_mod._extra_exclusions = original
        utils_mod._find_source_files_cached.cache_clear()


# ── grep_files() ─────────────────────────────────────────────


def test_grep_files(tmp_path, monkeypatch):
    """grep_files returns (filepath, lineno, line) tuples for matches."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)

    f1 = tmp_path / "a.py"
    f1.write_text("def foo():\n    return 42\n")
    f2 = tmp_path / "b.py"
    f2.write_text("class Bar:\n    pass\n")

    results = grep_files(r"def\s+\w+", [str(f1), str(f2)])
    assert len(results) == 1
    filepath, lineno, line = results[0]
    assert filepath == str(f1)
    assert lineno == 1
    assert "def foo" in line


def test_grep_files_no_match(tmp_path, monkeypatch):
    """grep_files returns empty list when nothing matches."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)

    f1 = tmp_path / "c.py"
    f1.write_text("x = 1\ny = 2\n")

    results = grep_files(r"zzz_nonexistent", [str(f1)])
    assert results == []


def test_grep_files_multiple_matches(tmp_path, monkeypatch):
    """grep_files finds multiple matches across lines and files."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)

    f1 = tmp_path / "d.py"
    f1.write_text("TODO: fix\nok\nTODO: refactor\n")

    results = grep_files(r"TODO", [str(f1)])
    assert len(results) == 2
    assert results[0][1] == 1
    assert results[1][1] == 3


# ── grep_files_containing() ─────────────────────────────────


def test_grep_files_containing(tmp_path, monkeypatch):
    """grep_files_containing maps names to sets of files containing them."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)

    f1 = tmp_path / "m1.py"
    f1.write_text("import foo\nfrom bar import baz\n")
    f2 = tmp_path / "m2.py"
    f2.write_text("import baz\nx = foo\n")

    result = grep_files_containing({"foo", "baz"}, [str(f1), str(f2)])

    assert "foo" in result
    assert str(f1) in result["foo"]
    assert str(f2) in result["foo"]

    assert "baz" in result
    assert str(f1) in result["baz"]
    assert str(f2) in result["baz"]


def test_grep_files_containing_word_boundary(tmp_path, monkeypatch):
    """Word boundary prevents partial matches by default."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)

    f1 = tmp_path / "wb.py"
    f1.write_text("foobar\n")

    result = grep_files_containing({"foo"}, [str(f1)])
    # "foo" should NOT match "foobar" with word boundary
    assert "foo" not in result


def test_grep_files_containing_empty_names(tmp_path, monkeypatch):
    """Empty names set returns empty dict."""
    result = grep_files_containing(set(), [])
    assert result == {}


# ── grep_count_files() ──────────────────────────────────────


def test_grep_count_files(tmp_path, monkeypatch):
    """grep_count_files returns list of files containing the name."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)

    f1 = tmp_path / "g1.py"
    f1.write_text("alpha = 1\n")
    f2 = tmp_path / "g2.py"
    f2.write_text("beta = 2\n")
    f3 = tmp_path / "g3.py"
    f3.write_text("alpha = 3\n")

    result = grep_count_files("alpha", [str(f1), str(f2), str(f3)])
    assert len(result) == 2
    assert str(f1) in result
    assert str(f3) in result
    assert str(f2) not in result


# ── compute_tool_hash() ─────────────────────────────────────


def test_compute_tool_hash_format():
    """compute_tool_hash returns a 12-char hex string."""
    h = compute_tool_hash()
    assert isinstance(h, str)
    assert len(h) == 12
    # Must be valid hex
    int(h, 16)


def test_compute_tool_hash_deterministic():
    """Calling compute_tool_hash twice returns the same value."""
    assert compute_tool_hash() == compute_tool_hash()


# ── check_tool_staleness() ──────────────────────────────────


def test_check_tool_staleness_matches():
    """Returns None when stored hash matches current."""
    current = compute_tool_hash()
    state = {"tool_hash": current}
    assert check_tool_staleness(state) is None


def test_check_tool_staleness_differs():
    """Returns warning string when hash differs."""
    state = {"tool_hash": "aaaaaaaaaaaa"}
    result = check_tool_staleness(state)
    assert result is not None
    assert "changed" in result.lower()
    assert "aaaaaaaaaaaa" in result


def test_check_tool_staleness_no_stored_hash():
    """Returns None when no tool_hash in state (first run)."""
    assert check_tool_staleness({}) is None
    assert check_tool_staleness({"other_key": "val"}) is None


# ── read_code_snippet() ────────────────────────────────────


def test_read_code_snippet_basic(tmp_path, monkeypatch):
    """Returns lines around target with arrow marker."""
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    result = read_code_snippet("test.py", 3, context=1)
    assert result is not None
    assert "→" in result
    assert "line3" in result
    assert "line2" in result
    assert "line4" in result


def test_read_code_snippet_first_line(tmp_path, monkeypatch):
    """First line should work without negative indices."""
    f = tmp_path / "test.py"
    f.write_text("first\nsecond\nthird\n")
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    result = read_code_snippet("test.py", 1, context=1)
    assert result is not None
    assert "first" in result
    assert "→" in result


def test_read_code_snippet_out_of_range(tmp_path, monkeypatch):
    """Line out of range returns None."""
    f = tmp_path / "test.py"
    f.write_text("only line\n")
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    assert read_code_snippet("test.py", 99) is None
    assert read_code_snippet("test.py", 0) is None


def test_read_code_snippet_nonexistent_file(tmp_path, monkeypatch):
    """Missing file returns None."""
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    assert read_code_snippet("no_such_file.py", 1) is None


def test_read_code_snippet_long_line_truncated(tmp_path, monkeypatch):
    """Lines longer than 120 chars are truncated."""
    f = tmp_path / "test.py"
    f.write_text("x" * 200 + "\n")
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    result = read_code_snippet("test.py", 1, context=0)
    assert result is not None
    assert "..." in result
    assert len(result.split("│")[1].strip()) <= 120
