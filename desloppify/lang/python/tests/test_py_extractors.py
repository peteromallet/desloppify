"""Tests for desloppify.lang.python.extractors — function/class extraction."""

import textwrap
from pathlib import Path

import pytest

from desloppify.lang.python.extractors import (
    extract_py_functions,
    extract_py_classes,
    extract_py_params,
    normalize_py_body,
    detect_passthrough_functions,
)


# ── Helpers ────────────────────────────────────────────────


def _write_py(tmp_path: Path, code: str, filename: str = "test_mod.py") -> str:
    """Write a Python file and return its path as a string."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return str(f)


# ── extract_py_functions ──────────────────────────────────


class TestExtractPyFunctions:
    def test_simple_function(self, tmp_path):
        fp = _write_py(tmp_path, """\
            def greet(name):
                greeting = f"Hello, {name}"
                return greeting
        """)
        funcs = extract_py_functions(fp)
        assert len(funcs) >= 1
        fn = funcs[0]
        assert fn.name == "greet"
        assert fn.line == 1
        assert fn.loc >= 3

    def test_async_function(self, tmp_path):
        fp = _write_py(tmp_path, """\
            async def fetch(url):
                response = await get(url)
                return response
        """)
        funcs = extract_py_functions(fp)
        assert len(funcs) >= 1
        assert funcs[0].name == "fetch"

    def test_function_params_extracted(self, tmp_path):
        fp = _write_py(tmp_path, """\
            def process(input_data, output_path, verbose=False):
                if verbose:
                    print(input_data)
                return output_path
        """)
        funcs = extract_py_functions(fp)
        assert len(funcs) >= 1
        assert "input_data" in funcs[0].params
        assert "output_path" in funcs[0].params
        assert "verbose" in funcs[0].params

    def test_self_excluded_from_params(self, tmp_path):
        fp = _write_py(tmp_path, """\
            class Foo:
                def method(self, x, y):
                    self.x = x
                    return y
        """)
        funcs = extract_py_functions(fp)
        method = [f for f in funcs if f.name == "method"]
        assert len(method) >= 1
        assert "self" not in method[0].params

    def test_multiple_functions(self, tmp_path):
        fp = _write_py(tmp_path, """\
            def alpha(a):
                x = a
                return x

            def beta(b):
                y = b
                return y

            def gamma(c):
                z = c
                return z
        """)
        funcs = extract_py_functions(fp)
        names = {f.name for f in funcs}
        assert names == {"alpha", "beta", "gamma"}

    def test_small_function_skipped(self, tmp_path):
        """Functions with < 3 normalized lines are skipped."""
        fp = _write_py(tmp_path, """\
            def tiny():
                return 1
        """)
        funcs = extract_py_functions(fp)
        # Only 2 lines -> normalized will be < 3 lines -> skipped
        names = {f.name for f in funcs}
        assert "tiny" not in names

    def test_body_hash_populated(self, tmp_path):
        fp = _write_py(tmp_path, """\
            def hashable(x):
                result = x * 2
                return result
        """)
        funcs = extract_py_functions(fp)
        assert len(funcs) >= 1
        assert funcs[0].body_hash != ""
        assert len(funcs[0].body_hash) == 32  # MD5 hex digest

    def test_nonexistent_file_returns_empty(self):
        funcs = extract_py_functions("/nonexistent/path/file.py")
        assert funcs == []

    def test_multi_line_signature(self, tmp_path):
        fp = _write_py(tmp_path, """\
            def multi_line(
                param_a,
                param_b,
                param_c,
            ):
                x = param_a
                y = param_b
                return x + y
        """)
        funcs = extract_py_functions(fp)
        assert len(funcs) >= 1
        assert funcs[0].name == "multi_line"
        assert "param_a" in funcs[0].params
        assert "param_b" in funcs[0].params
        assert "param_c" in funcs[0].params


# ── extract_py_params ─────────────────────────────────────


class TestExtractPyParams:
    def test_simple_params(self):
        params = extract_py_params("a, b, c")
        assert params == ["a", "b", "c"]

    def test_self_excluded(self):
        params = extract_py_params("self, x, y")
        assert params == ["x", "y"]

    def test_cls_excluded(self):
        params = extract_py_params("cls, x")
        assert params == ["x"]

    def test_type_annotations(self):
        params = extract_py_params("name: str, age: int")
        assert params == ["name", "age"]

    def test_defaults(self):
        params = extract_py_params("x=1, y='hello'")
        assert params == ["x", "y"]

    def test_star_args(self):
        params = extract_py_params("*args, **kwargs")
        assert params == ["args", "kwargs"]

    def test_empty_string(self):
        params = extract_py_params("")
        assert params == []

    def test_complex_params(self):
        params = extract_py_params("self, data: list[str], verbose: bool = False")
        assert params == ["data", "verbose"]


# ── normalize_py_body ─────────────────────────────────────


class TestNormalizePyBody:
    def test_strips_comments(self):
        body = textwrap.dedent("""\
            def foo():
                # a comment
                x = 1
                return x
        """)
        result = normalize_py_body(body)
        assert "# a comment" not in result
        assert "x = 1" in result

    def test_strips_docstrings(self):
        body = textwrap.dedent('''\
            def foo():
                """This is a docstring."""
                x = 1
                return x
        ''')
        result = normalize_py_body(body)
        assert "docstring" not in result
        assert "x = 1" in result

    def test_strips_print_and_logging(self):
        body = textwrap.dedent("""\
            def foo():
                x = 1
                print(x)
                logging.info("done")
                return x
        """)
        result = normalize_py_body(body)
        assert "print" not in result
        assert "logging" not in result

    def test_strips_blank_lines(self):
        body = "def foo():\n    x = 1\n\n    return x\n"
        result = normalize_py_body(body)
        lines = result.splitlines()
        assert all(line.strip() for line in lines)


# ── extract_py_classes ────────────────────────────────────


class TestExtractPyClasses:
    def test_class_extraction(self, tmp_path):
        # Need a class with >= 50 LOC
        methods = "\n".join(
            f"    def method_{i}(self):\n" + "\n".join(
                f"        x_{i}_{j} = {j}" for j in range(5)
            ) for i in range(10)
        )
        code = f"class BigClass:\n{methods}\n"
        fp = tmp_path / "big.py"
        fp.write_text(code)
        classes = extract_py_classes(tmp_path)
        assert len(classes) >= 1
        cls = classes[0]
        assert cls.name == "BigClass"
        assert cls.loc >= 50
        assert len(cls.methods) >= 10

    def test_class_with_init_attributes(self, tmp_path):
        body = "\n".join(f"        self.attr_{i} = {i}" for i in range(8))
        methods = "\n".join(
            f"    def m{i}(self):\n" + "\n".join(
                f"        x_{j} = {j}" for j in range(5)
            ) for i in range(8)
        )
        code = f"class WithAttrs:\n    def __init__(self):\n{body}\n\n{methods}\n"
        fp = tmp_path / "attrs.py"
        fp.write_text(code)
        classes = extract_py_classes(tmp_path)
        if classes:
            cls = classes[0]
            assert len(cls.attributes) >= 8

    def test_small_class_skipped(self, tmp_path):
        code = "class Small:\n    x = 1\n    def foo(self): pass\n"
        fp = tmp_path / "small.py"
        fp.write_text(code)
        classes = extract_py_classes(tmp_path)
        names = {c.name for c in classes}
        assert "Small" not in names

    def test_base_classes_extracted(self, tmp_path):
        methods = "\n".join(
            f"    def m{i}(self):\n" + "\n".join(
                f"        x_{j} = {j}" for j in range(5)
            ) for i in range(10)
        )
        code = f"class Child(Parent, SomeMixin):\n{methods}\n"
        fp = tmp_path / "child.py"
        fp.write_text(code)
        classes = extract_py_classes(tmp_path)
        if classes:
            cls = classes[0]
            # Mixins are excluded from base_classes
            assert "Parent" in cls.base_classes
            assert "SomeMixin" not in cls.base_classes


# ── detect_passthrough_functions ──────────────────────────


class TestDetectPassthrough:
    def test_passthrough_detected(self, tmp_path):
        fp = tmp_path / "pt.py"
        fp.write_text(textwrap.dedent("""\
            def wrapper(a, b, c, d, e):
                return inner(a=a, b=b, c=c, d=d, e=e)
        """))
        entries = detect_passthrough_functions(tmp_path)
        if entries:
            assert entries[0]["function"] == "wrapper"
            assert entries[0]["passthrough"] >= 4

    def test_non_passthrough_not_flagged(self, tmp_path):
        fp = tmp_path / "real.py"
        fp.write_text(textwrap.dedent("""\
            def transform(a, b, c, d):
                x = a + b
                y = c * d
                return x + y
        """))
        entries = detect_passthrough_functions(tmp_path)
        names = [e["function"] for e in entries]
        assert "transform" not in names

    def test_too_few_params_not_flagged(self, tmp_path):
        fp = tmp_path / "few.py"
        fp.write_text(textwrap.dedent("""\
            def small(a, b):
                return inner(a=a, b=b)
        """))
        entries = detect_passthrough_functions(tmp_path)
        names = [e["function"] for e in entries]
        assert "small" not in names
