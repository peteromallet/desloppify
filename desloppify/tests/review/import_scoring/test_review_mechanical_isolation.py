"""Review imports leave mechanical dispositions and fresh assessments intact."""

from copy import deepcopy

import pytest

from desloppify.intelligence.review import import_holistic_issues, import_review_issues
from desloppify.state import ensure_state_defaults
from desloppify.tests.state.test_state import _make_raw_issue


@pytest.mark.parametrize("import_review", [import_holistic_issues, import_review_issues])
@pytest.mark.parametrize("status", ["fixed", "wontfix", "false_positive"])
def test_review_import_does_not_verify_mechanical_issue(
    import_review, status, empty_state, tmp_path
):
    issue = _make_raw_issue(
        "structural::a.ts::large_file", detector="structural", file="a.ts", status=status,
        lang="typescript",
    )
    issue["resolution_attestation"] = {
        "kind": "manual", "text": "reviewed", "scan_verified": False,
    }
    empty_state["work_items"][issue["id"]] = issue
    ensure_state_defaults(empty_state)
    before = deepcopy(issue)

    diff = import_review(
        {"issues": [], "assessments": {"design_coherence": 81}},
        empty_state, "typescript", project_root=tmp_path,
    )

    assert diff["auto_resolved"] == 0
    assert issue == before
    assessment = empty_state["subjective_assessments"]["design_coherence"]
    assert assessment["score"] == 81
    assert not assessment.get("needs_review_refresh")
    assert "stale_since" not in assessment
