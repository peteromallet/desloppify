"""Direct tests for review packet blinding and subjective import guardrails."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.app.commands.review.import_helpers import load_import_findings_data
from desloppify.app.commands.review.prepare import do_prepare
from desloppify.app.commands.review.runner_helpers import write_packet_snapshot


def _colorize(text: str, _style: str) -> str:
    return text


def test_import_rejects_sub100_assessment_without_feedback(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {
            "naming_quality": 95,
            "logic_clarity": {"score": 92},
        },
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(SystemExit) as exc:
        load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "assessments below 100 must include explicit feedback" in err
    assert "naming_quality (95.0)" in err
    assert "logic_clarity (92.0)" in err


def test_import_accepts_sub100_assessment_with_dimension_feedback(tmp_path):
    payload = {
        "findings": [
            {
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name",
                "suggestion": "Rename to reconcile_invoice",
                "confidence": "medium",
            }
        ],
        "assessments": {"naming_quality": 95},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"]["naming_quality"] == 95


def test_import_accepts_perfect_assessment_without_feedback(tmp_path):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"]["naming_quality"] == 100


def test_write_packet_snapshot_redacts_target_from_blind_packet(tmp_path):
    packet = {
        "command": "review",
        "config": {"target_strict_score": 98, "noise_budget": 10},
        "dimensions": ["high_level_elegance"],
    }
    review_packet_dir = tmp_path / "review_packets"
    blind_path = tmp_path / "review_packet_blind.json"

    def _safe_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    packet_path, _ = write_packet_snapshot(
        packet,
        stamp="20260218_160000",
        review_packet_dir=review_packet_dir,
        blind_path=blind_path,
        safe_write_text_fn=_safe_write,
    )

    immutable_payload = json.loads(packet_path.read_text())
    blind_payload = json.loads(blind_path.read_text())

    assert immutable_payload["config"]["target_strict_score"] == 98
    assert "target_strict_score" not in blind_payload["config"]
    assert blind_payload["config"]["noise_budget"] == 10


def _make_do_prepare_args(*, total_files: int = 3, state: dict | None = None):
    """Return the common kwargs for do_prepare, overriding total_files."""
    args = SimpleNamespace(path=".", dimensions=None)
    captured: dict = {}

    def _setup_lang(_lang, _path, _config):
        return SimpleNamespace(name="python"), []

    return dict(
        args=args,
        state=state or {},
        lang=SimpleNamespace(name="python"),
        _state_path=None,
        config={},
        holistic=True,
        setup_lang_fn=_setup_lang,
        narrative_mod=SimpleNamespace(
            NarrativeContext=lambda **kwargs: SimpleNamespace(**kwargs),
            compute_narrative=lambda *_args, **_kwargs: {"headline": "x"},
        ),
        review_mod=SimpleNamespace(
            HolisticReviewPrepareOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            prepare_holistic_review=lambda *_args, **_kwargs: {
                "total_files": total_files,
                "investigation_batches": [],
                "workflow": [],
            },
        ),
        write_query_fn=lambda payload: captured.update(payload),
        colorize_fn=lambda text, _style: text,
        log_fn=lambda _msg: None,
    ), captured


def test_review_prepare_zero_files_exits_with_error(capsys):
    """Regression guard for issue #127: 0-file result must error, not silently succeed."""
    kwargs, captured = _make_do_prepare_args(total_files=0)
    with pytest.raises(SystemExit) as exc:
        do_prepare(**kwargs)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no files found" in err.lower()
    assert not captured, "query.json must not be written when no files are found"


def test_review_prepare_zero_files_hints_scan_path(capsys):
    """When state has a scan_path, the error hint mentions it."""
    kwargs, _ = _make_do_prepare_args(total_files=0, state={"scan_path": "."})
    with pytest.raises(SystemExit):
        do_prepare(**kwargs)
    err = capsys.readouterr().err
    assert "--path" in err


def test_review_prepare_query_redacts_target_score():
    captured: dict[str, object] = {}

    args = SimpleNamespace(
        path=".",
        dimensions=None,
    )
    config = {"target_strict_score": 98, "noise_budget": 10}
    lang = SimpleNamespace(name="python")

    def _setup_lang(_lang, _path, _config):
        return SimpleNamespace(name="python"), []

    def _write_query(payload: dict) -> None:
        captured.update(payload)

    do_prepare(
        args,
        state={},
        lang=lang,
        _state_path=None,
        config=config,
        holistic=True,
        setup_lang_fn=_setup_lang,
        narrative_mod=SimpleNamespace(
            NarrativeContext=lambda **kwargs: SimpleNamespace(**kwargs),
            compute_narrative=lambda *_args, **_kwargs: {"headline": "x"},
        ),
        review_mod=SimpleNamespace(
            HolisticReviewPrepareOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            prepare_holistic_review=lambda *_args, **_kwargs: {
                "total_files": 3,
                "investigation_batches": [],
                "workflow": [],
            }
        ),
        write_query_fn=_write_query,
        colorize_fn=lambda text, _style: text,
        log_fn=lambda _msg: None,
    )

    assert "config" in captured
    config = captured["config"]
    assert isinstance(config, dict)
    assert "target_strict_score" not in config
    assert config.get("noise_budget") == 10
