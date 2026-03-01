"""Focused tests for review duplicate-merge matching rules."""

from __future__ import annotations

from desloppify.app.commands.review import merge as merge_mod


def _finding(
    finding_id: str,
    *,
    summary: str,
    dimension: str = "design_coherence",
    related_files: list[str] | None = None,
    root_cause_cluster: str | None = None,
) -> dict[str, object]:
    detail: dict[str, object] = {"dimension": dimension}
    if related_files is not None:
        detail["related_files"] = related_files
    if root_cause_cluster is not None:
        detail["root_cause_cluster"] = root_cause_cluster
    return {"id": finding_id, "summary": summary, "detail": detail}


def test_same_issue_concept_merges_when_identifiers_match() -> None:
    left = _finding(
        "review::.::holistic::design_coherence::shared_issue::aaaa1111",
        summary="A summary",
        related_files=["desloppify/app/commands/review/merge.py"],
    )
    right = _finding(
        "review::.::holistic::design_coherence::shared_issue::bbbb2222",
        summary="Different summary",
        related_files=["desloppify/app/commands/review/merge.py"],
    )
    assert merge_mod._same_issue_concept(left, right, similarity_threshold=0.95)


def test_same_issue_concept_merges_when_root_cause_cluster_matches() -> None:
    left = _finding(
        "review::.::holistic::design_coherence::issue_left::aaaa1111",
        summary="A summary",
        root_cause_cluster="review.pipeline.shape",
        related_files=["desloppify/app/commands/review/batches.py"],
    )
    right = _finding(
        "review::.::holistic::design_coherence::issue_right::bbbb2222",
        summary="Different summary",
        root_cause_cluster="review.pipeline.shape",
        related_files=["desloppify/app/commands/review/batches.py"],
    )
    assert merge_mod._same_issue_concept(left, right, similarity_threshold=0.95)


def test_same_issue_concept_rejects_identifier_only_match_in_strict_mode() -> None:
    left = _finding(
        "review::.::holistic::design_coherence::shared_issue::aaaa1111",
        summary="One summary",
        related_files=["desloppify/app/commands/review/a.py"],
    )
    right = _finding(
        "review::.::holistic::design_coherence::shared_issue::bbbb2222",
        summary="Completely different language here",
        related_files=["desloppify/app/commands/review/b.py"],
    )
    assert not merge_mod._same_issue_concept(left, right, similarity_threshold=0.95)


def test_same_issue_concept_requires_related_file_overlap_for_summary_merge() -> None:
    left = _finding(
        "review::.::holistic::design_coherence::issue_left::aaaa1111",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=["desloppify/app/commands/review/batches.py"],
    )
    right = _finding(
        "review::.::holistic::design_coherence::issue_right::bbbb2222",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=["desloppify/app/commands/review/import_cmd.py"],
    )
    assert not merge_mod._same_issue_concept(left, right, similarity_threshold=0.2)


def test_same_issue_concept_rejects_summary_merge_without_file_metadata() -> None:
    left = _finding(
        "review::.::holistic::design_coherence::issue_left::aaaa1111",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=[],
    )
    right = _finding(
        "review::.::holistic::design_coherence::issue_right::bbbb2222",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=["desloppify/app/commands/review/batches.py"],
    )
    assert not merge_mod._same_issue_concept(left, right, similarity_threshold=0.2)


def test_build_merge_groups_collapses_transitive_duplicate_chain() -> None:
    first = _finding(
        "review::.::holistic::design_coherence::issue_first::aaaa1111",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=["desloppify/app/commands/review/batch.py"],
    )
    bridge = _finding(
        "review::.::holistic::design_coherence::issue_bridge::bbbb2222",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=[
            "desloppify/app/commands/review/batch.py",
            "desloppify/app/commands/review/import_cmd.py",
        ],
    )
    third = _finding(
        "review::.::holistic::design_coherence::issue_third::cccc3333",
        summary="Batch orchestration callback sprawl in review runner",
        related_files=["desloppify/app/commands/review/import_cmd.py"],
    )

    groups = merge_mod._build_merge_groups(
        [first, bridge, third],
        similarity_threshold=0.2,
        strict_merge=True,
    )
    assert len(groups) == 1
    assert [entry["id"] for entry in groups[0]] == [
        first["id"],
        bridge["id"],
        third["id"],
    ]
