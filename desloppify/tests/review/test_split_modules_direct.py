"""Direct coverage tests for review/issue split modules."""

from __future__ import annotations

import pytest

from desloppify.core.issues_render import finding_weight, render_issue_detail
from desloppify.intelligence.review.importing.holistic import (
    parse_holistic_import_payload,
)
from desloppify.intelligence.review.importing.per_file import (
    parse_per_file_import_payload,
)
from desloppify.intelligence.review.importing.shared import (
    extract_reviewed_files,
    store_assessments,
)
from desloppify.intelligence.review.prepare_internal.remediation_engine import (
    empty_plan,
)


def test_import_split_extract_helpers_require_object_payloads():
    with pytest.raises(ValueError):
        parse_per_file_import_payload([{"summary": "x"}])  # type: ignore[arg-type]

    findings2, assessments2, reviewed_files = parse_holistic_import_payload(
        {
            "findings": [{"summary": "y"}],
            "assessments": {"naming_quality": 88},
            "reviewed_files": ["a.py"],
        }
    )
    assert findings2 == [{"summary": "y"}]
    assert assessments2 == {"naming_quality": 88}
    assert reviewed_files == ["a.py"]


def test_import_shared_extract_reviewed_files_deduplicates():
    reviewed = extract_reviewed_files({"reviewed_files": ["a.py", "", "a.py", "b.py"]})
    assert reviewed == ["a.py", "b.py"]


def test_store_assessments_keeps_holistic_precedence():
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 90,
                "source": "holistic",
                "assessed_at": "2026-01-01",
            }
        }
    }
    store_assessments(state, {"naming_quality": 50}, source="per_file")
    assert state["subjective_assessments"]["naming_quality"]["score"] == 90


def test_remediation_empty_plan_renders_scores_block():
    state = {
        "overall_score": 95.1,
        "objective_score": 96.2,
        "strict_score": 95.1,
        "version": 1,
        "created": "2026-01-01T00:00:00+00:00",
    }
    content = empty_plan(state, "python")
    assert "Holistic Review: Remediation Plan" in content
    assert (
        "desloppify --lang python review --prepare --holistic --path <src>" in content
    )


def test_issues_render_builds_markdown_payload():
    finding = {
        "id": "review::src/foo.py::logic_clarity::abc12345",
        "summary": "Simplify conditional chain",
        "confidence": "medium",
        "detail": {
            "dimension": "logic_clarity",
            "evidence": ["deeply nested conditionals"],
            "suggestion": "Extract guard clauses",
            "reasoning": "Improves readability",
            "evidence_lines": ["src/foo.py:10"],
        },
        "file": "src/foo.py",
    }
    weight, impact, _ = finding_weight(finding)
    assert weight > 0
    assert impact > 0

    rendered = render_issue_detail(finding, "python")
    assert "Suggested Fix" in rendered
    assert "desloppify --lang python resolve fixed" in rendered
