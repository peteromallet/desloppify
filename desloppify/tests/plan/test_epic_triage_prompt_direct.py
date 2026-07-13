"""Direct coverage tests for grouped triage prompt rendering contracts."""

from __future__ import annotations

from desloppify.engine._plan.triage.prompt import TriageInput, build_triage_prompt


def _issue(issue_id: str, *, summary: str, dimension: str) -> tuple[str, dict]:
    return issue_id, {
        "summary": summary,
        "detail": {"dimension": dimension},
        "file": "src/sample.py",
        "confidence": "medium",
    }


def test_build_triage_prompt_includes_completed_clusters_and_resolved_issue_context() -> None:
    open_id, open_issue = _issue(
        "review::open::aaaabbbb",
        summary="Open abstraction mismatch",
        dimension="abstraction_fitness",
    )
    resolved_id, resolved_issue = _issue(
        "review::resolved::ccccdddd",
        summary="Resolved abstraction mismatch",
        dimension="abstraction_fitness",
    )
    triage_input = TriageInput(
        review_issues={open_id: open_issue},
        objective_backlog_issues={},
        existing_clusters={},
        dimension_scores={},
        new_since_last={open_id},
        resolved_since_last={resolved_id},
        previously_dismissed=[],
        triage_version=3,
        resolved_issues={resolved_id: resolved_issue},
        completed_clusters=[
            {
                "name": "cluster/runtime-seams",
                "thesis": "Normalize runtime seam ownership",
                "issue_ids": [resolved_id],
                "completed_at": "2026-03-10T10:00:00Z",
            }
        ],
    )

    prompt = build_triage_prompt(triage_input)

    assert "## Resolved review issues available for recurrence context (1)" in prompt
    assert resolved_id in prompt
    assert "## Completed clusters since last triage (1)" in prompt
    assert "cluster/runtime-seams: Normalize runtime seam ownership" in prompt


def test_build_triage_prompt_renders_recurring_dimension_summary() -> None:
    open_id, open_issue = _issue(
        "review::open::1111aaaa",
        summary="Open API drift",
        dimension="api_surface_coherence",
    )
    resolved_same_id, resolved_same_issue = _issue(
        "review::resolved::2222bbbb",
        summary="Resolved API drift",
        dimension="api_surface_coherence",
    )
    resolved_other_id, resolved_other_issue = _issue(
        "review::resolved::3333cccc",
        summary="Resolved naming issue",
        dimension="naming_quality",
    )
    triage_input = TriageInput(
        review_issues={open_id: open_issue},
        objective_backlog_issues={},
        existing_clusters={},
        dimension_scores={},
        new_since_last=set(),
        resolved_since_last={resolved_same_id, resolved_other_id},
        previously_dismissed=[],
        triage_version=1,
        resolved_issues={
            resolved_same_id: resolved_same_issue,
            resolved_other_id: resolved_other_issue,
        },
        completed_clusters=[],
    )

    prompt = build_triage_prompt(triage_input)

    assert "## Potential recurring dimensions (resolved issues still have open peers)" in prompt
    assert "- api_surface_coherence: 1 open / 1 recently resolved" in prompt
    assert "naming_quality: 1 open" not in prompt


def test_build_triage_prompt_includes_mechanical_backlog_context() -> None:
    open_id, open_issue = _issue(
        "review::open::1111aaaa",
        summary="Open API drift",
        dimension="api_surface_coherence",
    )
    triage_input = TriageInput(
        review_issues={open_id: open_issue},
        objective_backlog_issues={
            "unused::src/a.py::dead": {
                "detector": "unused",
                "summary": "Unused export",
                "file": "src/a.py",
                "confidence": "high",
            },
            "test_coverage::src/b.py::miss": {
                "detector": "test_coverage",
                "summary": "Missing behavioral coverage",
                "file": "src/b.py",
                "confidence": "medium",
            },
        },
        auto_clusters={
            "auto/unused-imports": {
                "auto": True,
                "issue_ids": ["unused::src/a.py::dead"],
                "description": "Remove 1 unused import issue",
                "action": "desloppify autofix import-cleanup --dry-run",
            }
        },
        existing_clusters={},
        dimension_scores={},
        new_since_last=set(),
        resolved_since_last=set(),
        previously_dismissed=[],
        triage_version=1,
        resolved_issues={},
        completed_clusters=[],
    )

    prompt = build_triage_prompt(triage_input)

    assert "## Auto-cluster candidates (2 items: 1 in 1 auto-clusters, 1 unclustered)" in prompt
    assert "### Auto-clusters (decision required for each)" in prompt
    assert "`auto_cluster_decisions`" in prompt
    assert "- auto/unused-imports (1 items) [autofix: desloppify autofix import-cleanup --dry-run]" in prompt
    assert "Remove 1 unused import issue" in prompt
    assert "### Unclustered items (1 items — needs human judgment or isolated findings)" in prompt
    assert "- [medium] test_coverage::src/b.py::miss — Missing behavioral coverage" in prompt
    assert "Inspect a cluster: `desloppify plan cluster show auto/<name>`" in prompt


def test_build_triage_prompt_can_omit_legacy_auto_cluster_decision_guidance() -> None:
    open_id, open_issue = _issue(
        "review::open::1111aaaa",
        summary="Open API drift",
        dimension="api_surface_coherence",
    )
    triage_input = TriageInput(
        review_issues={open_id: open_issue},
        objective_backlog_issues={
            "unused::src/a.py::dead": {
                "detector": "unused",
                "summary": "Unused export",
                "file": "src/a.py",
                "confidence": "high",
            },
        },
        auto_clusters={
            "auto/unused-imports": {
                "auto": True,
                "issue_ids": ["unused::src/a.py::dead"],
                "description": "Remove 1 unused import issue",
            }
        },
        existing_clusters={},
        dimension_scores={},
        new_since_last=set(),
        resolved_since_last=set(),
        previously_dismissed=[],
        triage_version=1,
        resolved_issues={},
        completed_clusters=[],
    )

    prompt = build_triage_prompt(
        triage_input,
        include_auto_cluster_decision_guidance=False,
    )

    assert "## Auto-cluster candidates (1 items: 1 in 1 auto-clusters, 0 unclustered)" in prompt
    assert "### Auto-clusters" in prompt
    assert "### Auto-clusters (decision required for each)" not in prompt
    assert "- auto/unused-imports (1 items)" in prompt
    assert "`auto_cluster_decisions`" not in prompt
    assert "defer (keep in backlog" not in prompt
    assert "break_up (split into smaller sub-clusters" not in prompt
