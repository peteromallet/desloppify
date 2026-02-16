"""Tests for TypeScript move helpers."""

from __future__ import annotations


def test_move_ts_module_imports():
    import desloppify.lang.typescript.move

    assert callable(desloppify.lang.typescript.move.find_ts_replacements)
    assert callable(desloppify.lang.typescript.move.find_ts_self_replacements)


class TestMoveTsHelpers:
    def test_strip_ts_ext(self):
        from desloppify.lang.typescript.move import _strip_ts_ext

        assert _strip_ts_ext("foo.ts") == "foo"
        assert _strip_ts_ext("foo.tsx") == "foo"
        assert _strip_ts_ext("foo.js") == "foo"
        assert _strip_ts_ext("foo.jsx") == "foo"
        assert _strip_ts_ext("foo") == "foo"
        assert _strip_ts_ext("foo.css") == "foo.css"

    def test_compute_ts_specifiers_relative(self):
        from desloppify.lang.typescript.move import _compute_ts_specifiers

        alias, relative = _compute_ts_specifiers("/project/src/a.ts", "/project/src/b.ts")
        assert relative == "./b"
        assert alias is None

    def test_compute_ts_specifiers_parent(self):
        from desloppify.lang.typescript.move import _compute_ts_specifiers

        alias, relative = _compute_ts_specifiers("/project/src/sub/a.ts", "/project/src/b.ts")
        assert relative == "../b"
        assert alias is None

    def test_strip_index_from_relative(self):
        from desloppify.lang.typescript.move import _compute_ts_specifiers

        alias, relative = _compute_ts_specifiers(
            "/project/src/a.ts",
            "/project/src/utils/index.ts",
        )
        assert relative == "./utils"
        assert not relative.endswith("/index")
        assert alias is None
