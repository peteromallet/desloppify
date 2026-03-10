"""Tests for core utilities — paths, exclusions, file discovery, grep, hashing."""

import os
from pathlib import Path

import pytest

import desloppify.base.text_utils as utils_text_mod
import desloppify.base.discovery.paths as paths_api_mod
import desloppify.base.tooling as tooling_mod
from desloppify.base.discovery.file_paths import (
    matches_exclusion,
    rel,
    resolve_path,
)
from desloppify.base.discovery.source import (
    SourceDiscoveryOptions,
    clear_source_file_cache_for_tests,
    find_source_files,
    get_exclusions,
    set_exclusions,
)
from desloppify.base.search.grep import grep_count_files, grep_files, grep_files_containing
from desloppify.base.discovery.paths import read_code_snippet
from desloppify.base.tooling import check_tool_staleness, compute_tool_hash


@pytest.fixture
def patch_project_root(monkeypatch):
    """Patch project root via RuntimeContext so all consumers see the override."""
    from desloppify.base.runtime_state import current_runtime_context

    ctx = current_runtime_context()

    def _patch(tmp_path):
        monkeypatch.setattr(ctx, "project_root", tmp_path)
        clear_source_file_cache_for_tests()

    return _patch


# ── rel() ────────────────────────────────────────────────────


def test_rel_absolute_under_project_root(monkeypatch):
    """Absolute path under PROJECT_ROOT is converted to relative."""
    root = paths_api_mod.get_project_root()
    abs_path = str(root / "foo" / "bar.py")
    assert rel(abs_path) == "foo/bar.py"


def test_rel_path_outside_project_root(tmp_path, monkeypatch):
    """Path outside PROJECT_ROOT is returned as a relative path from PROJECT_ROOT."""
    outside = str(tmp_path / "unrelated" / "file.py")
    result = rel(outside)
    # Path outside PROJECT_ROOT should be normalized to a relative path
    try:
        expected = os.path.relpath(outside, str(paths_api_mod.get_project_root())).replace(
            "\\", "/"
        )
    except ValueError:
        # Windows cross-drive fallback: rel() should return absolute normalized path.
        expected = str(Path(outside).resolve()).replace("\\", "/")
    assert result == expected


# ── resolve_path() ───────────────────────────────────────────


def test_resolve_path_relative():
    """Relative path is resolved to absolute under PROJECT_ROOT."""
    root = paths_api_mod.get_project_root()
    result = resolve_path("src/foo.py")
    assert os.path.isabs(result)
    assert result == str((root / "src" / "foo.py").resolve())


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


def test_matches_exclusion_dir_doublestar():
    """'Wan2GP/**' matches files under Wan2GP/ (glob-style exclusion)."""
    assert matches_exclusion("Wan2GP/models/rf.py", "Wan2GP/**") is True
    assert matches_exclusion("Wan2GP/sub/deep/file.py", "Wan2GP/**") is True


def test_matches_exclusion_dir_doublestar_no_match():
    """'Wan2GP/**' does not match files outside Wan2GP/."""
    assert matches_exclusion("Other/models/rf.py", "Wan2GP/**") is False
    assert matches_exclusion("Wan2GPx/foo.py", "Wan2GP/**") is False


def test_matches_exclusion_nested_dir_doublestar():
    """'src/vendor/**' matches nested glob exclusions."""
    assert matches_exclusion("src/vendor/foo.py", "src/vendor/**") is True
    assert matches_exclusion("src/vendor/sub/bar.py", "src/vendor/**") is True
    assert matches_exclusion("src/other/foo.py", "src/vendor/**") is False


def test_matches_exclusion_exact_directory_path():
    """Multi-segment exclusions should match the directory itself, not only children."""
    assert matches_exclusion(".claude/worktrees", ".claude/worktrees") is True


# ── find_source_files() ─────────────────────────────────────


def test_find_source_files_extensions(tmp_path, patch_project_root):
    """Only files with matching extensions are returned."""
    patch_project_root(tmp_path)

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


def test_find_source_files_excludes_default_dirs(tmp_path, patch_project_root):
    """Directories in DEFAULT_EXCLUSIONS (like __pycache__) are pruned."""
    patch_project_root(tmp_path)

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


def test_find_source_files_with_explicit_exclusion(tmp_path, patch_project_root):
    """Explicit exclusions filter out matching paths."""
    patch_project_root(tmp_path)

    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.py").write_text("keep")

    gen = src / "generated"
    gen.mkdir()
    (gen / "auto.py").write_text("auto")

    files = find_source_files(
        str(src),
        [".py"],
        SourceDiscoveryOptions(exclusions=("generated",)),
    )
    assert len(files) == 1
    assert any("keep.py" in f for f in files)
    assert not any("generated" in f for f in files)


def test_find_source_files_excludes_prefixed_virtualenv_dirs(tmp_path, patch_project_root):
    """Prefixed virtualenv directories (.venv-*, venv-*) are pruned."""
    patch_project_root(tmp_path)

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
    """set_exclusions() updates the runtime context exclusion config."""
    # Save original
    original = get_exclusions()
    try:
        set_exclusions(["vendor", "third_party"])
        assert get_exclusions() == ("vendor", "third_party")
    finally:
        # Restore
        set_exclusions(list(original))
        clear_source_file_cache_for_tests()


# ── grep_files() ─────────────────────────────────────────────


def test_grep_files(tmp_path, patch_project_root):
    """grep_files returns (filepath, lineno, line) tuples for matches."""
    patch_project_root(tmp_path)

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


def test_grep_files_no_match(tmp_path, patch_project_root):
    """grep_files returns empty list when nothing matches."""
    patch_project_root(tmp_path)

    f1 = tmp_path / "c.py"
    f1.write_text("x = 1\ny = 2\n")

    results = grep_files(r"zzz_nonexistent", [str(f1)])
    assert results == []


def test_grep_files_multiple_matches(tmp_path, patch_project_root):
    """grep_files finds multiple matches across lines and files."""
    patch_project_root(tmp_path)

    f1 = tmp_path / "d.py"
    f1.write_text("TODO: fix\nok\nTODO: refactor\n")

    results = grep_files(r"TODO", [str(f1)])
    assert len(results) == 2
    assert results[0][1] == 1
    assert results[1][1] == 3


# ── grep_files_containing() ─────────────────────────────────


def test_grep_files_containing(tmp_path, patch_project_root):
    """grep_files_containing maps names to sets of files containing them."""
    patch_project_root(tmp_path)

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


def test_grep_files_containing_word_boundary(tmp_path, patch_project_root):
    """Word boundary prevents partial matches by default."""
    patch_project_root(tmp_path)

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


def test_grep_count_files(tmp_path, patch_project_root):
    """grep_count_files returns list of files containing the name."""
    patch_project_root(tmp_path)

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


def test_check_tool_staleness_reports_unreadable_files(tmp_path, monkeypatch):
    """Staleness warning includes unreadable-file diagnostics."""
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    readable = tool_dir / "ok.py"
    readable.write_text("x = 1\n")
    unreadable = tool_dir / "broken.py"
    unreadable.write_text("x = 2\n")

    original_read_bytes = Path.read_bytes

    def _patched_read_bytes(path_obj: Path):
        if path_obj == unreadable:
            raise OSError("permission denied")
        return original_read_bytes(path_obj)

    monkeypatch.setattr(Path, "read_bytes", _patched_read_bytes, raising=False)
    monkeypatch.setattr(tooling_mod, "TOOL_DIR", tool_dir)

    result = check_tool_staleness({"tool_hash": "aaaaaaaaaaaa"})
    assert result is not None
    assert "unreadable file" in result


# ── read_code_snippet() ────────────────────────────────────


def test_read_code_snippet_basic(tmp_path, patch_project_root):
    """Returns lines around target with arrow marker."""
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    patch_project_root(tmp_path)
    result = read_code_snippet("test.py", 3, context=1)
    assert result is not None
    assert "→" in result
    assert "line3" in result
    assert "line2" in result
    assert "line4" in result


def test_read_code_snippet_first_line(tmp_path, patch_project_root):
    """First line should work without negative indices."""
    f = tmp_path / "test.py"
    f.write_text("first\nsecond\nthird\n")
    patch_project_root(tmp_path)
    result = read_code_snippet("test.py", 1, context=1)
    assert result is not None
    assert "first" in result
    assert "→" in result


def test_read_code_snippet_out_of_range(tmp_path, patch_project_root):
    """Line out of range returns None."""
    f = tmp_path / "test.py"
    f.write_text("only line\n")
    patch_project_root(tmp_path)
    assert read_code_snippet("test.py", 99) is None
    assert read_code_snippet("test.py", 0) is None


def test_read_code_snippet_nonexistent_file(tmp_path, patch_project_root):
    """Missing file returns None."""
    patch_project_root(tmp_path)
    assert read_code_snippet("no_such_file.py", 1) is None


def test_read_code_snippet_long_line_truncated(tmp_path, patch_project_root):
    """Lines longer than 120 chars are truncated."""
    f = tmp_path / "test.py"
    f.write_text("x" * 200 + "\n")
    patch_project_root(tmp_path)
    result = read_code_snippet("test.py", 1, context=0)
    assert result is not None
    assert "..." in result
    assert len(result.split("│")[1].strip()) <= 120


def test_utils_text_read_code_snippet_project_root_override(tmp_path):
    """utils_text helper supports explicit project_root override."""
    f = tmp_path / "sample.py"
    f.write_text("one\ntwo\nthree\n")

    result = utils_text_mod.read_code_snippet("sample.py", 2, project_root=tmp_path)
    assert result is not None
    assert "two" in result
    assert "→" in result


def test_utils_text_read_code_snippet_absolute_path(tmp_path):
    """Absolute paths are read directly, regardless of project_root."""
    f = tmp_path / "absolute.py"
    f.write_text("alpha\nbeta\n")

    result = utils_text_mod.read_code_snippet(
        str(f), 1, project_root=tmp_path / "does-not-matter"
    )
    assert result is not None
    assert "alpha" in result
