"""Trusted imports must cover their selected dimensions, not every language dimension."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.app.commands.review.batch.orchestrator import do_import_run
from desloppify.app.commands.review.batch.scope import (
    enforce_trusted_import_coverage_gate,
    missing_scored_dimensions,
    scored_dimensions_for_lang,
)
from desloppify.base.exception_sets import CommandError
from desloppify.engine._state.schema import empty_state


def _enforce(assessed: list[str], selected: list[str], scored: list[str]) -> None:
    enforce_trusted_import_coverage_gate(
        missing_dims=missing_scored_dimensions(
            selected_dims=assessed, scored_dims=scored,
        ),
        selected_dims=selected,
        allow_partial=False,
        scan_path=".",
        colorize_fn=lambda text, _tone: text,
    )


def test_complete_explicit_eighteen_dimension_selection_passes() -> None:
    scored = scored_dimensions_for_lang("php")
    selected = [
        dimension for dimension in scored
        if dimension not in {"initialization_coupling", "incomplete_migration"}
    ]
    assert len(scored) == 20
    assert len(selected) == 18

    _enforce(selected, selected, scored)


def test_missing_selected_dimension_still_blocks(capsys) -> None:
    with pytest.raises(CommandError, match="incomplete selected-dimension coverage"):
        _enforce(
            ["naming_quality"],
            ["naming_quality", "logic_clarity"],
            ["naming_quality", "logic_clarity", "type_safety"],
        )

    err = capsys.readouterr().err
    assert "Missing dimensions: logic_clarity" in err
    assert "type_safety" not in err


def test_full_default_dimension_selection_remains_fail_closed() -> None:
    scored = scored_dimensions_for_lang("php")

    with pytest.raises(CommandError, match="incomplete selected-dimension coverage"):
        _enforce(scored[:-1], scored, scored)


def _write_completed_run(root: Path, dimensions: list[str]) -> Path:
    run_dir = root / "run"
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True)
    packet_path = run_dir / "packet.json"
    blind_path = run_dir / "blind.json"
    packet = {
        "dimensions": dimensions,
        "investigation_batches": [
            {"name": "Selected review", "dimensions": dimensions},
        ],
    }
    packet_path.write_text(json.dumps(packet))
    blind_path.write_text(json.dumps(packet))
    (run_dir / "run_summary.json").write_text(json.dumps({
        "runner": "codex",
        "run_stamp": "synthetic-completed-run",
        "selected_batches": [1],
        "successful_batches": [1],
        "failed_batches": [],
        "immutable_packet": str(packet_path),
        "blind_packet": str(blind_path),
    }))
    payload = {
        "assessments": {dimension: 88.0 for dimension in dimensions},
        "dimension_notes": {
            dimension: {
                "evidence": ["The synthetic module uses one explicit public entry point."],
                "impact_scope": "module",
                "fix_scope": "single_edit",
                "confidence": "high",
                "issues_preventing_higher_score": "Optional documentation detail remains unexamined.",
            }
            for dimension in dimensions
        },
        "dimension_judgment": {
            dimension: {
                "strengths": ["The synthetic module has an explicit public boundary."],
                "dimension_character": "The fixture contains one small module with clear ownership.",
                "score_rationale": (
                    "The fixture exposes one readable operation with clear ownership. "
                    "Optional documentation detail remains unexamined, so the assessment "
                    "does not claim comprehensive evidence beyond the synthetic boundary."
                ),
            }
            for dimension in dimensions
        },
        "issues": [],
    }
    (results_dir / "batch-1.raw.txt").write_text(json.dumps(payload))
    return run_dir


def test_completed_import_run_preserves_unselected_trusted_assessments(
    set_project_root: Path,
) -> None:
    scored = scored_dimensions_for_lang("php")
    unselected = {"initialization_coupling", "incomplete_migration"}
    selected = [dimension for dimension in scored if dimension not in unselected]
    run_dir = _write_completed_run(set_project_root, selected)
    original_raw_hash = hashlib.sha256(
        (run_dir / "results/batch-1.raw.txt").read_bytes(),
    ).hexdigest()
    state = empty_state()
    for dimension in unselected:
        state["subjective_assessments"][dimension] = {
            "score": 91.0,
            "source": "holistic",
            "assessed_at": "2025-01-02T03:04:05+00:00",
            "judgment": {"strengths": ["Previously reviewed synthetic boundary."]},
        }
    original_assessments = copy.deepcopy(state["subjective_assessments"])
    state_file = set_project_root / ".desloppify/state-php.json"

    do_import_run(
        str(run_dir), state, SimpleNamespace(name="php"), state_file,
        config={}, allow_partial=False, scan_after_import=False,
    )

    persisted = json.loads(state_file.read_text())
    assert set(persisted["subjective_assessments"]) == set(scored)
    for dimension in unselected:
        assert persisted["subjective_assessments"][dimension] == original_assessments[dimension]
    for dimension in selected:
        assert persisted["subjective_assessments"][dimension]["score"] == 88.0
        assert persisted["subjective_assessments"][dimension]["source"] == "holistic"
    assert persisted["assessment_import_audit"][-1]["mode"] == "trusted_internal"
    assert hashlib.sha256(
        (run_dir / "results/batch-1.raw.txt").read_bytes(),
    ).hexdigest() == original_raw_hash
    assert not (run_dir / "prompts").exists()
    assert not (run_dir / "logs").exists()
