"""Direct tests for review batch core helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.app.commands.review.batch_scoring import (
    DimensionMergeScorer,
    ScoreInputs,
)
from desloppify.app.commands.review import batch_core as batch_core_mod
from desloppify.intelligence.review.feedback_contract import (
    LOW_SCORE_FINDING_THRESHOLD,
    max_batch_findings_for_dimension_count,
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
    return batch_core_mod.merge_batch_results(
        batch_results,
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
        abstraction_component_names=_ABSTRACTION_COMPONENT_NAMES,
    )


def test_merge_penalizes_high_scores_when_severe_findings_exist():
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
                "findings": [
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
    assert merged["assessments"]["high_level_elegance"] == 75.7
    quality = merged.get("review_quality", {})
    assert quality["finding_pressure"] == 4.08
    assert quality["dimensions_with_findings"] == 1


def test_merge_keeps_scores_without_findings():
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
                "findings": [],
                "quality": {},
            }
        ]
    )
    assert merged["assessments"]["mid_level_elegance"] == 88.0


def test_batch_prompt_requires_score_and_finding_consistency():
    prompt = batch_core_mod.build_batch_prompt(
        repo_root=Path("/repo"),
        packet_path=Path("/repo/.desloppify/review_packets/p.json"),
        batch_index=0,
        batch={
            "name": "Architecture & Coupling",
            "dimensions": ["high_level_elegance"],
            "why": "test",
            "files_to_read": ["core.py", "scan.py"],
        },
    )
    assert "Score/finding consistency is required" in prompt
    assert "Seed files (start here):" in prompt
    assert "Start with the seed files, then freely explore additional repository files" in prompt
    assert "Evaluate ONLY listed files and ONLY listed dimensions" not in prompt


def test_dimension_merge_scorer_penalizes_higher_pressure():
    scorer = DimensionMergeScorer()
    low = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            finding_pressure=1.0,
            finding_count=1,
        )
    )
    high = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            finding_pressure=4.08,
            finding_count=1,
        )
    )
    assert low.final_score > high.final_score


def test_dimension_merge_scorer_penalizes_additional_findings():
    scorer = DimensionMergeScorer()
    one_finding = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            finding_pressure=2.0,
            finding_count=1,
        )
    )
    three_findings = scorer.score_dimension(
        ScoreInputs(
            weighted_mean=92.0,
            floor=90.0,
            finding_pressure=2.0,
            finding_count=3,
        )
    )
    assert one_finding.final_score > three_findings.final_score


def test_merge_batch_results_merges_same_identifier_findings():
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
                "findings": [
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
                "findings": [
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
    findings = merged["findings"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["identifier"] == "processing_filter_predicate_mismatch"
    assert finding["summary"] == "Processing predicate mismatch across hooks"
    assert set(finding["related_files"]) == {"src/a.ts", "src/b.ts", "src/c.ts"}
    assert set(finding["evidence"]) == {"branch A uses OR", "branch B uses AND"}


def test_normalize_batch_result_rejects_low_score_without_same_dimension_finding():
    with pytest.raises(ValueError) as exc:
        batch_core_mod.normalize_batch_result(
            payload={
                "assessments": {"logic_clarity": LOW_SCORE_FINDING_THRESHOLD - 10.0},
                "dimension_notes": {
                    "logic_clarity": {
                        "evidence": ["branching logic diverges across handlers"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "high",
                        "issues_preventing_higher_score": "",
                    }
                },
                "findings": [],
            },
            allowed_dims={"logic_clarity"},
            max_batch_findings=max_batch_findings_for_dimension_count(1),
            abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
        )
    assert "low-score dimensions must include at least one explicit finding" in str(exc.value)


def test_normalize_batch_result_accepts_low_score_with_same_dimension_finding():
    assessments, findings, _notes, _quality = batch_core_mod.normalize_batch_result(
        payload={
            "assessments": {"logic_clarity": LOW_SCORE_FINDING_THRESHOLD - 10.0},
            "dimension_notes": {
                "logic_clarity": {
                    "evidence": ["branching logic diverges across handlers"],
                    "impact_scope": "module",
                    "fix_scope": "single_edit",
                    "confidence": "high",
                    "issues_preventing_higher_score": "",
                }
            },
            "findings": [
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
        max_batch_findings=max_batch_findings_for_dimension_count(1),
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
    )
    assert assessments["logic_clarity"] == LOW_SCORE_FINDING_THRESHOLD - 10.0
    assert len(findings) == 1


def test_normalize_batch_result_accepts_legacy_unreported_risk_key():
    _assessments, _findings, notes, _quality = batch_core_mod.normalize_batch_result(
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
            "findings": [
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
        max_batch_findings=max_batch_findings_for_dimension_count(1),
        abstraction_sub_axes=_ABSTRACTION_SUB_AXES,
    )
    assert (
        notes["logic_clarity"]["issues_preventing_higher_score"]
        == "legacy note still provided"
    )
