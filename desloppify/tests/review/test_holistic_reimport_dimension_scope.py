"""Holistic imports supersede findings only within their dimension coverage."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from desloppify.app.commands.review.importing.parse import (
    ImportParseOptions,
    _parse_and_validate_import,
)
from desloppify.base.runtime_state import runtime_scope
from desloppify.intelligence.review.importing.holistic import import_holistic_issues
from desloppify.intelligence.review.importing.holistic_issue_flow import (
    auto_resolve_stale_holistic,
)
from desloppify.state import empty_state

_NOW = "2026-01-01T00:00:00+00:00"
_SWEEP_FLAGS = pytest.mark.parametrize(
    "full_sweep", [True, False, None], ids=["full-sweep", "partial-sweep", "omitted"]
)


def _finding(dimension: str, identifier: str) -> dict:
    return {
        "dimension": dimension,
        "identifier": identifier,
        "summary": f"Synthetic defect {identifier}",
        "confidence": "high",
        "related_files": ["src/alpha.py", "src/beta.py"],
        "evidence": ["Synthetic fixture evidence."],
        "suggestion": "Apply the synthetic correction.",
    }


def _import(payload: dict, state: dict, project_root: Path) -> dict:
    path = project_root / "review-import.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with runtime_scope() as runtime:
        runtime.project_root = project_root
        normalized, errors = _parse_and_validate_import(
            str(path),
            options=ImportParseOptions(
                lang_name="python",
                trusted_assessment_source=True,
                trusted_assessment_label="synthetic fixture",
            ),
        )
        assert errors == []
        assert normalized is not None
        if payload.get("assessments"):
            assert normalized["_assessment_policy"]["mode"] == "trusted_internal"
        return import_holistic_issues(
            normalized,
            state,
            "python",
            project_root=project_root,
            utc_now_fn=lambda: _NOW,
        )


def _seed_state(project_root: Path, *, retained: bool = False) -> dict:
    state = empty_state()
    findings = [
        _finding("naming_quality", "old_naming"),
        _finding("error_consistency", "old_errors"),
    ]
    if retained:
        findings.append(_finding("naming_quality", "retained_naming"))
    _import(
        {
            "issues": findings,
            "assessments": {"naming_quality": 88.0, "error_consistency": 88.0},
        },
        state,
        project_root,
    )
    return state


def _record(state: dict, identifier: str) -> dict:
    return next(
        issue
        for issue_id, issue in state["work_items"].items()
        if issue_id.endswith(f"::{identifier}")
    )


def _scope(full_sweep: bool | None, dimensions: list[str]) -> dict:
    scope: dict = {"imported_dimensions": dimensions}
    if full_sweep is not None:
        scope["full_sweep_included"] = full_sweep
    return scope


@_SWEEP_FLAGS
def test_partial_trusted_import_preserves_unrelated_findings_and_assessments(
    tmp_path: Path, full_sweep: bool | None,
) -> None:
    state = _seed_state(tmp_path, retained=True)
    unrelated = deepcopy(_record(state, "old_errors"))
    assessments = deepcopy(state["subjective_assessments"])

    diff = _import(
        {
            "issues": [
                _finding("naming_quality", "retained_naming"),
                _finding("naming_quality", "new_naming"),
            ],
            "assessments": {"naming_quality": 88.0},
            "review_scope": _scope(full_sweep, ["naming_quality"]),
        },
        state,
        tmp_path,
    )

    assert diff["auto_resolved"] == 1
    assert _record(state, "old_naming")["status"] == "fixed"
    assert _record(state, "retained_naming")["status"] == "open"
    assert _record(state, "new_naming")["status"] == "open"
    assert _record(state, "old_errors") == unrelated
    assert state["subjective_assessments"] == assessments


@_SWEEP_FLAGS
def test_zero_finding_assessment_only_supersedes_its_dimension(
    tmp_path: Path, full_sweep: bool | None,
) -> None:
    state = _seed_state(tmp_path)
    unrelated = deepcopy(_record(state, "old_errors"))
    assessments = deepcopy(state["subjective_assessments"])

    diff = _import(
        {
            "issues": [],
            "assessments": {"naming_quality": 88.0},
            "dimension_notes": {
                "naming_quality": {"evidence": ["Synthetic review found no new defect."]},
            },
            "review_scope": _scope(full_sweep, []),
        },
        state,
        tmp_path,
    )

    assert diff["auto_resolved"] == 1
    assert _record(state, "old_naming")["status"] == "fixed"
    assert _record(state, "old_errors") == unrelated
    assert state["subjective_assessments"] == assessments


@_SWEEP_FLAGS
def test_empty_dimension_scope_preserves_existing_evidence(
    tmp_path: Path, full_sweep: bool | None,
) -> None:
    state = _seed_state(tmp_path)
    findings = deepcopy(state["work_items"])
    assessments = deepcopy(state["subjective_assessments"])

    diff = _import(
        {"issues": [], "review_scope": _scope(full_sweep, [])},
        state,
        tmp_path,
    )

    assert diff["auto_resolved"] == 0
    assert state["work_items"] == findings
    assert state["subjective_assessments"] == assessments


def test_comprehensive_explicit_dimension_scope_resolves_all_superseded_findings(
    tmp_path: Path,
) -> None:
    state = _seed_state(tmp_path)
    assessments = deepcopy(state["subjective_assessments"])

    diff = _import(
        {
            "issues": [],
            "review_scope": _scope(True, ["Naming Quality", "error-consistency"]),
        },
        state,
        tmp_path,
    )

    assert diff["auto_resolved"] == 2
    assert _record(state, "old_naming")["status"] == "fixed"
    assert _record(state, "old_errors")["status"] == "fixed"
    assert state["subjective_assessments"] == assessments


@pytest.mark.parametrize("detector", ["review", "concerns"])
def test_reconciliation_normalizes_covered_and_existing_dimensions(detector: str) -> None:
    state = {
        "work_items": {
            "covered": {
                "id": "covered", "detector": detector, "status": "open",
                "detail": {"holistic": True, "dimension": "Naming Quality"},
            },
            "unrelated": {
                "id": "unrelated", "detector": detector, "status": "open",
                "detail": {"holistic": True, "dimension": "error-consistency"},
            },
        },
    }
    unrelated = deepcopy(state["work_items"]["unrelated"])
    diff = {"auto_resolved": 0}

    auto_resolve_stale_holistic(
        state,
        set(),
        diff,
        lambda: _NOW,
        imported_dimensions={"naming-quality"},
        full_sweep_included=True,
    )

    assert diff["auto_resolved"] == 1
    assert state["work_items"]["covered"]["status"] == "fixed"
    assert state["work_items"]["unrelated"] == unrelated
