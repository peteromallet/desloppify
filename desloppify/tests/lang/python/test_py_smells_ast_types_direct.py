"""Direct tests for AST smell typed models and merge helpers."""

from __future__ import annotations

from desloppify.languages.python.detectors.smells_ast._types import (
    dedupe_smell_matches,
    merge_smell_matches,
)


def test_dedupe_smell_matches_is_sorted_and_unique():
    matches = [
        {"file": "b.py", "line": 2, "content": "z"},
        {"file": "a.py", "line": 3, "content": "x"},
        {"file": "a.py", "line": 1, "content": "y"},
        {"file": "a.py", "line": 3, "content": "x"},
    ]

    deduped = dedupe_smell_matches(matches)
    assert deduped == [
        {"file": "a.py", "line": 1, "content": "y"},
        {"file": "a.py", "line": 3, "content": "x"},
        {"file": "b.py", "line": 2, "content": "z"},
    ]


def test_merge_smell_matches_avoids_duplicate_entries():
    smell_counts = {
        "dead_function": [
            {"file": "x.py", "line": 10, "content": "a"},
        ]
    }

    merge_smell_matches(
        smell_counts,
        "dead_function",
        [
            {"file": "x.py", "line": 10, "content": "a"},
            {"file": "x.py", "line": 8, "content": "b"},
        ],
    )

    assert smell_counts["dead_function"] == [
        {"file": "x.py", "line": 10, "content": "a"},
        {"file": "x.py", "line": 8, "content": "b"},
    ]
