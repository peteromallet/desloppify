"""Direct regression tests for review batch result coverage."""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.app.commands.review.batch.execution_results import (
    merge_and_write_results,
)


def test_selected_dimension_run_requires_only_selected_assessment_coverage(tmp_path: Path) -> None:
    selected = ["cross_module_architecture"]
    scored = ["naming_quality", *selected, "type_safety"]
    output = tmp_path / "holistic_issues_merged.json"

    def write_text(path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")

    merged_path, missing = merge_and_write_results(
        merge_batch_results_fn=lambda _results: {
            "assessments": {"cross_module_architecture": 83},
            "issues": [],
        },
        build_import_provenance_fn=lambda **_kwargs: {"source": "test"},
        batch_results=[{"assessments": {"cross_module_architecture": 83}}],
        batches=[{"name": "cross_module_architecture"}],
        successful_indexes=[0],
        packet={"dimensions": selected},
        packet_dimensions=selected,
        scored_dimensions=scored,
        scan_path=".",
        runner="codex",
        prompt_packet_path=tmp_path / "packet.json",
        stamp="test-run",
        run_dir=tmp_path,
        safe_write_text_fn=write_text,
        colorize_fn=lambda text, _tone=None: text,
    )

    assert merged_path == output
    assert missing == []
    coverage = json.loads(output.read_text(encoding="utf-8"))["assessment_coverage"]
    assert coverage["scored_dimensions"] == scored
    assert coverage["selected_dimensions"] == selected
    assert coverage["imported_dimensions"] == selected
    assert coverage["missing_dimensions"] == []


def test_selected_dimension_run_still_rejects_missing_selected_assessment(tmp_path: Path) -> None:
    output = tmp_path / "holistic_issues_merged.json"

    def write_text(path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")

    _, missing = merge_and_write_results(
        merge_batch_results_fn=lambda _results: {"assessments": {}, "issues": []},
        build_import_provenance_fn=lambda **_kwargs: {},
        batch_results=[{"assessments": {}}],
        batches=[{"name": "cross_module_architecture"}],
        successful_indexes=[0],
        packet={"dimensions": ["cross_module_architecture"]},
        packet_dimensions=["cross_module_architecture"],
        scored_dimensions=["naming_quality", "cross_module_architecture"],
        scan_path=".",
        runner="codex",
        prompt_packet_path=tmp_path / "packet.json",
        stamp="test-run",
        run_dir=tmp_path,
        safe_write_text_fn=write_text,
        colorize_fn=lambda text, _tone=None: text,
    )

    assert missing == ["cross_module_architecture"]
    coverage = json.loads(output.read_text(encoding="utf-8"))["assessment_coverage"]
    assert coverage["missing_dimensions"] == ["cross_module_architecture"]
