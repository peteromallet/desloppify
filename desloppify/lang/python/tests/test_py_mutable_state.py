"""Tests for desloppify.lang.python.detectors.mutable_state — global mutable config detection."""

import textwrap
from pathlib import Path

import pytest

from desloppify.lang.python.detectors.mutable_state import detect_global_mutable_config


def _write_py(tmp_path: Path, code: str, filename: str = "mod.py") -> Path:
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return tmp_path


def _names(entries: list[dict]) -> set[str]:
    return {e["name"] for e in entries}


class TestBasicDetection:
    def test_list_mutated(self, tmp_path):
        path = _write_py(tmp_path, """\
            items = []

            def add(x):
                items.append(x)
        """)
        entries, count = detect_global_mutable_config(path)
        assert "items" in _names(entries)
        assert count == 1

    def test_dict_mutated(self, tmp_path):
        path = _write_py(tmp_path, """\
            cache = {}

            def store(k, v):
                cache[k] = v
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "cache" in _names(entries)

    def test_none_reassigned_with_global(self, tmp_path):
        """Reassignment with explicit `global` declaration is a real mutation."""
        path = _write_py(tmp_path, """\
            connection = None

            def connect():
                global connection
                connection = get_conn()
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "connection" in _names(entries)

    def test_none_reassigned_without_global_not_flagged(self, tmp_path):
        """Reassignment without `global` creates a local — not a mutation."""
        path = _write_py(tmp_path, """\
            connection = None

            def connect():
                connection = get_conn()
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "connection" not in _names(entries)

    def test_set_mutated(self, tmp_path):
        path = _write_py(tmp_path, """\
            seen = set()

            def mark(x):
                seen.add(x)
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "seen" in _names(entries)


class TestNotFlagged:
    def test_upper_case_constant(self, tmp_path):
        """UPPER_CASE names are constants — not flagged even if mutable."""
        path = _write_py(tmp_path, """\
            DEFAULT_LIST = []

            def reset():
                DEFAULT_LIST.clear()
        """)
        entries, _ = detect_global_mutable_config(path)
        assert len(entries) == 0

    def test_no_mutation(self, tmp_path):
        """Module-level mutable that's only read — not flagged."""
        path = _write_py(tmp_path, """\
            config = {}

            def check():
                return len(config) > 0
        """)
        entries, _ = detect_global_mutable_config(path)
        assert len(entries) == 0

    def test_parameter_shadows_global(self, tmp_path):
        """When a function parameter has the same name as a global — not flagged."""
        path = _write_py(tmp_path, """\
            items = []

            def process(items):
                items.append(1)
        """)
        entries, _ = detect_global_mutable_config(path)
        assert len(entries) == 0


class TestAugAssign:
    def test_plus_equals_with_global(self, tmp_path):
        path = _write_py(tmp_path, """\
            data = []

            def extend(new):
                global data
                data += new
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "data" in _names(entries)

    def test_plus_equals_without_global_not_flagged(self, tmp_path):
        """Augmented assignment without `global` creates a local — not a mutation."""
        path = _write_py(tmp_path, """\
            data = []

            def extend(new):
                data += new
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "data" not in _names(entries)


class TestAnnotated:
    def test_optional_annotation_with_global(self, tmp_path):
        path = _write_py(tmp_path, """\
            from typing import Optional
            _conn: Optional[object] = None

            def init():
                global _conn
                _conn = create()
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "_conn" in _names(entries)

    def test_optional_annotation_without_global_not_flagged(self, tmp_path):
        """Optional annotation without global reassignment — not flagged."""
        path = _write_py(tmp_path, """\
            from typing import Optional
            _conn: Optional[object] = None

            def init():
                _conn = create()
        """)
        entries, _ = detect_global_mutable_config(path)
        assert "_conn" not in _names(entries)


class TestMultipleMutations:
    def test_mutation_count(self, tmp_path):
        path = _write_py(tmp_path, """\
            registry = {}

            def register(k, v):
                registry[k] = v

            def clear():
                registry.clear()
        """)
        entries, _ = detect_global_mutable_config(path)
        assert len(entries) == 1
        assert entries[0]["mutation_count"] >= 2


class TestOutputStructure:
    def test_entry_keys(self, tmp_path):
        path = _write_py(tmp_path, """\
            cache = {}

            def put(k, v):
                cache[k] = v
        """)
        entries, total = detect_global_mutable_config(path)
        assert len(entries) == 1
        e = entries[0]
        assert "file" in e
        assert "name" in e
        assert "line" in e
        assert "mutation_count" in e
        assert "mutation_lines" in e
        assert "summary" in e
        assert "confidence" in e
        assert total == 1
