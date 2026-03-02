"""Tests for regex-based Python code smell detectors."""

import textwrap
from pathlib import Path

from desloppify.languages.python.detectors.smells import detect_smells

# ── Helpers ────────────────────────────────────────────────


def _write_py(tmp_path: Path, code: str, filename: str = "test_mod.py") -> Path:
    """Write a Python file and return the directory containing it."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return tmp_path


def _smell_ids(entries: list[dict]) -> set[str]:
    """Extract the set of smell IDs from detect_smells output."""
    return {e["id"] for e in entries}


# ── eval/exec ─────────────────────────────────────────────


class TestEvalExec:
    def test_eval_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            result = eval("1 + 2")
        """,
        )
        entries, _ = detect_smells(path)
        assert "eval_exec" in _smell_ids(entries)

    def test_exec_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            exec("print('hello')")
        """,
        )
        entries, _ = detect_smells(path)
        assert "eval_exec" in _smell_ids(entries)

    def test_method_eval_not_flagged(self, tmp_path):
        """obj.eval() should not be flagged (lookbehind prevents it)."""
        path = _write_py(
            tmp_path,
            """\
            model.eval()
        """,
        )
        entries, _ = detect_smells(path)
        assert "eval_exec" not in _smell_ids(entries)


# ── todo/fixme ────────────────────────────────────────────


class TestTodoFixme:
    def test_todo(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            # TODO: fix this later
            x = 1
        """,
        )
        entries, _ = detect_smells(path)
        assert "todo_fixme" in _smell_ids(entries)

    def test_fixme(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            # FIXME: broken
            x = 1
        """,
        )
        entries, _ = detect_smells(path)
        assert "todo_fixme" in _smell_ids(entries)


# ── hardcoded URLs ────────────────────────────────────────


class TestHardcodedUrl:
    def test_hardcoded_url_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            url = fetch("https://api.example.com/data")
        """,
        )
        entries, _ = detect_smells(path)
        assert "hardcoded_url" in _smell_ids(entries)

    def test_constant_url_suppressed(self, tmp_path):
        """UPPER_CASE = 'http://...' is suppressed."""
        path = _write_py(
            tmp_path,
            """\
            BASE_URL = "https://api.example.com"
        """,
        )
        entries, _ = detect_smells(path)
        assert "hardcoded_url" not in _smell_ids(entries)


# ── magic numbers ─────────────────────────────────────────


class TestMagicNumber:
    def test_magic_number(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            if count >= 10000:
                pass
        """,
        )
        entries, _ = detect_smells(path)
        assert "magic_number" in _smell_ids(entries)


# ── regex backtrack ───────────────────────────────────────


class TestRegexBacktrack:
    def test_nested_quantifiers(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import re
            pat = re.compile(r"(a+)+b")
        """,
        )
        entries, _ = detect_smells(path)
        assert "regex_backtrack" in _smell_ids(entries)

    def test_safe_regex_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import re
            pat = re.compile(r"[a-z]+\\d+")
        """,
        )
        entries, _ = detect_smells(path)
        assert "regex_backtrack" not in _smell_ids(entries)


# ── naive comment strip ──────────────────────────────────


class TestNaiveCommentStrip:
    def test_re_sub_comment_strip(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import re
            cleaned = re.sub(r"//[^\\n]*", "", text)
        """,
        )
        entries, _ = detect_smells(path)
        assert "naive_comment_strip" in _smell_ids(entries)
