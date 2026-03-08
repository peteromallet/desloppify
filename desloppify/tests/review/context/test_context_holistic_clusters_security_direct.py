"""Direct coverage tests for holistic security cluster builders."""

from __future__ import annotations

from collections import Counter

from desloppify.intelligence.review.context_holistic._clusters_security import (
    _build_security_hotspots,
    _build_signal_density,
    _build_systemic_patterns,
)


def test_build_security_hotspots_applies_threshold_and_sort_order() -> None:
    by_detector = {
        "security": [
            {"file": "src/a.py", "detail": {"severity": "high"}},
            {"file": "src/a.py", "detail": {"severity": "high"}},
            {"file": "src/a.py", "detail": {"severity": "medium"}},
            {"file": "src/b.py", "detail": {"severity": "high"}},
            {"file": "src/b.py", "detail": {"severity": "medium"}},
            {"file": "src/b.py", "detail": {"severity": "medium"}},
            {"file": "src/c.py", "detail": {"severity": "high"}},
            {"file": "", "detail": {"severity": "high"}},
        ]
    }

    rows = _build_security_hotspots(by_detector)
    assert rows == [
        {"file": "src/a.py", "high_severity": 2, "medium_severity": 1, "total": 3},
        {"file": "src/b.py", "high_severity": 1, "medium_severity": 2, "total": 3},
    ]


def test_build_signal_density_counts_distinct_detectors_and_limits() -> None:
    by_file: dict[str, list[dict]] = {
        "src/a.py": [
            {"detector": "smells"},
            {"detector": "security"},
            {"detector": "security"},
        ],
        "src/b.py": [
            {"detector": "smells"},
        ],
    }

    for idx in range(19):
        by_file[f"src/f{idx}.py"] = [
            {"detector": "smells"},
            {"detector": "structural"},
            {"detector": "coupling"},
        ]

    rows = _build_signal_density(by_file)
    assert len(rows) == 20
    assert rows[0]["detector_count"] == 3
    assert rows[0]["issue_count"] == 3
    assert {"file": "src/a.py", "detector_count": 2, "issue_count": 3, "detectors": ["security", "smells"]} in rows
    assert all(row["file"] != "src/b.py" for row in rows)


def test_build_systemic_patterns_enforces_file_threshold_and_hotspots() -> None:
    smell_counter = Counter(
        {
            "broad_except": 9,
            "deferred_import": 6,
            "tiny_pattern": 4,
        }
    )
    smell_files = {
        "broad_except": [
            "a.py",
            "a.py",
            "b.py",
            "c.py",
            "d.py",
            "e.py",
            "f.py",
            "g.py",
            "h.py",
        ],
        "deferred_import": ["x.py", "y.py", "z.py", "u.py", "v.py", "v.py"],
        "tiny_pattern": ["m.py", "n.py", "o.py", "p.py"],
    }

    rows = _build_systemic_patterns(smell_counter, smell_files)
    assert rows[0]["pattern"] == "broad_except"
    assert rows[0]["file_count"] == 8
    assert rows[0]["hotspots"][0] == "a.py (2)"
    assert rows[1]["pattern"] == "deferred_import"
    assert rows[1]["file_count"] == 5
    assert all(row["pattern"] != "tiny_pattern" for row in rows)
