"""Tests for scope_matches() hash suffix matching (#163)."""

from __future__ import annotations

from desloppify.engine._work_queue.helpers import scope_matches


def _item(*, id: str, detector: str = "smells", file: str = "a.py") -> dict:
    return {
        "id": id,
        "detector": detector,
        "file": file,
        "summary": "test finding",
        "detail": {},
        "kind": "",
    }


class TestHashSuffixMatching:
    def test_hash_suffix_matches(self):
        item = _item(id="smells::a.py::1497da0b")
        assert scope_matches(item, "1497da0b") is True

    def test_hash_suffix_no_match(self):
        item = _item(id="smells::a.py::1497da0b")
        assert scope_matches(item, "deadbeef") is False

    def test_hash_suffix_case_insensitive(self):
        item = _item(id="smells::a.py::1497da0b")
        assert scope_matches(item, "1497DA0B") is True

    def test_short_hex_not_treated_as_hash(self):
        """7-char hex falls through to other matching (not hash suffix)."""
        item = _item(id="smells::a.py::1497da0")
        # 7-char hex is too short for hash matching
        assert scope_matches(item, "1497da0") is False

    def test_detector_name_still_works(self):
        item = _item(id="smells::a.py::abcdef01", detector="smells")
        assert scope_matches(item, "smells") is True
