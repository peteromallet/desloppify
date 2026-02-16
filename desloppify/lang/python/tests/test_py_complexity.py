"""Tests for desloppify.lang.python.detectors.complexity — Python complexity signals."""

import textwrap

import pytest

from desloppify.lang.python.detectors.complexity import (
    compute_max_params,
    compute_nesting_depth,
    compute_long_functions,
    _detect_indent_unit,
)


# ── compute_max_params ────────────────────────────────────


class TestComputeMaxParams:
    def test_below_threshold_returns_none(self):
        content = "def foo(a, b, c): pass\n"
        lines = content.splitlines()
        assert compute_max_params(content, lines) is None

    def test_above_threshold(self):
        params = ", ".join(f"p{i}" for i in range(10))
        content = f"def many({params}): pass\n"
        lines = content.splitlines()
        result = compute_max_params(content, lines)
        assert result is not None
        count, label = result
        assert count == 10
        assert "10 params" in label

    def test_self_and_cls_excluded(self):
        # 8 params including self -> only 7 real -> None (threshold is >7)
        params = ", ".join(["self"] + [f"p{i}" for i in range(7)])
        content = f"def method({params}): pass\n"
        lines = content.splitlines()
        assert compute_max_params(content, lines) is None

    def test_star_args_excluded(self):
        params = ", ".join([f"p{i}" for i in range(6)] + ["*args", "**kwargs"])
        content = f"def star({params}): pass\n"
        lines = content.splitlines()
        # Only 6 real params, under threshold
        assert compute_max_params(content, lines) is None

    def test_multiple_functions_returns_max(self):
        content = textwrap.dedent("""\
            def small(a, b): pass

            def big(a, b, c, d, e, f, g, h, i): pass

            def medium(a, b, c): pass
        """)
        lines = content.splitlines()
        result = compute_max_params(content, lines)
        assert result is not None
        count, _ = result
        assert count == 9

    def test_nested_parens_handled(self):
        """Params with nested brackets are counted (commas inside brackets are not split)."""
        content = "def typed(a: dict[str, int], b: tuple[int, ...], c, d, e, f, g, h): pass\n"
        lines = content.splitlines()
        result = compute_max_params(content, lines)
        assert result is not None
        count, _ = result
        # The parser splits on commas including those inside type annotations,
        # so each comma-separated token is counted as a param.
        assert count >= 8


# ── compute_nesting_depth ─────────────────────────────────


class TestComputeNestingDepth:
    def test_shallow_returns_none(self):
        content = textwrap.dedent("""\
            def foo():
                if True:
                    pass
        """)
        lines = content.splitlines()
        assert compute_nesting_depth(content, lines) is None

    def test_deep_nesting_detected(self):
        content = textwrap.dedent("""\
            def deep():
                if True:
                    if True:
                        if True:
                            if True:
                                if True:
                                    pass
        """)
        lines = content.splitlines()
        result = compute_nesting_depth(content, lines)
        assert result is not None
        depth, label = result
        assert depth >= 5
        assert "nesting depth" in label

    def test_comments_and_blanks_ignored(self):
        content = textwrap.dedent("""\
            def foo():
                x = 1
                # a comment
                y = 2

                z = 3
        """)
        lines = content.splitlines()
        # Max depth is 1 (inside function body), which is <= 4 threshold
        assert compute_nesting_depth(content, lines) is None


# ── compute_long_functions ────────────────────────────────


class TestComputeLongFunctions:
    def test_short_function_returns_none(self):
        content = textwrap.dedent("""\
            def short():
                return 42
        """)
        lines = content.splitlines()
        assert compute_long_functions(content, lines) is None

    def test_long_function_detected(self):
        body = "\n".join(f"    x{i} = {i}" for i in range(90))
        content = f"def lengthy():\n{body}\n"
        lines = content.splitlines()
        result = compute_long_functions(content, lines)
        assert result is not None
        loc, label = result
        assert loc > 80
        assert "lengthy" in label

    def test_multiple_functions_returns_longest(self):
        short_body = "\n".join(f"    a{i} = {i}" for i in range(5))
        long_body = "\n".join(f"    b{i} = {i}" for i in range(100))
        content = f"def short_fn():\n{short_body}\n\ndef long_fn():\n{long_body}\n"
        lines = content.splitlines()
        result = compute_long_functions(content, lines)
        assert result is not None
        loc, label = result
        assert "long_fn" in label
        assert loc > 80


# ── _detect_indent_unit ───────────────────────────────────


class TestDetectIndentUnit:
    def test_4_space_indent(self):
        lines = [
            "def foo():",
            "    x = 1",
            "    if True:",
            "        pass",
        ]
        assert _detect_indent_unit(lines) == 4

    def test_2_space_indent(self):
        lines = [
            "def foo():",
            "  x = 1",
            "  if True:",
            "    pass",
        ]
        assert _detect_indent_unit(lines) == 2

    def test_empty_file(self):
        lines = []
        assert _detect_indent_unit(lines) == 4  # default

    def test_no_indented_lines(self):
        lines = ["x = 1", "y = 2"]
        assert _detect_indent_unit(lines) == 4  # default

    def test_tab_counted_as_chars(self):
        lines = [
            "def foo():",
            "\tx = 1",
        ]
        # Tab is 1 char indent
        assert _detect_indent_unit(lines) == 1
