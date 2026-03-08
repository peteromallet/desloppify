"""Direct coverage tests for holistic error-state cluster builders."""

from __future__ import annotations

from desloppify.intelligence.review.context_holistic._clusters_error_state import (
    _build_error_hotspots,
    _build_mutable_globals,
)


def test_build_error_hotspots_filters_threshold_sorts_and_limits() -> None:
    by_detector = {
        "smells": [
            {"file": "src/a.py", "detail": {"smell_id": "broad_except"}},
            {"file": "src/a.py", "detail": {"smell_id": "silent_except"}},
            {"file": "src/a.py", "detail": {"smell_id": "empty_except"}},
            {"file": "src/b.py", "detail": {"smell_id": "bare_except"}},
            {"file": "src/b.py", "detail": {"smell_id": "bare_except"}},
            {"file": "src/b.py", "detail": {"smell_id": "swallowed_error"}},
            {"file": "src/c.py", "detail": {"smell_id": "broad_except"}},
            {"file": "src/c.py", "detail": {"smell_id": "other_smell"}},
        ]
    }

    for idx in range(25):
        by_detector["smells"].extend(
            [
                {"file": f"src/f{idx}.py", "detail": {"smell_id": "bare_except"}},
                {"file": f"src/f{idx}.py", "detail": {"smell_id": "bare_except"}},
                {"file": f"src/f{idx}.py", "detail": {"smell_id": "bare_except"}},
            ]
        )

    rows = _build_error_hotspots(by_detector)
    assert len(rows) == 20
    assert rows[0]["file"] == "src/a.py"
    assert rows[0]["total"] == 3
    assert rows[0]["broad_except"] == 1
    assert rows[0]["silent_except"] == 1
    assert rows[0]["empty_except"] == 1
    assert all(row["file"] != "src/c.py" for row in rows)


def test_build_mutable_globals_groups_names_and_uses_default_mutation_weight() -> None:
    by_detector = {
        "global_mutable_config": [
            {"file": "src/a.py", "detail": {"name": "_registry", "mutations": 4}},
            {"file": "src/a.py", "detail": {"name": "_registry", "mutations": 2}},
            {"file": "src/a.py", "detail": {"name": "_cache"}},
            {"file": "src/b.py", "detail": {"name": "_state", "mutations": 1}},
            {"file": "", "detail": {"name": "_ignored", "mutations": 100}},
        ]
    }

    rows = _build_mutable_globals(by_detector)
    assert rows == [
        {
            "file": "src/a.py",
            "names": ["_registry", "_cache"],
            "total_mutations": 7,
        },
        {
            "file": "src/b.py",
            "names": ["_state"],
            "total_mutations": 1,
        },
    ]
