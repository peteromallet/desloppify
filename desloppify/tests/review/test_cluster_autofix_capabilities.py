"""Cluster advice must preserve per-language fixer availability checks."""

from __future__ import annotations

import pytest

from desloppify.engine._work_queue.plan_order import collapse_clusters
from desloppify.engine._work_queue.ranking import build_issue_items


@pytest.mark.parametrize(
    ("languages", "expected_hint"),
    [
        (["kotlin", "kotlin"], None),
        (["typescript", "kotlin"], None),
        (["unknown", "unknown"], None),
        (["typescript", "typescript"], "desloppify autofix unused-imports --dry-run"),
    ],
)
def test_cluster_only_recommends_autofix_supported_by_every_member(
    languages, expected_hint,
):
    issues = {
        f"unused::{i}": {
            "id": f"unused::{i}", "detector": "unused", "status": "open",
            "file": f"src/file{i}", "lang": language, "confidence": "high",
        }
        for i, language in enumerate(languages)
    }
    state = {
        "issues": issues,
        "lang_capabilities": {
            "kotlin": {"fixers": ["ktlint-violation"]},
            "typescript": {"fixers": ["unused-imports"]},
        },
    }
    plan = {"clusters": {"auto/unused": {
        "auto": True,
        "issue_ids": list(issues),
        "action": "desloppify autofix unused-imports --dry-run",
    }}}
    items = build_issue_items(
        state, scan_path=None, status_filter="open", scope=None, chronic=False,
    )
    cluster, = collapse_clusters(items, plan)
    assert cluster["autofix_hint"] == expected_hint
    assert cluster["primary_command"] == "desloppify next --cluster auto/unused --count 10"


def test_manual_cluster_action_is_preserved():
    items = [{"id": f"smells::{i}", "detector": "smells"} for i in range(2)]
    plan = {"clusters": {"cleanup": {
        "issue_ids": [item["id"] for item in items],
        "action": "Extract the shared parser",
    }}}
    cluster, = collapse_clusters(items, plan)
    assert cluster["autofix_hint"] is None
    assert cluster["primary_command"] == "Extract the shared parser"
