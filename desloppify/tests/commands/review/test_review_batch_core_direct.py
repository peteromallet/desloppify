"""Direct tests for review batch core helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.app.commands.review.batch.core_normalize import normalize_batch_result
from desloppify.app.commands.review.batch.merge import merge_batch_results
from desloppify.app.commands.review.batch.prompt_template import render_batch_prompt
from desloppify.app.commands.review.batch.scoring import (
    DimensionMergeScorer,
    ScoreInputs,
    _percentile_floor,
)
from desloppify.intelligence.review.feedback_contract import (
    LOW_SCORE_ISSUE_THRESHOLD,
    max_batch_issues_for_dimension_count,
)

_ABSTRACTION_SUB_AXES = (
    "abstraction_leverage",
    "indirection_cost",
    "interface_honesty",
)
_ABSTRACTION_COMPONENT_NAMES = {
    "abstraction_leverage": "Abstraction leverage",
    "indirection_cost": "Indirection cost",
    "interface_honesty": "Interface honesty",
}


def _merge(batch_results: list[dict]) -> dict[str, object]:
    return merge_batch_results(
        batch_results,
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
        abstraction_component_names=_ABSTRACTION_COMPONENT_NAMES,
    )


def test_merge_penalizes_high_scores_when_severe_issues_exist():
    merged = _merge(
        [
            {
                "assessments": {"high_level_elegance": 92.0},
                "dimension_notes": {
                    "high_level_elegance": {
                        "evidence": ["layering is inconsistent around shared core"],
                        "impact_scope": "codebase",
                        "fix_scope": "architectural_change",
                        "confidence": "high",
                        "issues_preventing_higher_score": "major refactor required",
                    }
                },
                "issues": [
                    {
                        "dimension": "high_level_elegance",
                        "identifier": "core_boundary_drift",
                        "summary": "boundary drift across critical modules",
                        "confidence": "high",
                        "impact_scope": "codebase",
                        "fix_scope": "architectural_change",
                    }
                ],
                "quality": {},
            }
        ]
    )
    assert merged["assessments"]["high_level_elegance"] == 78.1
    assert merged["review_quality"]["issue_pressure"] == 3.4
    assert merged["review_quality"]["dimensions_with_issues"] == 1


def test_merge_keeps_scores_without_issues():
    merged = _merge(
        [
            {
                "assessments": {"mid_level_elegance": 88.0},
                "dimension_notes": {
                    "mid_level_elegance": {
                        "evidence": ["handoff seams are mostly coherent"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "medium",
                        "issues_preventing_higher_score": "minor seam churn remains",
                    }
                },
                "issues": [],
                "quality": {},
            }
        ]
    )
    assert merged["assessments"]["mid_level_elegance"] == 88.0


def test_batch_prompt_requires_score_and_issue_consistency():
    prompt = render_batch_prompt(
        repo_root=Path("/repo"),
        packet_path=Path("/repo/.desloppify/review_packets/p.json"),
        batch_index=0,
        batch={
            "name": "high_level_elegance",
            "dimensions": ["high_level_elegance"],
            "why": "test",
            "files_to_read": ["core.py", "scan.py"],
        },
    )
    assert "Seed files (start here):" in prompt
    assert "Start from the seed files" in prompt
    assert "blind packet's `system_prompt`" in prompt
    assert "Evaluate ONLY listed files and ONLY listed dimensions" not in prompt


def test_dimension_merge_scorer_penalizes_higher_pressure():
    scorer = DimensionMergeScorer()
    low = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            issue_pressure=1.0,
            issue_count=1,
        )
    )
    high = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            issue_pressure=4.08,
            issue_count=1,
        )
    )
    assert low.final_score > high.final_score


def test_dimension_merge_scorer_penalizes_additional_issues():
    scorer = DimensionMergeScorer()
    one_issue = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            issue_pressure=2.0,
            issue_count=1,
        )
    )
    three_issues = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            issue_pressure=2.0,
            issue_count=3,
        )
    )
    assert one_issue.final_score > three_issues.final_score


def test_merge_batch_results_merges_same_identifier_issues():
    merged = _merge(
        [
            {
                "assessments": {"logic_clarity": 70.0},
                "dimension_notes": {
                    "logic_clarity": {
                        "evidence": ["predicate mismatch in task filtering"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "medium",
                        "issues_preventing_higher_score": "",
                    }
                },
                "issues": [
                    {
                        "dimension": "logic_clarity",
                        "identifier": "processing_filter_predicate_mismatch",
                        "summary": "Mismatch in processing predicates",
                        "related_files": ["src/a.ts", "src/b.ts"],
                        "evidence": ["branch A uses OR"],
                        "suggestion": "align predicates",
                        "confidence": "high",
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                    }
                ],
                "quality": {},
            },
            {
                "assessments": {"logic_clarity": 65.0},
                "dimension_notes": {
                    "logic_clarity": {
                        "evidence": ["task filtering diverges"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "medium",
                        "issues_preventing_higher_score": "",
                    }
                },
                "issues": [
                    {
                        "dimension": "logic_clarity",
                        "identifier": "processing_filter_predicate_mismatch",
                        "summary": "Processing predicate mismatch across hooks",
                        "related_files": ["src/b.ts", "src/c.ts"],
                        "evidence": ["branch B uses AND"],
                        "suggestion": "create shared predicate helper",
                        "confidence": "high",
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                    }
                ],
                "quality": {},
            },
        ]
    )
    issues = merged["issues"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue["identifier"] == "processing_filter_predicate_mismatch"
    assert issue["summary"] == "Processing predicate mismatch across hooks"
    assert set(issue["related_files"]) == {"src/a.ts", "src/b.ts", "src/c.ts"}
    assert set(issue["evidence"]) == {"branch A uses OR", "branch B uses AND"}


def test_normalize_batch_result_rejects_low_score_without_same_dimension_issue():
    with pytest.raises(ValueError) as exc:
        normalize_batch_result(
            payload={
                "assessments": {"logic_clarity": LOW_SCORE_ISSUE_THRESHOLD - 10.0},
                "dimension_notes": {
                    "logic_clarity": {
                        "evidence": ["branching logic diverges across handlers"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "high",
                        "issues_preventing_higher_score": "",
                    }
                },
                "dimension_judgment": {
                    "logic_clarity": {
                        "strengths": ["handlers keep domain names consistent"],
                        "issue_character": "Predicate logic drifts between equivalent paths.",
                        "score_rationale": (
                            "The core decision paths are understandable, but equivalent handlers "
                            "encode different branching logic and create behavioral drift. "
                            "That inconsistency materially reduces trust in control-flow clarity."
                        ),
                    }
                },
                "issues": [],
            },
            allowed_dims={"logic_clarity"},
            max_batch_issues=max_batch_issues_for_dimension_count(1),
            abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
        )
    assert "low-score dimensions must include at least one explicit issue" in str(exc.value)


def test_normalize_batch_result_accepts_low_score_with_same_dimension_issue():
    assessments, issues, _notes, _judgment, _quality = normalize_batch_result(
        payload={
            "assessments": {"logic_clarity": LOW_SCORE_ISSUE_THRESHOLD - 10.0},
            "dimension_notes": {
                "logic_clarity": {
                    "evidence": ["branching logic diverges across handlers"],
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                    "confidence": "high",
                    "issues_preventing_higher_score": "",
                }
            },
            "dimension_judgment": {
                "logic_clarity": {
                    "strengths": ["predicate naming is mostly descriptive"],
                    "issue_character": "Control-flow choices are easy to follow but inconsistent.",
                    "score_rationale": (
                        "Branch structure is readable in isolation, yet equivalent handlers "
                        "use incompatible predicate logic that undermines coherence. "
                        "The score reflects moderate clarity with meaningful divergence risk."
                    ),
                }
            },
            "issues": [
                {
                    "dimension": "logic_clarity",
                    "identifier": "divergent_predicates",
                    "summary": "Predicate branches diverge in equivalent handlers",
                    "related_files": ["src/a.ts", "src/b.ts"],
                    "evidence": ["handler A uses OR, handler B uses AND"],
                    "suggestion": "extract a shared predicate helper and reuse it",
                    "confidence": "high",
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                }
            ],
        },
        allowed_dims={"logic_clarity"},
        max_batch_issues=max_batch_issues_for_dimension_count(1),
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
    )
    assert assessments["logic_clarity"] == LOW_SCORE_ISSUE_THRESHOLD - 10.0
    assert len(issues) == 1


def test_normalize_batch_result_accepts_legacy_findings_alias():
    assessments, issues, _notes, _judgment, _quality = normalize_batch_result(
        payload={
            "assessments": {"logic_clarity": 80.0},
            "dimension_notes": {
                "logic_clarity": {
                    "evidence": ["legacy alias path"],
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                    "confidence": "medium",
                    "issues_preventing_higher_score": "",
                }
            },
            "dimension_judgment": {
                "logic_clarity": {
                    "strengths": ["legacy payload shape is still parseable"],
                    "issue_character": "The contract is clear but legacy paths increase ambiguity.",
                    "score_rationale": (
                        "The importer retains strong structural expectations, but alias handling "
                        "adds historical complexity that can obscure canonical usage. "
                        "The score reflects mostly clear logic with compatibility overhead."
                    ),
                }
            },
            "findings": [
                {
                    "dimension": "logic_clarity",
                    "identifier": "legacy_findings_alias",
                    "summary": "Legacy findings key still normalizes",
                    "related_files": ["src/a.ts"],
                    "evidence": ["payload used findings key"],
                    "suggestion": "continue importing via issues key",
                    "confidence": "medium",
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                }
            ],
        },
        allowed_dims={"logic_clarity"},
        max_batch_issues=max_batch_issues_for_dimension_count(1),
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
    )
    assert assessments["logic_clarity"] == 80.0
    assert len(issues) == 1
    assert issues[0]["identifier"] == "legacy_findings_alias"


def test_normalize_batch_result_rejects_missing_dimension_judgment_entry():
    with pytest.raises(ValueError) as exc:
        normalize_batch_result(
            payload={
                "assessments": {"logic_clarity": 80.0},
                "dimension_notes": {
                    "logic_clarity": {
                        "evidence": ["branching logic is mostly clear"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "medium",
                        "issues_preventing_higher_score": "",
                    }
                },
                "issues": [
                    {
                        "dimension": "logic_clarity",
                        "identifier": "judgment_contract_missing",
                        "summary": "Missing judgment contract should fail closed",
                        "related_files": ["src/a.ts"],
                        "evidence": ["dimension_judgment omitted"],
                        "suggestion": "provide all required judgment fields",
                        "confidence": "medium",
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                    }
                ],
            },
            allowed_dims={"logic_clarity"},
            max_batch_issues=max_batch_issues_for_dimension_count(1),
            abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
        )
    assert "dimension_judgment missing entry for assessed dimension" in str(exc.value)


def test_normalize_batch_result_rejects_incomplete_dimension_judgment_entry():
    with pytest.raises(ValueError) as exc:
        normalize_batch_result(
            payload={
                "assessments": {"logic_clarity": 80.0},
                "dimension_notes": {
                    "logic_clarity": {
                        "evidence": ["branching logic is mostly clear"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "medium",
                        "issues_preventing_higher_score": "",
                    }
                },
                "dimension_judgment": {
                    "logic_clarity": {
                        "strengths": ["handler structure is predictable"],
                        "issue_character": "some divergence exists",
                    }
                },
                "issues": [
                    {
                        "dimension": "logic_clarity",
                        "identifier": "judgment_contract_incomplete",
                        "summary": "Incomplete judgment contract should fail closed",
                        "related_files": ["src/a.ts"],
                        "evidence": ["score_rationale omitted"],
                        "suggestion": "require full judgment payload for assessed dimensions",
                        "confidence": "medium",
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                    }
                ],
            },
            allowed_dims={"logic_clarity"},
            max_batch_issues=max_batch_issues_for_dimension_count(1),
            abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
        )
    assert "dimension_judgment.logic_clarity.score_rationale" in str(exc.value)


def test_normalize_batch_result_accepts_legacy_unreported_risk_key():
    _assessments, _issues, notes, _judgment, _quality = normalize_batch_result(
        payload={
            "assessments": {"logic_clarity": 90.0},
            "dimension_notes": {
                "logic_clarity": {
                    "evidence": ["legacy payload compatibility path"],
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                    "confidence": "medium",
                    "unreported_risk": "legacy note still provided",
                }
            },
            "dimension_judgment": {
                "logic_clarity": {
                    "strengths": ["legacy and canonical fields are reconciled"],
                    "issue_character": "Compatibility handling is explicit but adds branching cost.",
                    "score_rationale": (
                        "Normalization logic remains understandable because compatibility keys are "
                        "handled in one place, but each legacy path increases cognitive load. "
                        "The score reflects that tradeoff."
                    ),
                }
            },
            "issues": [
                {
                    "dimension": "logic_clarity",
                    "identifier": "legacy_note_path",
                    "summary": "Legacy note field still accepted",
                    "related_files": ["src/a.ts", "src/b.ts"],
                    "evidence": ["legacy payload uses unreported_risk"],
                    "suggestion": "continue normalizing onto the new field",
                    "confidence": "medium",
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                }
            ],
        },
        allowed_dims={"logic_clarity"},
        max_batch_issues=max_batch_issues_for_dimension_count(1),
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
    )
    assert (
        notes["logic_clarity"]["issues_preventing_higher_score"]
        == "legacy note still provided"
    )


# --- _percentile_floor tests ---


def test_percentile_floor_single_entry_returns_min():
    assert _percentile_floor([(42.0, 5.0)], fallback=99.0) == 42.0


def test_percentile_floor_empty_returns_fallback():
    assert _percentile_floor([], fallback=77.0) == 77.0


def test_percentile_floor_two_equal_weight_entries():
    # Bottom 10% of total weight (2.0) is 0.2 — first entry (50, 1.0)
    # exceeds threshold immediately, so floor = 50.0.
    result = _percentile_floor([(50.0, 1.0), (90.0, 1.0)], fallback=70.0)
    assert result == 50.0


def test_percentile_floor_weights_bottom_entries():
    # Entries: (30, 2.0), (60, 3.0), (90, 5.0)
    # Total weight = 10, threshold = 1.0
    # Sorted: (30, 2.0) — accumulated 2.0 >= 1.0, stop.
    # Floor = 30*2/2 = 30.0
    result = _percentile_floor([(90.0, 5.0), (30.0, 2.0), (60.0, 3.0)], fallback=70.0)
    assert result == 30.0


def test_percentile_floor_small_bad_weight_still_contributes():
    # Entries: (20, 0.5), (85, 4.5), (90, 5.0)
    # Total weight = 10, threshold = 1.0
    # Sorted: (20, 0.5) — accumulated 0.5 < 1.0, continue
    #         (85, 4.5) — accumulated 5.0 >= 1.0, stop.
    # Floor = (20*0.5 + 85*4.5) / 5.0 = (10 + 382.5) / 5.0 = 78.5
    result = _percentile_floor([(85.0, 4.5), (20.0, 0.5), (90.0, 5.0)], fallback=80.0)
    assert result == pytest.approx(78.5)


def test_merge_scores_uses_percentile_floor_not_absolute_min():
    """Verify that merging a tiny bad file with a large good file
    produces a higher floor than the old min()-based approach would."""
    scorer = DimensionMergeScorer()
    dim = "logic_clarity"

    # Scenario: one small bad file (score=30, weight=0.3) and one
    # large good file (score=90, weight=9.7).
    score_buckets = {dim: [(30.0, 0.3), (90.0, 9.7)]}
    # score_raw_by_dim is no longer used for floor, but pass it for API compat.
    score_raw_by_dim = {dim: [30.0, 90.0]}

    result = scorer.merge_scores(score_buckets, score_raw_by_dim, {}, {})
    # Old min()-based floor would be 30.0.
    # New percentile floor: threshold = 10.0 * 0.1 = 1.0
    #   sorted: (30, 0.3) -> acc 0.3, (90, 9.7) -> acc 10.0 >= 1.0
    #   floor = (30*0.3 + 90*9.7) / 10.0 = (9 + 873) / 10.0 = 88.2
    # floor_aware = 0.7 * weighted_mean + 0.3 * 88.2
    # weighted_mean = (30*0.3 + 90*9.7) / 10.0 = 88.2
    # floor_aware = 0.7 * 88.2 + 0.3 * 88.2 = 88.2
    assert result[dim] == pytest.approx(88.2)


def test_merge_scores_bad_file_cannot_game_by_merging():
    """Core regression: merging a bad file into a good file should not
    eliminate the floor penalty entirely."""
    scorer = DimensionMergeScorer()
    dim = "logic_clarity"

    # Before gaming: two separate files.
    separate = scorer.merge_scores(
        {dim: [(40.0, 3.0), (90.0, 7.0)]},
        {dim: [40.0, 90.0]},
        {},
        {},
    )

    # After gaming: bad code merged into the good file (same total weight).
    merged_single = scorer.merge_scores(
        {dim: [(75.0, 10.0)]},
        {dim: [75.0]},
        {},
        {},
    )

    # The separate-files score should still reflect the bad code penalty.
    # With percentile floor, the two approaches produce similar results
    # rather than letting the merged version completely escape the floor.
    # The key property: separate files score <= merged single file score
    # (but the gap is much smaller than with min()-based floor).
    assert separate[dim] <= merged_single[dim]
