"""Regression tests for review packet parity and shared builder delegation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from desloppify.app.commands.review.batch.orchestrator import _load_or_prepare_packet
from desloppify.app.commands.review.external import _prepare_packet_snapshot
from desloppify.app.commands.review.prepare import do_prepare
from desloppify.state import empty_state as build_empty_state


def _args(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        path=str(path),
        dimensions=None,
        retrospective=True,
        retrospective_max_issues=7,
        retrospective_max_batch_items=5,
        packet=None,
    )


def _fake_setup(*_args, **_kwargs):
    return SimpleNamespace(name="python"), ["src/app.py", "src/utils.py"]


def _fake_holistic_prepare(_path, lang_run, _state, *, options):
    dimensions = (
        list(options.dimensions)
        if isinstance(options.dimensions, list)
        else ["naming_quality", "logic_clarity"]
    )
    return {
        "command": "review",
        "mode": "holistic",
        "language": lang_run.name,
        "dimensions": dimensions,
        "system_prompt": "mock prompt",
        "investigation_batches": [
            {
                "name": "naming batch",
                "dimensions": [dimensions[0]],
                "files_to_read": ["src/app.py"],
                "why": "test",
            }
        ],
        "total_files": 2,
        "workflow": ["inspect files"],
    }


def test_review_packet_shared_fields_match_across_modes(tmp_path):
    args = _args(tmp_path)
    state = build_empty_state()
    lang = SimpleNamespace(name="python")
    config = {
        "target_strict_score": 98,
        "noise_budget": 10,
        "review_batch_max_files": 17,
    }
    captured_prepare: dict = {}

    with (
        patch(
            "desloppify.app.commands.review.packet.build.narrative_mod.compute_narrative",
            return_value={"headline": "stable narrative"},
        ),
        patch(
            "desloppify.app.commands.review.prepare.setup_lang_concrete",
            side_effect=_fake_setup,
        ),
        patch(
            "desloppify.app.commands.review.batch.orchestrator._setup_lang",
            side_effect=_fake_setup,
        ),
        patch(
            "desloppify.app.commands.review.external.setup_lang_concrete",
            side_effect=_fake_setup,
        ),
        patch(
            "desloppify.app.commands.review.prepare.review_mod.prepare_holistic_review",
            side_effect=_fake_holistic_prepare,
        ),
        patch(
            "desloppify.app.commands.review.batch.orchestrator.review_mod.prepare_holistic_review",
            side_effect=_fake_holistic_prepare,
        ),
        patch(
            "desloppify.app.commands.review.external.review_mod.prepare_holistic_review",
            side_effect=_fake_holistic_prepare,
        ),
        patch(
            "desloppify.app.commands.review.prepare.write_query",
            side_effect=lambda payload: captured_prepare.update(payload),
        ),
        patch(
            "desloppify.app.commands.review.prepare._print_prepare_summary",
            return_value=None,
        ),
        patch(
            "desloppify.app.commands.review.batch.orchestrator.write_query_best_effort",
            return_value=None,
        ),
        patch(
            "desloppify.app.commands.review.external.write_query",
            return_value=None,
        ),
        patch(
            "desloppify.app.commands.review.batch.orchestrator.write_review_packet_snapshot",
            return_value=(tmp_path / "batch.packet.json", tmp_path / "batch.blind.json"),
        ),
        patch(
            "desloppify.app.commands.review.external.write_review_packet_snapshot",
            return_value=(tmp_path / "ext.packet.json", tmp_path / "ext.blind.json"),
        ),
    ):
        do_prepare(args, state, lang, None, config=config)
        packet_batch, _batch_packet_path, _batch_blind_path = _load_or_prepare_packet(
            args,
            state=state,
            lang=lang,
            config=config,
            stamp="20260304_000000",
        )
        packet_external, _ext_packet_path, _ext_blind_path = _prepare_packet_snapshot(
            args,
            state,
            lang,
            config=config,
        )

    shared_fields = [
        "command",
        "mode",
        "language",
        "dimensions",
        "system_prompt",
        "investigation_batches",
        "total_files",
        "workflow",
        "config",
        "narrative",
    ]
    for field in shared_fields:
        assert captured_prepare[field] == packet_batch[field] == packet_external[field]

    assert "target_strict_score" not in captured_prepare["config"]
    assert captured_prepare["next_command"] == (
        "desloppify review --prepare --retrospective"
        " --retrospective-max-issues 7 --retrospective-max-batch-items 5"
    )
    assert packet_batch["next_command"] == (
        "desloppify review --run-batches --runner codex --parallel --scan-after-import"
        " --retrospective --retrospective-max-issues 7 --retrospective-max-batch-items 5"
    )
    assert packet_external["next_command"] == (
        "desloppify review --external-submit --session-id <id> --import <file>"
        " --retrospective --retrospective-max-issues 7 --retrospective-max-batch-items 5"
    )


def test_review_modes_delegate_to_shared_builder(tmp_path):
    args = _args(tmp_path)
    state = build_empty_state()
    lang = SimpleNamespace(name="python")
    payload = {
        "command": "review",
        "mode": "holistic",
        "total_files": 1,
        "investigation_batches": [],
        "workflow": [],
        "config": {},
        "narrative": {},
    }

    with (
        patch(
            "desloppify.app.commands.review.prepare.build_review_packet_payload",
            return_value=dict(payload),
        ) as prepare_builder,
        patch(
            "desloppify.app.commands.review.prepare.write_query",
            return_value=None,
        ),
        patch(
            "desloppify.app.commands.review.prepare._print_prepare_summary",
            return_value=None,
        ),
    ):
        do_prepare(args, state, lang, None, config={})
    assert prepare_builder.call_count == 1
    assert (
        prepare_builder.call_args.kwargs["next_command"]
        == "desloppify review --prepare --retrospective"
        " --retrospective-max-issues 7 --retrospective-max-batch-items 5"
    )

    with (
        patch(
            "desloppify.app.commands.review.batch.orchestrator.build_review_packet_payload",
            return_value=dict(payload),
        ) as batch_builder,
        patch(
            "desloppify.app.commands.review.batch.orchestrator.write_query_best_effort",
            return_value=None,
        ),
        patch(
            "desloppify.app.commands.review.batch.orchestrator.write_review_packet_snapshot",
            return_value=(tmp_path / "packet.json", tmp_path / "blind.json"),
        ),
    ):
        _load_or_prepare_packet(
            args,
            state=state,
            lang=lang,
            config={},
            stamp="20260304_000000",
        )
    assert batch_builder.call_count == 1
    assert (
        batch_builder.call_args.kwargs["next_command"]
        == "desloppify review --run-batches --runner codex --parallel --scan-after-import"
        " --retrospective --retrospective-max-issues 7 --retrospective-max-batch-items 5"
    )

    with (
        patch(
            "desloppify.app.commands.review.external.build_review_packet_payload",
            return_value=dict(payload),
        ) as external_builder,
        patch(
            "desloppify.app.commands.review.external.write_query",
            return_value=None,
        ),
        patch(
            "desloppify.app.commands.review.external.write_review_packet_snapshot",
            return_value=(tmp_path / "ext.packet.json", tmp_path / "ext.blind.json"),
        ),
    ):
        _prepare_packet_snapshot(
            args,
            state,
            lang,
            config={},
        )
    assert external_builder.call_count == 1
    assert (
        external_builder.call_args.kwargs["next_command"]
        == "desloppify review --external-submit --session-id <id> --import <file>"
        " --retrospective --retrospective-max-issues 7 --retrospective-max-batch-items 5"
    )
