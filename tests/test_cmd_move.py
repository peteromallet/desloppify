"""Tests for generic move command helpers."""

from pathlib import Path

from desloppify.commands.move import (
    _dedup,
    _detect_lang_from_ext,
    _detect_lang_from_dir,
    _resolve_dest,
    _safe_write,
)


# ---------------------------------------------------------------------------
# Module imports
# ---------------------------------------------------------------------------

class TestMoveModuleSanity:
    """Verify move modules import cleanly."""

    def test_move_module_imports(self):
        import desloppify.commands.move
        assert callable(desloppify.commands.move.cmd_move)


# ---------------------------------------------------------------------------
# _dedup
# ---------------------------------------------------------------------------

class TestDedup:
    """_dedup removes duplicate replacement tuples while preserving order."""

    def test_empty_list(self):
        assert _dedup([]) == []

    def test_no_duplicates(self):
        pairs = [("a", "b"), ("c", "d")]
        assert _dedup(pairs) == pairs

    def test_removes_duplicates(self):
        pairs = [("a", "b"), ("c", "d"), ("a", "b"), ("e", "f"), ("c", "d")]
        assert _dedup(pairs) == [("a", "b"), ("c", "d"), ("e", "f")]

    def test_preserves_order(self):
        pairs = [("z", "y"), ("a", "b"), ("z", "y")]
        assert _dedup(pairs) == [("z", "y"), ("a", "b")]

    def test_different_values_not_deduped(self):
        pairs = [("a", "b"), ("a", "c")]
        assert _dedup(pairs) == [("a", "b"), ("a", "c")]


# ---------------------------------------------------------------------------
# _detect_lang_from_ext
# ---------------------------------------------------------------------------

class TestDetectLangFromExt:
    """_detect_lang_from_ext maps file extensions to language names."""

    def test_typescript_ts(self):
        assert _detect_lang_from_ext("foo.ts") == "typescript"

    def test_typescript_tsx(self):
        assert _detect_lang_from_ext("foo.tsx") == "typescript"

    def test_python_py(self):
        assert _detect_lang_from_ext("foo.py") == "python"

    def test_unknown_ext(self):
        assert _detect_lang_from_ext("foo.rb") is None

    def test_no_ext(self):
        assert _detect_lang_from_ext("Makefile") is None

    def test_full_path(self):
        assert _detect_lang_from_ext("/src/components/Button.tsx") == "typescript"


# ---------------------------------------------------------------------------
# _detect_lang_from_dir
# ---------------------------------------------------------------------------

class TestDetectLangFromDir:
    """_detect_lang_from_dir inspects directory contents."""

    def test_python_dir(self, tmp_path):
        (tmp_path / "foo.py").write_text("")
        assert _detect_lang_from_dir(str(tmp_path)) == "python"

    def test_typescript_dir(self, tmp_path):
        (tmp_path / "bar.ts").write_text("")
        assert _detect_lang_from_dir(str(tmp_path)) == "typescript"

    def test_empty_dir(self, tmp_path):
        assert _detect_lang_from_dir(str(tmp_path)) is None

    def test_no_source_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("")
        (tmp_path / "config.yml").write_text("")
        assert _detect_lang_from_dir(str(tmp_path)) is None

    def test_nested_files(self, tmp_path):
        sub = tmp_path / "src" / "components"
        sub.mkdir(parents=True)
        (sub / "App.tsx").write_text("")
        assert _detect_lang_from_dir(str(tmp_path)) == "typescript"


# ---------------------------------------------------------------------------
# _resolve_dest
# ---------------------------------------------------------------------------

class TestResolveDest:
    """_resolve_dest resolves destination paths."""

    def test_file_to_file(self, tmp_path):
        source = "src/foo.ts"
        dest = str(tmp_path / "bar.ts")
        result = _resolve_dest(source, dest)
        assert result.endswith("bar.ts")

    def test_file_to_dir_keeps_filename(self, tmp_path):
        target_dir = tmp_path / "newdir"
        target_dir.mkdir()
        source = "src/foo.ts"
        result = _resolve_dest(source, str(target_dir))
        assert result.endswith("foo.ts")
        assert "newdir" in result

    def test_file_to_trailing_slash(self, tmp_path):
        source = "src/foo.ts"
        result = _resolve_dest(source, str(tmp_path) + "/")
        assert result.endswith("foo.ts")


# ---------------------------------------------------------------------------
# _safe_write
# ---------------------------------------------------------------------------

class TestSafeWrite:
    """_safe_write performs atomic writes."""

    def test_writes_content(self, tmp_path):
        target = tmp_path / "output.txt"
        _safe_write(str(target), "hello world")
        assert target.read_text() == "hello world"

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "output.txt"
        target.write_text("old content")
        _safe_write(str(target), "new content")
        assert target.read_text() == "new content"

    def test_no_temp_file_left(self, tmp_path):
        target = tmp_path / "output.txt"
        _safe_write(str(target), "hello")
        tmp_file = target.with_suffix(".txt.tmp")
        assert not tmp_file.exists()

    def test_string_path_works(self, tmp_path):
        target = str(tmp_path / "string_path.txt")
        _safe_write(target, "content")
        assert Path(target).read_text() == "content"

    def test_path_object_works(self, tmp_path):
        target = tmp_path / "path_obj.txt"
        _safe_write(target, "content")
        assert target.read_text() == "content"
