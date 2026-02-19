"""Direct tests for review batch core helpers."""

from __future__ import annotations

from pathlib import Path

from desloppify.app.commands.review import batch_core as batch_core_mod

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
                        "unreported_risk": "major refactor required",
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
                        "unreported_risk": "minor seam churn remains",
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
