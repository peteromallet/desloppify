"""Tests for _triage_coverage filtering to review issues only."""

from __future__ import annotations

from desloppify.app.commands.plan.triage.review_coverage import triage_coverage
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS


def _plan_with_queue(*issue_ids: str, clustered: list[str] | None = None) -> dict:
    """Build a plan with given queue items and optional clustered IDs."""
    plan = empty_plan()
    plan["queue_order"] = list(TRIAGE_STAGE_IDS) + list(issue_ids)
    if clustered:
        plan["clusters"]["test-cluster"] = {
            "name": "test-cluster",
            "issue_ids": list(clustered),
            "description": "Test",
            "action_steps": ["step 1"],
            "auto": False,
        }
    return plan


def _review_ids(*ids: str) -> set[str]:
    """Convenience wrapper to build an open_review_ids set."""
    return set(ids)


class TestTriageCoverage:
    def test_coverage_excludes_non_review_items(self):
        """Non-review queue items (mechanical issues) don't inflate total."""
        plan = _plan_with_queue(
            "review::test.py::naming_issue",
            "review::test.py::coupling_issue",
            "naming-convention::test.py",  # mechanical — should be excluded
            "unused-import::test.py",       # mechanical — should be excluded
            clustered=["review::test.py::naming_issue"],
        )
        organized, total, _ = triage_coverage(
            plan,
            open_review_ids=_review_ids(
                "review::test.py::naming_issue",
                "review::test.py::coupling_issue",
            ),
        )
        assert total == 2  # only review issues
        assert organized == 1

    def test_coverage_counts_review_issues_only(self):
        """Review and concerns issues are correctly counted."""
        plan = _plan_with_queue(
            "review::a.py::issue1",
            "concerns::b.py::issue2",
            "review::c.py::issue3",
            "unused-import::d.py",
            clustered=["review::a.py::issue1", "concerns::b.py::issue2"],
        )
        organized, total, _ = triage_coverage(
            plan,
            open_review_ids=_review_ids(
                "review::a.py::issue1",
                "concerns::b.py::issue2",
                "review::c.py::issue3",
            ),
        )
        assert total == 3  # 2 review + 1 concerns
        assert organized == 2

    def test_coverage_empty_queue(self):
        """Empty queue returns (0, 0, clusters)."""
        plan = _plan_with_queue()  # only triage stage IDs
        organized, total, clusters = triage_coverage(
            plan, open_review_ids=set(),
        )
        assert organized == 0
        assert total == 0
        assert isinstance(clusters, dict)

    def test_coverage_excludes_triage_stages(self):
        """Triage stage IDs are never counted toward review coverage totals."""
        plan = _plan_with_queue("review::test.py::issue1")
        _, total, _ = triage_coverage(
            plan,
            open_review_ids=_review_ids("review::test.py::issue1"),
        )
        assert total == 1  # triage stages excluded

    def test_coverage_uses_provided_ids_not_queue(self):
        """open_review_ids overrides queue_order for total count.

        Simulates a real scenario: queue_order has 1 review item but state
        has 3 open review issues. Coverage should be 2/3 (not 1/1).
        """
        plan = empty_plan()
        # queue_order only has 1 review item
        plan["queue_order"] = [*TRIAGE_STAGE_IDS, "review::a.py::issue1"]
        # But two of the three are clustered
        plan["clusters"]["my-cluster"] = {
            "name": "my-cluster",
            "issue_ids": [
                "review::a.py::issue1",
                "review::b.py::issue2",
            ],
            "description": "Test",
            "action_steps": ["step 1"],
            "auto": False,
        }
        # State has 3 open review issues
        open_ids = _review_ids(
            "review::a.py::issue1",
            "review::b.py::issue2",
            "review::c.py::issue3",
        )
        organized, total, _ = triage_coverage(plan, open_review_ids=open_ids)
        assert total == 3
        assert organized == 2

    def test_coverage_fallback_to_queue_when_no_ids(self):
        """Without open_review_ids, falls back to queue_order logic."""
        plan = _plan_with_queue(
            "review::test.py::issue1",
            "unused-import::test.py",
            clustered=["review::test.py::issue1"],
        )
        # No open_review_ids — uses queue_order
        organized, total, _ = triage_coverage(plan)
        assert total == 1
        assert organized == 1

    def test_coverage_ignores_issue_refs_without_issue_ids(self):
        """Step refs are traceability metadata, not membership."""
        plan = empty_plan()
        plan["queue_order"] = [
            *TRIAGE_STAGE_IDS,
            "review::a.py::issue1",
            "concerns::b.py::issue2",
        ]
        plan["clusters"]["recovered"] = {
            "name": "recovered",
            "issue_ids": [],
            "description": "Recovered cluster",
            "action_steps": [
                {
                    "title": "Fix both",
                    "issue_refs": [
                        "review::a.py::issue1",
                        "concerns::b.py::issue2",
                    ],
                }
            ],
            "auto": False,
        }

        organized, total, _ = triage_coverage(plan)

        assert total == 2
        assert organized == 0
