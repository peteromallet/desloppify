"""Direct coverage tests for finding factory helpers."""

from __future__ import annotations

from desloppify.languages.framework.finding_factories import (
    make_single_use_findings,
    make_unused_findings,
)


def test_make_unused_findings_shapes_entries():
    logs: list[str] = []
    entries = [
        {"file": "src/a.py", "name": "x", "line": 3, "category": "imports"},
        {"file": "src/b.py", "name": "y", "line": 6, "category": "vars"},
    ]
    findings = make_unused_findings(entries, logs.append)

    assert len(findings) == 2
    assert findings[0]["tier"] == 1
    assert findings[1]["tier"] == 2
    assert findings[0]["detector"] == "unused"
    assert logs and "2 findings" in logs[-1]


def test_make_single_use_findings_applies_loc_filtering():
    logs: list[str] = []
    entries = [
        {"file": "src/low.py", "loc": 80, "sole_importer": "src/app.py"},
        {"file": "src/high.py", "loc": 320, "sole_importer": "src/app.py"},
    ]

    def _area(path: str) -> str:
        if "high.py" in path:
            return "feature"
        return "app"

    findings = make_single_use_findings(entries, get_area=_area, stderr_fn=logs.append)

    assert len(findings) == 1
    assert findings[0]["file"] == "src/high.py"
    assert findings[0]["detector"] == "single_use"
    assert logs and "single-use" in logs[-1]
