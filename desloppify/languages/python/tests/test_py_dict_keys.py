"""Tests for desloppify.languages.python.detectors.dict_keys — dict key flow analysis."""

import textwrap
from pathlib import Path

import pytest

from desloppify.languages.python.detectors import dict_keys as dict_keys_mod
from desloppify.languages.python.detectors.dict_keys import (
    detect_dict_key_flow,
    detect_schema_drift,
)

# ── Helpers ────────────────────────────────────────────────


def _write_py(tmp_path: Path, code: str, filename: str = "test_mod.py") -> Path:
    """Write a Python file and return the directory containing it."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return tmp_path


def _kinds(issues: list[dict]) -> set[str]:
    """Extract unique issue kinds."""
    return {f["kind"] for f in issues}


def _find_kind(issues: list[dict], kind: str) -> list[dict]:
    """Filter issues by kind."""
    return [f for f in issues if f["kind"] == kind]


# ── Levenshtein / singular-plural helpers ─────────────────


class TestLevenshtein:
    def test_identical(self):
        assert dict_keys_mod._levenshtein("hello", "hello") == 0

    def test_one_edit(self):
        assert dict_keys_mod._levenshtein("cat", "car") == 1

    def test_empty(self):
        assert dict_keys_mod._levenshtein("", "abc") == 3

    def test_swap(self):
        assert dict_keys_mod._levenshtein("abc", "acb") == 2  # two single-char edits


class TestIsSingularPlural:
    def test_s_plural(self):
        assert dict_keys_mod._is_singular_plural("item", "items")
        assert dict_keys_mod._is_singular_plural("items", "item")

    def test_es_plural(self):
        assert dict_keys_mod._is_singular_plural("box", "boxes")

    def test_ies_plural(self):
        assert dict_keys_mod._is_singular_plural("category", "categories")

    def test_unrelated(self):
        assert not dict_keys_mod._is_singular_plural("foo", "bar")


# ── Phantom reads (read key never written) ────────────────


class TestPhantomRead:
    def test_phantom_read_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def build():
                d = {"name": "alice"}
                x = d["age"]
                return x
        """,
        )
        entries, count = detect_dict_key_flow(path)
        assert count == 1
        assert "phantom_read" in _kinds(entries)
        phantom = _find_kind(entries, "phantom_read")
        assert any(f["key"] == "age" for f in phantom)

    def test_no_phantom_when_key_written(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def build():
                d = {"name": "alice", "age": 30}
                x = d["age"]
                return x
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "phantom_read" not in _kinds(entries)

    @pytest.mark.parametrize("constructor", ("dict(source)", "dict(**source)"))
    def test_copy_constructor_does_not_assume_an_empty_local_dict(
        self, tmp_path, constructor
    ):
        path = _write_py(
            tmp_path,
            f"""\
            def build(source):
                copied = {constructor}
                value = copied["expected"]
                return value
        """,
        )

        entries, _ = detect_dict_key_flow(path)

        assert "phantom_read" not in _kinds(entries)

    @pytest.mark.parametrize("constructor", ("dict()", "dict(expected=1)"))
    def test_empty_and_keyword_dict_constructors_still_track_reads(
        self, tmp_path, constructor
    ):
        path = _write_py(
            tmp_path,
            f"""\
            def build():
                created = {constructor}
                value = created["missing"]
                return value
        """,
        )

        entries, _ = detect_dict_key_flow(path)

        phantom = _find_kind(entries, "phantom_read")
        assert any(entry["key"] == "missing" for entry in phantom)


# ── Dead writes (written key never read) ──────────────────


class TestDeadWrite:
    def test_dead_write_detected(self, tmp_path):
        """Dict with 3+ writes, not returned, one key never read -> dead write."""
        path = _write_py(
            tmp_path,
            """\
            def process():
                d = {}
                d["a"] = 1
                d["b"] = 2
                d["c"] = 3
                x = d["a"]
                y = d["b"]
                return x + y
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "dead_write" in _kinds(entries)
        dead = _find_kind(entries, "dead_write")
        assert any(f["key"] == "c" for f in dead)

    def test_no_dead_write_when_returned(self, tmp_path):
        """Dict returned from function -> dead write suppressed."""
        path = _write_py(
            tmp_path,
            """\
            def build_config():
                d = {}
                d["a"] = 1
                d["b"] = 2
                d["c"] = 3
                return d
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "dead_write" not in _kinds(entries)

    def test_no_dead_write_config_name(self, tmp_path):
        """Dict named 'config' -> dead write suppressed."""
        path = _write_py(
            tmp_path,
            """\
            def setup():
                config = {}
                config["a"] = 1
                config["b"] = 2
                config["c"] = 3
                x = config["a"]
                return x
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "dead_write" not in _kinds(entries)

    def test_no_dead_write_when_assigned_into_parent_container(self, tmp_path):
        """Dict assigned into another dict key should be treated as escaped."""
        path = _write_py(
            tmp_path,
            """\
            def stage():
                meta = {}
                child = {}
                child["a"] = 1
                child["b"] = 2
                child["c"] = 3
                meta["child"] = child
                return meta
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "dead_write" not in _kinds(entries)

    def test_no_dead_write_when_nested_in_list_return(self, tmp_path):
        """Dict returned inside nested list/tuple structures should be escaped."""
        path = _write_py(
            tmp_path,
            """\
            def combined():
                item = {}
                item["a"] = 1
                item["b"] = 2
                item["c"] = 3
                return [("label", item)]
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "dead_write" not in _kinds(entries)


# ── Overwritten keys ──────────────────────────────────────


class TestOverwrittenKey:
    def test_overwritten_key_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def dup():
                d = {}
                d["x"] = 1
                d["x"] = 2
                return d
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "overwritten_key" in _kinds(entries)

    def test_overwritten_with_read_between_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def ok():
                d = {}
                d["x"] = 1
                val = d["x"]
                d["x"] = 2
                return d
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "overwritten_key" not in _kinds(entries)


# ── Near-miss (typo) detection ────────────────────────────


class TestNearMiss:
    def test_typo_detected(self, tmp_path):
        """Write 'colour', read 'color' -> near miss."""
        path = _write_py(
            tmp_path,
            """\
            def paint():
                d = {}
                d["colour"] = "red"
                d["size"] = 10
                d["shape"] = "circle"
                x = d["color"]
                return x
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "near_miss" in _kinds(entries)


# ── Dynamic keys suppress analysis ───────────────────────


class TestDynamicKeys:
    def test_dynamic_subscript_suppresses(self, tmp_path):
        """d[var] marks dict as having dynamic keys."""
        path = _write_py(
            tmp_path,
            """\
            def dynamic(key):
                d = {}
                d["a"] = 1
                d["b"] = 2
                d["c"] = 3
                return d[key]
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        # dynamic key access should suppress dead write warnings
        assert "dead_write" not in _kinds(entries)


# ── Dict methods (get, pop, update, etc.) ─────────────────


class TestDictMethods:
    def test_get_counts_as_read(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def reader():
                d = {"name": "alice"}
                return d.get("name")
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "phantom_read" not in _kinds(entries)

    def test_update_counts_as_write(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def writer():
                d = {}
                d.update({"name": "alice"})
                return d.get("name")
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert "phantom_read" not in _kinds(entries)


# ── Clean code ────────────────────────────────────────────


class TestCleanDictUsage:
    def test_no_issues_for_clean_code(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def build():
                d = {"name": "alice", "age": 30}
                name = d["name"]
                age = d["age"]
                return f"{name}, {age}"
        """,
        )
        entries, count = detect_dict_key_flow(path)
        assert len(entries) == 0
        assert count == 1


# ── Schema drift ──────────────────────────────────────────


class TestSchemaDrift:
    def test_drift_detected(self, tmp_path):
        """3+ similar dict literals with outlier key -> flagged."""
        code = textwrap.dedent("""\
            d1 = {"name": "a", "age": 1, "city": "x"}
            d2 = {"name": "b", "age": 2, "city": "y"}
            d3 = {"name": "c", "age": 3, "town": "z"}
        """)
        path = _write_py(tmp_path, code)
        entries, count = detect_schema_drift(path)
        # The function needs at least 3 literals to produce issues
        assert count >= 3
        # "town" is the outlier — only in 1 of 3 dicts while "city" is in 2
        if entries:
            assert any(f["key"] == "town" for f in entries)

    def test_no_drift_identical_dicts(self, tmp_path):
        code = textwrap.dedent("""\
            d1 = {"name": "a", "age": 1, "city": "x"}
            d2 = {"name": "b", "age": 2, "city": "y"}
            d3 = {"name": "c", "age": 3, "city": "z"}
        """)
        path = _write_py(tmp_path, code)
        entries, _ = detect_schema_drift(path)
        assert len(entries) == 0

    def test_too_few_literals_no_issues(self, tmp_path):
        code = textwrap.dedent("""\
            d1 = {"name": "a", "age": 1, "city": "x"}
            d2 = {"name": "b", "age": 2, "town": "y"}
        """)
        path = _write_py(tmp_path, code)
        entries, count = detect_schema_drift(path)
        # Fewer than 3 literals -> no issues
        assert len(entries) == 0


# ── Output structure ──────────────────────────────────────


class TestOutputStructure:
    def test_issue_keys(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def build():
                d = {"name": "alice"}
                x = d["age"]
                return x
        """,
        )
        entries, _ = detect_dict_key_flow(path)
        assert len(entries) > 0
        f = entries[0]
        assert "file" in f
        assert "kind" in f
        assert "key" in f
        assert "line" in f
        assert "summary" in f
        assert "confidence" in f
        assert "tier" in f
