"""Triage accepts shared work only when its steps account for each issue."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.app.commands.plan.triage.runner.stage_validation import validate_stage


def _shared_service_plan(issue_count: int) -> tuple[dict, dict]:
    issue_ids = [f"review::src/service.php::issue_{index}" for index in range(issue_count)]
    plan = {
        "clusters": {
            "shared-service": {
                "issue_ids": issue_ids,
                "description": "Centralize the service's validation before its only write.",
                "action_steps": [
                    {
                        "title": "Unify validation at the service boundary",
                        "detail": (
                            "Update src/service.php in Service::save to validate all inputs "
                            "before the repository write and remove the duplicated branches."
                        ),
                        "effort": "small",
                        "issue_refs": issue_ids.copy(),
                    }
                ],
            }
        },
        "epic_triage_meta": {
            "triage_stages": {
                "reflect": {"timestamp": "2026-01-01T00:00:00Z"},
                "organize": {
                    "report": (
                        "Organized all service validation issues into shared-service. "
                        "One shared implementation change covers every member; perform it "
                        "before later callers depend on the corrected boundary."
                    )
                },
            }
        },
        "execution_log": [
            {"timestamp": "2026-01-02T00:00:00Z", "action": "cluster_create"},
            {"timestamp": "2026-01-02T00:00:01Z", "action": "cluster_add"},
            {"timestamp": "2026-01-02T00:00:02Z", "action": "cluster_update"},
        ],
    }
    state = {
        "issues": {
            issue_id: {"status": "open", "detector": "review", "file": "src/service.php"}
            for issue_id in issue_ids
        }
    }
    return plan, state


@pytest.mark.parametrize("issue_count", [2, 3, 4])
def test_organize_accepts_one_step_covering_a_small_shared_cluster(
    tmp_path: Path,
    issue_count: int,
) -> None:
    plan, state = _shared_service_plan(issue_count)

    ok, message = validate_stage("organize", plan, state, tmp_path)

    assert ok, message


@pytest.mark.parametrize("coverage", ["none", "partial", "duplicate-and-foreign"])
def test_organize_rejects_consolidated_steps_without_full_member_coverage(
    tmp_path: Path,
    coverage: str,
) -> None:
    plan, state = _shared_service_plan(3)
    cluster = plan["clusters"]["shared-service"]
    first_id = cluster["issue_ids"][0]
    references = {
        "none": [],
        "partial": cluster["issue_ids"][:2],
        "duplicate-and-foreign": [first_id, first_id, "review::src/other.php::other"],
    }
    cluster["action_steps"][0]["issue_refs"] = references[coverage]

    ok, message = validate_stage("organize", plan, state, tmp_path)

    assert not ok
    assert "Unenriched clusters: shared-service" == message


def test_organize_combines_coverage_from_multiple_shared_steps(tmp_path: Path) -> None:
    plan, state = _shared_service_plan(4)
    cluster = plan["clusters"]["shared-service"]
    step = cluster["action_steps"][0]
    cluster["action_steps"] = [
        {**step, "issue_refs": cluster["issue_ids"][:2]},
        {**step, "title": "Update the calling boundary", "issue_refs": cluster["issue_ids"][2:]},
    ]

    ok, message = validate_stage("organize", plan, state, tmp_path)

    assert ok, message


def test_enrich_accepts_a_complete_consolidated_plan(tmp_path: Path) -> None:
    plan, state = _shared_service_plan(3)
    plan["epic_triage_meta"]["triage_stages"]["enrich"] = {"report": "Detailed shared-service."}
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.php").write_text("<?php class Service {}\n")

    ok, message = validate_stage("enrich", plan, state, tmp_path)

    assert ok, message


@pytest.mark.parametrize(
    ("field", "value", "expected_message"),
    [
        ("detail", "", "detail"),
        ("effort", "", "effort"),
        ("detail", "Update src/missing.php in Service::save to validate all inputs before its only write.", "file path"),
    ],
)
def test_consolidated_coverage_does_not_bypass_enrich_quality(
    tmp_path: Path,
    field: str,
    value: str,
    expected_message: str,
) -> None:
    plan, state = _shared_service_plan(3)
    plan["epic_triage_meta"]["triage_stages"]["enrich"] = {"report": "Detailed shared-service."}
    plan["clusters"]["shared-service"]["action_steps"][0][field] = value
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.php").write_text("<?php class Service {}\n")

    ok, message = validate_stage("enrich", plan, state, tmp_path)

    assert not ok
    assert expected_message in message
