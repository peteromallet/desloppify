"""A review import is not evidence that a mechanical detector ran (#809)."""

from copy import deepcopy

import pytest

from desloppify.engine._state.merge_issues import verify_disappeared
from desloppify.state import MergeScanOptions, empty_state, merge_scan
from desloppify.tests.state.test_state import _make_raw_issue


@pytest.mark.parametrize("status", ["fixed", "wontfix", "false_positive"])
@pytest.mark.parametrize("scan_path", [".", "other"])
@pytest.mark.parametrize("confirmed_detectors", [None, set(), {"review"}])
def test_manual_resolution_requires_detector_evidence(
    status, scan_path, confirmed_detectors
):
    issue = _make_raw_issue(
        "smells::src/a.py::item", detector="smells", file="src/a.py", status=status
    )
    issue["note"] = "Manual disposition"
    issue["resolution_attestation"] = {
        "kind": "manual", "text": "reviewed", "scan_verified": False,
    }
    existing = {issue["id"]: issue}
    before = deepcopy(existing)

    result = verify_disappeared(
        existing, set(), set(), "2026-03-14T00:00:00+00:00",
        lang=None, scan_path=scan_path, confirmed_detectors=confirmed_detectors,
    )

    assert result == (0, 0, 0, set())
    assert existing == before


@pytest.mark.parametrize("status", ["fixed", "wontfix", "false_positive"])
@pytest.mark.parametrize("evidence", ["potentials", "output"])
def test_manual_resolution_is_verified_when_detector_ran(status, evidence):
    state = empty_state()
    issue = _make_raw_issue(
        "smells::a.py::item", detector="smells", file="a.py", status=status
    )
    state["work_items"][issue["id"]] = issue
    output = []
    options = MergeScanOptions(potentials={"smells": 10})
    if evidence == "output":
        output = [_make_raw_issue("smells::b.py::item", detector="smells", file="b.py")]
        options = MergeScanOptions()

    diff = merge_scan(state, output, options)

    assert diff["auto_resolved"] == 1
    assert issue["status"] == status
    assert issue["resolution_attestation"]["scan_verified"] is True


def test_force_resolve_does_not_invent_detector_evidence():
    state = empty_state()
    issue = _make_raw_issue("smells::a.py::item", detector="smells", status="fixed")
    state["work_items"][issue["id"]] = issue

    diff = merge_scan(state, [], MergeScanOptions(force_resolve=True, potentials={"review": 1}))

    assert diff["auto_resolved"] == 0
    assert "resolution_attestation" not in issue
