"""Synthetic retry/replay boundaries for immutable multi-dimensional packets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.app.commands.review import cmd
from desloppify.app.commands.review.batch import execution_phases, orchestrator, scope
from desloppify.app.commands.review.batch.core_parse import parse_batch_selection
from desloppify.app.commands.review.runner_packets import (
    build_batch_import_provenance,
    selected_batch_indexes,
)
from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.cli import create_parser


def _packet(dimensions, groups=None):
    return {
        "dimensions": dimensions,
        "investigation_batches": [
            {"name": f"slice-{index + 1}", "dimensions": group}
            for index, group in enumerate(groups or [[dim] for dim in dimensions])
        ],
    }


def _payload(dimensions):
    return {
        "assessments": dict.fromkeys(dimensions, 75.0),
        "issues": [
            {
                "dimension": dim,
                "identifier": f"synthetic_{dim}",
                "summary": "Synthetic fixture leaves a contract implicit.",
                "confidence": "high",
                "suggestion": "Make the fixture contract explicit.",
                "related_files": ["fixture.py"],
                "evidence": ["The synthetic fixture has an implicit boundary."],
                "impact_scope": "module",
                "fix_scope": "single_edit",
            }
            for dim in dimensions
        ],
        "dimension_notes": {
            dim: {
                "evidence": ["Synthetic fixture has a clear function boundary."],
                "impact_scope": "module",
                "fix_scope": "single_edit",
            }
            for dim in dimensions
        },
        "dimension_judgment": {
            dim: {
                "dimension_character": "The synthetic fixture has explicit boundaries.",
                "score_rationale": "Synthetic evidence supports the assessment while leaving room for a more explicit contract.",
            }
            for dim in dimensions
        },
    }


def _write_run(tmp_path, packet, recorded, raw_results):
    tmp_path.mkdir(parents=True, exist_ok=True)
    blind = tmp_path / "blind.json"
    immutable = tmp_path / "packet.json"
    blind.write_text(json.dumps(packet))
    immutable.write_text(json.dumps(packet))
    results = tmp_path / "results"
    results.mkdir()
    for index, raw in raw_results.items():
        (results / f"batch-{index}.raw.txt").write_text(raw)
    (tmp_path / "run_summary.json").write_text(
        json.dumps(
            {
                "runner": "codex",
                "run_stamp": "synthetic",
                "selected_batches": recorded,
                "blind_packet": str(blind),
                "immutable_packet": str(immutable),
            }
        )
    )
    return blind, immutable


def _capture_imports(monkeypatch):
    imports = []

    def capture(path, *_args, import_config, **_kwargs):
        assert import_config.trusted_assessment_source is True
        imports.append((json.loads(Path(path).read_text()), import_config))

    monkeypatch.setattr(orchestrator, "_do_import", capture)
    monkeypatch.setattr(
        orchestrator,
        "scored_dimensions_for_lang",
        lambda _lang: ["naming_quality", "logic_clarity"],
    )
    return imports, capture


def _replay(run_dir, **kwargs):
    orchestrator.do_import_run(
        str(run_dir),
        state={},
        lang=SimpleNamespace(name="python"),
        state_file=str(run_dir / "state.json"),
        **kwargs,
    )


def _prepare(tmp_path, packet, selection, monkeypatch):
    monkeypatch.setattr(
        execution_phases,
        "scored_dimensions_for_lang",
        lambda _lang: ["naming_quality", "logic_clarity"],
    )
    args = SimpleNamespace(path=".", dimensions=None, only_batches=selection)
    deps = SimpleNamespace(
        load_or_prepare_packet_fn=lambda _request: (
            packet,
            tmp_path / "packet.json",
            tmp_path / "blind.json",
        ),
        selected_batch_indexes_fn=lambda args, *, batch_count: selected_batch_indexes(
            raw_selection=args.only_batches,
            batch_count=batch_count,
            parse_fn=parse_batch_selection,
            colorize_fn=lambda text, _tone: text,
        ),
        colorize_fn=lambda text, _tone: text,
    )
    return execution_phases._prepare_packet_scope(
        args=args,
        state={},
        lang=SimpleNamespace(name="python"),
        config={},
        deps=deps,
        stamp="synthetic",
    )


@pytest.mark.parametrize(
    "selection, expected",
    [(None, ["naming_quality", "custom_dimension"]), ("2", ["custom_dimension"])],
)
def test_live_scope_comes_from_selected_exploded_batches(
    tmp_path, monkeypatch, selection, expected
):
    packet = _packet(
        ["naming_quality", "logic_clarity", "custom_dimension"],
        [["naming_quality", "custom_dimension"]],
    )
    prepared = _prepare(tmp_path, packet, selection, monkeypatch)
    assert prepared.packet_dimensions == expected
    assert packet["dimensions"] == [
        "naming_quality",
        "logic_clarity",
        "custom_dimension",
    ]


@pytest.mark.parametrize("selection", [None, "2"])
def test_replay_original_selected_run_or_explicit_slice(
    tmp_path, monkeypatch, selection
):
    packet = _packet(["naming_quality", "logic_clarity", "custom_dimension"])
    blind, immutable = _write_run(
        tmp_path, packet, [2], {2: json.dumps(_payload(["logic_clarity"]))}
    )
    imports, _capture = _capture_imports(monkeypatch)
    before = {
        path: path.read_bytes()
        for path in [blind, immutable, tmp_path / "run_summary.json"]
    }
    _replay(tmp_path, **({"only_batches": selection} if selection else {}))
    merged, policy = imports[0]
    assert policy.allow_partial is False
    assert merged["assessment_coverage"]["selected_dimensions"] == ["logic_clarity"]
    assert merged["provenance"]["batch_indexes"] == [2]
    assert (
        merged["provenance"]["packet_sha256"]
        == hashlib.sha256(blind.read_bytes()).hexdigest()
    )
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("unselected", ["malformed", "missing"])
def test_replay_does_not_read_unselected_results(tmp_path, monkeypatch, unselected):
    packet = _packet(["naming_quality", "logic_clarity"])
    raw = {1: json.dumps(_payload(["naming_quality"]))}
    if unselected == "malformed":
        raw[2] = "{not valid JSON"
    _write_run(tmp_path, packet, [1, 2], raw)
    imports, _capture = _capture_imports(monkeypatch)
    _replay(tmp_path, only_batches="1")
    assert imports[0][0]["assessment_coverage"]["selected_dimensions"] == [
        "naming_quality"
    ]


@pytest.mark.parametrize("selection", ["0", "-1", "4", "abc", ",", "1"])
def test_replay_rejects_invalid_or_unrecorded_selection(
    tmp_path, monkeypatch, selection
):
    packet = _packet(["naming_quality", "logic_clarity", "custom_dimension"])
    _write_run(
        tmp_path,
        packet,
        [2, 3],
        {
            1: json.dumps(_payload(["naming_quality"])),
            2: json.dumps(_payload(["logic_clarity"])),
        },
    )
    imports, _capture = _capture_imports(monkeypatch)
    with pytest.raises(PacketValidationError):
        _replay(tmp_path, only_batches=selection)
    assert imports == []


def test_replay_indexes_are_absolute_after_dimension_explosion(tmp_path, monkeypatch):
    packet = _packet(
        ["naming_quality", "custom_dimension"], [["naming_quality", "custom_dimension"]]
    )
    _write_run(
        tmp_path, packet, [1, 2], {2: json.dumps(_payload(["custom_dimension"]))}
    )
    imports, _capture = _capture_imports(monkeypatch)
    _replay(tmp_path, only_batches="2,2")
    assert imports[0][0]["assessment_coverage"]["selected_dimensions"] == [
        "custom_dimension"
    ]
    assert imports[0][0]["provenance"]["batch_indexes"] == [2]


@pytest.mark.parametrize("selection", [None, "1,2"])
def test_selected_malformed_result_blocks_even_with_complete_dimension_coverage(
    tmp_path, monkeypatch, selection
):
    packet = _packet(["naming_quality"], [["naming_quality"], ["naming_quality"]])
    _write_run(
        tmp_path,
        packet,
        [1, 2],
        {1: json.dumps(_payload(["naming_quality"])), 2: "{bad"},
    )
    imports, _capture = _capture_imports(monkeypatch)
    with pytest.raises(CommandError, match="batch execution failed"):
        _replay(tmp_path, **({"only_batches": selection} if selection else {}))
    assert imports == []


@pytest.mark.parametrize(
    "raw", ["{bad", json.dumps({"assessments": {"naming_quality": 75}, "issues": []})]
)
def test_selected_parse_or_normalization_failure_blocks_replay(
    tmp_path, monkeypatch, raw
):
    packet = _packet(["naming_quality", "logic_clarity"])
    _write_run(
        tmp_path,
        packet,
        [1, 2],
        {1: raw, 2: json.dumps(_payload(["naming_quality", "logic_clarity"]))},
    )
    imports, _capture = _capture_imports(monkeypatch)
    with pytest.raises(CommandError, match="batch execution failed"):
        _replay(tmp_path, only_batches="1,2")
    assert imports == []


def test_selected_custom_dimension_still_requires_an_assessment(tmp_path, monkeypatch):
    packet = _packet(["naming_quality", "custom_dimension"])
    _write_run(tmp_path, packet, [1, 2], {2: json.dumps(_payload([]))})
    imports, _capture = _capture_imports(monkeypatch)
    with pytest.raises(CommandError, match="incomplete selected-dimension coverage"):
        _replay(tmp_path, only_batches="2")
    assert imports == []


def test_partial_replay_keeps_requested_scope_and_successful_provenance(
    tmp_path, monkeypatch
):
    packet = _packet(["naming_quality", "custom_dimension"])
    _write_run(tmp_path, packet, [1, 2], {1: json.dumps(_payload(["naming_quality"]))})
    imports, _capture = _capture_imports(monkeypatch)
    _replay(tmp_path, only_batches="1,2", allow_partial=True)
    merged, policy = imports[0]
    assert policy.allow_partial is True
    assert merged["assessment_coverage"]["selected_dimensions"] == [
        "naming_quality",
        "custom_dimension",
    ]
    assert merged["assessment_coverage"]["missing_selected_dimensions"] == [
        "custom_dimension"
    ]
    assert merged["provenance"]["batch_indexes"] == [1]


@pytest.mark.parametrize("selection", [None, "2"])
def test_missing_selected_files_block_strict_replay(tmp_path, monkeypatch, selection):
    packet = _packet(["naming_quality", "logic_clarity"])
    _write_run(tmp_path, packet, [1, 2], {1: json.dumps(_payload(["naming_quality"]))})
    imports, _capture = _capture_imports(monkeypatch)
    with pytest.raises(
        CommandError, match="Missing result files|No result files found"
    ):
        _replay(tmp_path, **({"only_batches": selection} if selection else {}))
    assert imports == []


@pytest.mark.parametrize("recorded", [[0], [4], [True], ["1"], "1"])
def test_malformed_recorded_selection_is_not_trusted(tmp_path, monkeypatch, recorded):
    packet = _packet(["naming_quality", "logic_clarity"])
    _write_run(
        tmp_path,
        packet,
        recorded,
        {1: json.dumps(_payload(["naming_quality", "logic_clarity"]))},
    )
    imports, _capture = _capture_imports(monkeypatch)
    with pytest.raises(CommandError):
        _replay(tmp_path)
    assert imports == []


@pytest.mark.parametrize(
    "dimensions", [[], "naming_quality", ["undeclared"], [False], [""]]
)
def test_selected_batch_must_have_declared_nonempty_dimension_scope(dimensions):
    with pytest.raises(PacketValidationError):
        scope.selected_batch_dimensions(
            batches=[{"dimensions": dimensions}],
            selected_indexes=[0],
            packet_dimensions=["naming_quality"],
        )


def test_cli_forwards_replay_selection(monkeypatch):
    args = create_parser().parse_args(
        ["review", "--import-run", "synthetic-run", "--only-batches", "2,4"]
    )
    calls = []
    monkeypatch.setattr(
        cmd, "do_import_run", lambda *_args, **kwargs: calls.append(kwargs)
    )
    cmd._run_review_mode(
        args=args,
        opts=cmd.ReviewOptions.from_args(args),
        runtime=SimpleNamespace(config={}),
        state={},
        lang=SimpleNamespace(name="python"),
        state_file="synthetic-state.json",
    )
    assert calls[0]["only_batches"] == "2,4"


def test_twenty_dimension_split_replay_and_live_retry_use_same_immutable_packet(
    tmp_path, monkeypatch
):
    dimensions = [f"synthetic_dimension_{index}" for index in range(1, 21)]
    packet = _packet(dimensions)
    successful = [index for index in range(1, 21) if index != 8]
    raw = {index: json.dumps(_payload([dimensions[index - 1]])) for index in successful}
    raw[8] = "{malformed fixture"
    blind, immutable = _write_run(tmp_path, packet, list(range(1, 21)), raw)
    before = {
        path: path.read_bytes()
        for path in [
            blind,
            immutable,
            tmp_path / "run_summary.json",
            *sorted((tmp_path / "results").iterdir()),
        ]
    }
    imports, capture = _capture_imports(monkeypatch)
    with pytest.raises(CommandError):
        _replay(tmp_path)
    assert imports == []
    _replay(tmp_path, only_batches=",".join(map(str, successful)))
    prepared_scope = _prepare(tmp_path, packet, "8", monkeypatch)
    payload = _payload([dimensions[7]])
    prepared = SimpleNamespace(
        **vars(prepared_scope),
        runner="codex",
        stamp="synthetic-retry",
        run_dir=tmp_path,
        allow_partial=False,
        state={},
        lang=SimpleNamespace(name="python"),
        config={},
        append_run_log=lambda _text: None,
        args=SimpleNamespace(scan_after_import=False),
    )
    deps = SimpleNamespace(
        merge_batch_results_fn=lambda _results: payload,
        build_import_provenance_fn=build_batch_import_provenance,
        safe_write_text_fn=lambda path, text: path.write_text(text),
        colorize_fn=lambda text, _tone: text,
        do_import_fn=capture,
        run_followup_scan_fn=lambda **_kwargs: 0,
    )
    execution_phases.merge_and_import_batch_run(
        prepared=prepared,
        executed=SimpleNamespace(
            batch_results=[payload], successful_indexes=[7], failure_set=set()
        ),
        state_file=tmp_path / "state.json",
        deps=deps,
    )
    assert len(imports) == 2
    assert set().union(
        *(set(merged["assessments"]) for merged, _policy in imports)
    ) == set(dimensions)
    assert imports[0][0]["assessment_coverage"]["selected_dimensions"] == [
        dimensions[index - 1] for index in successful
    ]
    assert imports[1][0]["assessment_coverage"]["selected_dimensions"] == [
        dimensions[7]
    ]
    assert all(policy.allow_partial is False for _merged, policy in imports)
    assert all(
        merged["provenance"]["packet_sha256"]
        == hashlib.sha256(blind.read_bytes()).hexdigest()
        for merged, _policy in imports
    )
    assert all(path.read_bytes() == data for path, data in before.items())
