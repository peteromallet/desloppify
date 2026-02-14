"""Tests for desloppify.commands.move and language-specific helpers."""

import os
from pathlib import Path

import pytest

from desloppify.commands.move import (
    _dedup,
    _detect_lang_from_ext,
    _detect_lang_from_dir,
    _resolve_dest,
    _safe_write,
    _EXT_TO_LANG,
    cmd_move,
)


# ---------------------------------------------------------------------------
# Module imports
# ---------------------------------------------------------------------------

class TestMoveModuleSanity:
    """Verify all three move modules import cleanly."""

    def test_move_module_imports(self):
        import desloppify.commands.move
        assert callable(desloppify.commands.move.cmd_move)

    def test_move_py_module_imports(self):
        import desloppify.commands._move_py
        assert callable(desloppify.commands._move_py.find_py_replacements)
        assert callable(desloppify.commands._move_py.find_py_self_replacements)

    def test_move_ts_module_imports(self):
        import desloppify.commands._move_ts
        assert callable(desloppify.commands._move_ts.find_ts_replacements)
        assert callable(desloppify.commands._move_ts.find_ts_self_replacements)


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

    def test_csharp_cs(self):
        assert _detect_lang_from_ext("foo.cs") == "csharp"

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

    def test_csharp_dir(self, tmp_path):
        (tmp_path / "Service.cs").write_text("")
        assert _detect_lang_from_dir(str(tmp_path)) == "csharp"

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


# ---------------------------------------------------------------------------
# _move_py helpers
# ---------------------------------------------------------------------------

class TestMovePyHelpers:
    """Test Python-specific move helpers."""

    def test_path_to_py_module(self):
        from desloppify.commands._move_py import _path_to_py_module
        root = Path("/project")
        assert _path_to_py_module("/project/foo/bar.py", root) == "foo.bar"
        assert _path_to_py_module("/project/foo/__init__.py", root) == "foo"
        assert _path_to_py_module("/project/foo/baz/qux.py", root) == "foo.baz.qux"

    def test_path_to_py_module_outside_root(self):
        from desloppify.commands._move_py import _path_to_py_module
        root = Path("/project")
        assert _path_to_py_module("/other/foo.py", root) is None

    def test_has_exact_module(self):
        from desloppify.commands._move_py import _has_exact_module
        assert _has_exact_module("from foo.bar import baz", "foo.bar")
        assert not _has_exact_module("from foo.bar.child import baz", "foo.bar")
        assert _has_exact_module("import foo.bar", "foo.bar")
        assert not _has_exact_module("import foo.barx", "foo.bar")

    def test_replace_exact_module(self):
        from desloppify.commands._move_py import _replace_exact_module
        line = "from foo.bar import baz"
        result = _replace_exact_module(line, "foo.bar", "qux.quux")
        assert result == "from qux.quux import baz"

    def test_replace_exact_module_no_child(self):
        from desloppify.commands._move_py import _replace_exact_module
        line = "from foo.bar.child import baz"
        result = _replace_exact_module(line, "foo.bar", "qux.quux")
        # Should not replace because foo.bar.child is not an exact match for foo.bar
        assert result == "from foo.bar.child import baz"

    def test_compute_py_relative_import(self):
        from desloppify.commands._move_py import _compute_py_relative_import
        result = _compute_py_relative_import(
            "/project/pkg/a.py", "/project/pkg/b.py"
        )
        assert result == ".b"

    def test_compute_py_relative_import_parent(self):
        from desloppify.commands._move_py import _compute_py_relative_import
        result = _compute_py_relative_import(
            "/project/pkg/sub/a.py", "/project/pkg/b.py"
        )
        assert result == "..b"

    def test_resolve_py_relative_file(self, tmp_path):
        from desloppify.commands._move_py import _resolve_py_relative
        (tmp_path / "foo.py").write_text("")
        result = _resolve_py_relative(tmp_path, ".", "foo")
        assert result is not None
        assert result.endswith("foo.py")

    def test_resolve_py_relative_package(self, tmp_path):
        from desloppify.commands._move_py import _resolve_py_relative
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        result = _resolve_py_relative(tmp_path, ".", "pkg")
        assert result is not None
        assert result.endswith("__init__.py")

    def test_resolve_py_relative_not_found(self, tmp_path):
        from desloppify.commands._move_py import _resolve_py_relative
        result = _resolve_py_relative(tmp_path, ".", "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# _move_ts helpers
# ---------------------------------------------------------------------------

class TestMoveTsHelpers:
    """Test TypeScript-specific move helpers."""

    def test_strip_ts_ext(self):
        from desloppify.commands._move_ts import _strip_ts_ext
        assert _strip_ts_ext("foo.ts") == "foo"
        assert _strip_ts_ext("foo.tsx") == "foo"
        assert _strip_ts_ext("foo.js") == "foo"
        assert _strip_ts_ext("foo.jsx") == "foo"
        assert _strip_ts_ext("foo") == "foo"
        assert _strip_ts_ext("foo.css") == "foo.css"

    def test_compute_ts_specifiers_relative(self):
        from desloppify.commands._move_ts import _compute_ts_specifiers
        # Same directory
        alias, relative = _compute_ts_specifiers(
            "/project/src/a.ts", "/project/src/b.ts"
        )
        assert relative == "./b"

    def test_compute_ts_specifiers_parent(self):
        from desloppify.commands._move_ts import _compute_ts_specifiers
        alias, relative = _compute_ts_specifiers(
            "/project/src/sub/a.ts", "/project/src/b.ts"
        )
        assert relative == "../b"

    def test_strip_index_from_relative(self):
        from desloppify.commands._move_ts import _compute_ts_specifiers
        alias, relative = _compute_ts_specifiers(
            "/project/src/a.ts", "/project/src/utils/index.ts"
        )
        assert relative == "./utils"
        assert not relative.endswith("/index")
