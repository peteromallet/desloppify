"""Review imports must not claim that mechanical detectors ran cleanly."""

from copy import deepcopy

import pytest

from desloppify.intelligence.review import import_holistic_issues, import_review_issues
from desloppify.state import MergeScanOptions, empty_state, make_issue, merge_scan


@pytest.mark.parametrize("import_fn", [import_holistic_issues, import_review_issues])
@pytest.mark.parametrize("detector", ["cycles", "test_coverage"])
@pytest.mark.parametrize("status", ["wontfix", "false_positive", "fixed"])
def test_review_import_preserves_mechanical_disposition(
    import_fn, detector, status, tmp_path
):
    state = empty_state()
    issue = make_issue(
        detector,
        "src/example.ts",
        "accepted",
        tier=3,
        confidence="high",
        summary="Synthetic mechanical finding",
    )
    issue.update(
        lang="typescript",
        status=status,
        note="Manual decision with a specific reason",
        resolved_at="2025-01-01T00:00:00+00:00",
        resolution_attestation={
            "kind": "manual",
            "text": "I checked this finding",
            "attested_at": "2025-01-01T00:00:00+00:00",
            "scan_verified": False,
        },
    )
    state["work_items"][issue["id"]] = issue
    before = deepcopy(issue)

    diff = import_fn({"issues": []}, state, "typescript", project_root=tmp_path)

    assert diff["auto_resolved"] == 0
    assert detector in diff["suspect_detectors"]
    for field in ("status", "note", "resolved_at", "resolution_attestation", "last_seen", "reopen_count"):
        assert state["work_items"][issue["id"]][field] == before[field]

    # A subsequent real detector scan may verify absence normally.
    merge_scan(
        state,
        [],
        options=MergeScanOptions(lang="typescript", potentials={detector: 1}),
    )
    after = state["work_items"][issue["id"]]
    assert after["status"] == status
    assert after["resolved_at"] == before["resolved_at"]
    assert after["resolution_attestation"]["text"] == before["resolution_attestation"]["text"]
    assert after["resolution_attestation"]["scan_verified"] is True


@pytest.mark.parametrize("detector", ["cycles", "test_coverage"])
def test_seen_wontfix_clears_old_scan_verification_without_losing_manual_fields(detector):
    state = empty_state()
    issue = make_issue(
        detector,
        "src/example.ts",
        "accepted",
        tier=3,
        confidence="high",
        summary="Synthetic mechanical finding",
    )
    issue.update(
        lang="typescript",
        status="wontfix",
        note="Manual decision with a specific reason",
        resolved_at="2025-01-01T00:00:00+00:00",
        resolution_attestation={
            "kind": "manual",
            "text": "I checked this finding",
            "attested_at": "2025-01-01T00:00:00+00:00",
            "scan_verified": True,
            "scan_verified_at": "2025-01-02T00:00:00+00:00",
            "scan_verification_text": "Absent from detector output in latest scan",
        },
    )
    state["work_items"][issue["id"]] = issue
    before = deepcopy(issue)
    current = deepcopy(issue)
    current["status"] = "open"

    merge_scan(state, [current], options=MergeScanOptions(lang="typescript"))

    after = state["work_items"][issue["id"]]
    assert after["status"] == "wontfix"
    assert after["note"] == before["note"]
    assert after["resolved_at"] == before["resolved_at"]
    attestation = after["resolution_attestation"]
    for field in ("kind", "text", "attested_at"):
        assert attestation[field] == before["resolution_attestation"][field]
    assert attestation["scan_verified"] is False
    assert "scan_verified_at" not in attestation
    assert "scan_verification_text" not in attestation
