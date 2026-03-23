"""Direct tests for review runner/batch split helper modules."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import desloppify.app.commands.review.runner_parallel.serial as runner_serial_mod
import desloppify.app.commands.review.runner_process_impl.attempt_success as runner_success_mod
import desloppify.app.commands.review.batch.core_merge_support as merge_support_mod
import desloppify.app.commands.review.batch.merge as batch_merge_mod
import desloppify.app.commands.review.batch.core_models as core_models_mod
import desloppify.app.commands.review.batch.core_normalize as core_normalize_mod
import desloppify.app.commands.review.batch.core_parse as core_parse_mod
import desloppify.app.commands.review.external as external_mod
from desloppify.app.commands.review.runner_process_impl.types import (
    BatchRunnerDeps as CodexBatchRunnerDeps,
    _ExecutionResult,
)


def test_execute_serial_tasks_tracks_failures_and_progress() -> None:
    events: list[tuple[int, str, int | None]] = []

    failures = runner_serial_mod.execute_serial_tasks(
        tasks={0: lambda: 0, 1: lambda: 1},
        indexes=[0, 1],
        progress_fn=lambda _event: None,
        error_log_fn=lambda _idx, _exc: None,
        clock_fn=lambda: 100.0,
        contract_cache={},
        emit_progress_fn=lambda _pf, idx, event, code, **_kw: (
            events.append((idx, event, code)) or None
        ),
        record_execution_error_fn=lambda **_kwargs: None,
        runner_task_exceptions=(RuntimeError,),
    )

    assert failures == [1]
    assert events[0] == (0, "start", None)
    assert events[-1] == (1, "done", 1)


def test_handle_successful_attempt_core_recovers_from_stdout_fallback(tmp_path) -> None:
    output_file = tmp_path / "out.txt"
    log_file = tmp_path / "run.log"

    deps = CodexBatchRunnerDeps(
        timeout_seconds=30,
        subprocess_run=object(),
        timeout_error=TimeoutError,
        safe_write_text_fn=lambda path, text: Path(path).write_text(
            text, encoding="utf-8"
        ),
        sleep_fn=lambda _seconds: None,
        validate_output_fn=lambda path: path.exists()
        and path.read_text(encoding="utf-8").strip() == "ok payload",
        output_validation_grace_seconds=0.0,
    )
    result = _ExecutionResult(code=0, stdout_text="ok payload", stderr_text="")
    log_sections = ["header"]

    rc = runner_success_mod.handle_successful_attempt_core(
        result=result,
        output_file=output_file,
        log_file=log_file,
        deps=deps,
        log_sections=log_sections,
        default_validate_fn=lambda _path: False,
        monotonic_fn=lambda: 100.0,
    )

    assert rc == 0
    assert output_file.read_text(encoding="utf-8") == "ok payload"
    assert "recovered" in log_file.read_text(encoding="utf-8").lower()


def test_core_models_normalized_issue_payload_round_trip() -> None:
    issue = core_models_mod.NormalizedBatchIssue(
        dimension="naming_quality",
        identifier="id1",
        summary="Rename ambiguous var",
        confidence="high",
        suggestion="Use explicit names",
        related_files=["src/a.py"],
        evidence=["line 10 uses x"],
        impact_scope="module",
        fix_scope="single_edit",
        reasoning="Clear naming improves comprehension",
        evidence_lines=[10],
    )
    payload = issue.to_payload()
    assert payload["identifier"] == "id1"
    assert payload["reasoning"].startswith("Clear")
    assert payload["evidence_lines"] == [10]


def test_core_parse_helpers_handle_selection_and_payload_extraction() -> None:
    assert core_parse_mod.parse_batch_selection(None, 3) == [0, 1, 2]
    assert core_parse_mod.parse_batch_selection("1, 3, 1", 3) == [0, 2]

    logs: list[str] = []
    payload = core_parse_mod.extract_json_payload(
        'prefix {"assessments": {}, "issues": []} suffix',
        log_fn=logs.append,
    )
    assert payload == {"assessments": {}, "issues": []}
    assert (
        core_parse_mod.extract_json_payload("no json here", log_fn=logs.append) is None
    )
    assert logs


def test_core_merge_support_issue_merge_and_scoring_helpers() -> None:
    issues = [{"dimension": "naming_quality"}, {"dimension": "naming_quality"}]
    notes = {"naming_quality": {"evidence": ["a", "b"]}}
    assert (
        merge_support_mod.assessment_weight(
            dimension="naming_quality",
            issues=issues,
            dimension_notes=notes,
        )
        == 5.0
    )

    existing = {
        "dimension": "naming_quality",
        "identifier": "id1",
        "summary": "short summary",
        "suggestion": "rename",
        "related_files": ["src/a.py"],
        "evidence": ["e1"],
    }
    incoming = {
        "dimension": "naming_quality",
        "identifier": "id1",
        "summary": "longer summary with details",
        "suggestion": "rename variable and update call sites",
        "related_files": ["src/a.py", "src/b.py"],
        "evidence": ["e2"],
    }
    assert batch_merge_mod._should_merge_issues(existing, incoming) is True
    batch_merge_mod._merge_issue_payload(existing, incoming)
    assert set(existing["related_files"]) == {"src/a.py", "src/b.py"}
    assert "longer summary" in existing["summary"]

    key = merge_support_mod._issue_identity_key(
        {"dimension": "naming_quality", "identifier": "id-123", "summary": "summary"}
    )
    assert key == "naming_quality::id-123"

    components = merge_support_mod._compute_abstraction_components(
        merged_assessments={"abstraction_fitness": 70.0},
        abstraction_axis_scores={"cohesion": [(60.0, 2.0)], "locality": [(90.0, 1.0)]},
        abstraction_sub_axes=("cohesion", "locality"),
        abstraction_component_names={"cohesion": "Cohesion", "locality": "Locality"},
    )
    assert components == {"Cohesion": 60.0, "Locality": 90.0}


def test_core_normalize_helpers_and_batch_normalization() -> None:
    assert core_normalize_mod._low_score_dimensions(
        {"naming_quality": 59.9, "design_coherence": 80.0}
    ) == {"naming_quality", "design_coherence"}

    judgment = core_normalize_mod._validate_dimension_judgment(
        "naming_quality",
        {
            "strengths": ["clear modules"],
            "dimension_character": "mostly local",
            "score_rationale": "x" * 60,
        },
        log_fn=lambda _msg: None,
    )
    assert judgment is not None
    assert judgment["dimension_character"] == "mostly local"

    aliased_judgment = core_normalize_mod._validate_dimension_judgment(
        "logic_clarity",
        {
            "dimension_character": "judgment character is required",
            "score_rationale": "y" * 60,
        },
        log_fn=lambda _msg: None,
    )
    assert aliased_judgment is not None
    assert aliased_judgment["dimension_character"] == "judgment character is required"

    quality = core_normalize_mod._compute_batch_quality(
        assessments={"naming_quality": 80.0},
        issues=[
            core_models_mod.NormalizedBatchIssue(
                dimension="naming_quality",
                identifier="id1",
                summary="s",
                confidence="high",
                suggestion="x",
                related_files=["src/a.py"],
                evidence=["e"],
                impact_scope="module",
                fix_scope="single_edit",
            )
        ],
        dimension_notes={"naming_quality": {"evidence": ["e1", "e2"]}},
        high_score_missing_issue_note=0.0,
        expected_dimensions=1,
    )
    assert quality["dimension_coverage"] == 1.0
    assert quality["evidence_density"] == 2.0

    payload = {
        "assessments": {"naming_quality": 80},
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "id1",
                "summary": "Rename variable",
                "confidence": "high",
                "suggestion": "Use explicit name",
                "related_files": ["src/a.py"],
                "evidence": ["line 10"],
                "impact_scope": "module",
                "fix_scope": "single_edit",
            }
        ],
        "dimension_notes": {
            "naming_quality": {
                "evidence": ["line 10"],
                "impact_scope": "module",
                "fix_scope": "single_edit",
            }
        },
        "dimension_judgment": {
            "naming_quality": {
                "strengths": ["Naming conventions are mostly consistent."],
                "dimension_character": "Inconsistency is isolated to a few ambiguous identifiers.",
                "score_rationale": (
                    "Most modules use descriptive names and consistent style, but a handful of "
                    "generic names still obscure intent at handoff points. "
                    "That keeps the score strong but not top-tier."
                ),
            }
        },
    }
    assessments, issues_payload, notes_payload, judgments, norm_quality, _ctx = (
        core_normalize_mod.normalize_batch_result(
            payload,
            {"naming_quality"},
            max_batch_issues=5,
            abstraction_sub_axes=("cohesion",),
            log_fn=lambda _msg: None,
        )
    )
    assert assessments == {"naming_quality": 80.0}
    assert len(issues_payload) == 1
    assert "naming_quality" in notes_payload
    assert "naming_quality" in judgments
    assert "dimension_coverage" in norm_quality


def test_external_helpers_session_and_time_formatting() -> None:
    now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
    assert external_mod._iso_seconds(now) == "2026-03-09T12:00:00+00:00"
    sid = external_mod._session_id()
    assert sid.startswith("ext_")
    assert len(sid) > 10
