"""Selected packet coverage is enforced consistently for live and replay imports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.app.commands.review.batch import (
    execution_phases,
    execution_results,
    orchestrator,
    scope,
)
from desloppify.app.commands.review.runner_packets import build_batch_import_provenance
from desloppify.base.exception_sets import CommandError
from desloppify.intelligence.review.feedback_contract import (
    TRUSTED_IMPORT_COVERAGE_OVERRIDE_FLAG,
)


def _colorize(text: str, _tone: str) -> str:
    return text


def _write(path: Path, text: str) -> None:
    path.write_text(text)


def _merged(assessed: list[str], issue_dims: list[str] | None = None) -> dict:
    return {
        "assessments": dict.fromkeys(assessed, 75.0),
        "issues": [{"dimension": dim} for dim in issue_dims or []],
    }


@pytest.mark.parametrize("allow_partial", [False, True])
def test_gate_ignores_unselected_missing_dimensions(allow_partial, capsys):
    scope.enforce_trusted_import_coverage_gate(
        missing_dims=["logic_clarity"],
        selected_dims=["naming_quality"],
        allow_partial=allow_partial,
        scan_path=".",
        colorize_fn=_colorize,
    )
    assert capsys.readouterr().out == ""


def test_gate_reports_only_missing_selected_dimensions(capsys):
    with pytest.raises(CommandError, match="incomplete selected-dimension coverage"):
        scope.enforce_trusted_import_coverage_gate(
            missing_dims=["unselected", "logic_clarity"],
            selected_dims=["naming_quality", "logic_clarity"],
            allow_partial=False,
            scan_path="src",
            colorize_fn=_colorize,
        )
    err = capsys.readouterr().err
    assert "Missing dimensions: logic_clarity" in err
    assert "--path src --dimensions logic_clarity" in err
    assert "unselected" not in err


def test_gate_preserves_explicit_override(capsys):
    scope.enforce_trusted_import_coverage_gate(
        missing_dims=["logic_clarity"],
        selected_dims=["naming_quality", "logic_clarity"],
        allow_partial=True,
        scan_path=".",
        colorize_fn=_colorize,
    )
    assert TRUSTED_IMPORT_COVERAGE_OVERRIDE_FLAG in capsys.readouterr().out


@pytest.mark.parametrize(
    ("selected", "assessed", "issue_dims", "missing_selected"),
    [
        (["naming_quality"], ["naming_quality"], [], []),
        (["custom_dimension"], [], [], ["custom_dimension"]),
        (["logic_clarity"], [], ["logic_clarity"], ["logic_clarity"]),
    ],
)
def test_merge_separates_global_notice_from_selected_assessment_coverage(
    tmp_path, capsys, selected, assessed, issue_dims, missing_selected
):
    blind = tmp_path / "blind.json"
    blind.write_text("{}")
    path, missing = execution_results.merge_and_write_results(
        merge_batch_results_fn=lambda _results: _merged(assessed, issue_dims),
        build_import_provenance_fn=build_batch_import_provenance,
        batch_results=[],
        batches=[{"dimensions": selected}],
        successful_indexes=[0],
        packet={"dimensions": selected},
        packet_dimensions=selected,
        scored_dimensions=["naming_quality", "logic_clarity"],
        scan_path=".",
        runner="codex",
        prompt_packet_path=blind,
        stamp="synthetic",
        run_dir=tmp_path,
        safe_write_text_fn=_write,
        colorize_fn=_colorize,
    )
    payload = json.loads(path.read_text())
    coverage = payload["assessment_coverage"]
    assert missing == coverage["missing_selected_dimensions"] == missing_selected
    assert coverage["missing_dimensions"] == [
        dim for dim in ["naming_quality", "logic_clarity"] if dim not in assessed
    ]
    assert "Coverage gap:" in capsys.readouterr().out
    assert payload["provenance"]["packet_sha256"] == hashlib.sha256(b"{}").hexdigest()


_PIPELINE_CASES = [
    # Explicit one-dimension review is complete even with other scored dimensions.
    (["naming_quality"], ["naming_quality"], [0], False, True),
    # A complete full packet passes; an incomplete one remains blocked.
    (
        ["naming_quality", "logic_clarity"],
        ["naming_quality", "logic_clarity"],
        [0, 1],
        False,
        True,
    ),
    (["naming_quality", "logic_clarity"], ["naming_quality"], [0, 1], False, False),
    # --only-batches does not imply the omitted packet dimensions were assessed.
    (["naming_quality", "logic_clarity"], ["naming_quality"], [0], False, False),
    (["naming_quality", "logic_clarity"], ["naming_quality"], [0], True, True),
    (
        ["naming_quality", "logic_clarity"],
        ["naming_quality", "logic_clarity"],
        [0],
        False,
        True,
    ),
    # Selected non-default dimensions require assessments too.
    (["custom_dimension"], [], [0], False, False),
    (["custom_dimension"], ["custom_dimension"], [0], False, True),
]


@pytest.mark.parametrize("mode", ["live", "replay"])
@pytest.mark.parametrize(
    ("selected", "assessed", "indexes", "allow_partial", "passes"), _PIPELINE_CASES
)
def test_live_and_replay_enforce_the_same_packet_contract(
    tmp_path, monkeypatch, mode, selected, assessed, indexes, allow_partial, passes
):
    packet = {
        "dimensions": selected,
        "investigation_batches": [
            {"name": dim, "dimensions": [dim]} for dim in selected
        ],
    }
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps(packet))
    immutable = tmp_path / "packet.json"
    immutable.write_text(json.dumps(packet))
    imports: list[dict] = []
    policies: list[object] = []

    def capture_import(path, *_args, import_config, **_kwargs):
        imports.append(json.loads(Path(path).read_text()))
        policies.append(import_config)

    payload = _merged(assessed)
    if mode == "live":
        prepared = SimpleNamespace(
            batch_results=[payload],
            batches=packet["investigation_batches"],
            packet=packet,
            packet_dimensions=selected,
            scored_dimensions=["naming_quality", "logic_clarity"],
            selected_indexes=indexes,
            scan_path=".",
            runner="codex",
            prompt_packet_path=blind,
            stamp="synthetic",
            run_dir=tmp_path,
            allow_partial=allow_partial,
            state={},
            lang=SimpleNamespace(name="python"),
            config={},
            append_run_log=lambda _text: None,
            args=SimpleNamespace(scan_after_import=False),
        )
        executed = SimpleNamespace(
            batch_results=[payload],
            successful_indexes=indexes,
            failure_set=set(),
        )
        deps = SimpleNamespace(
            merge_batch_results_fn=lambda _results: payload,
            build_import_provenance_fn=build_batch_import_provenance,
            safe_write_text_fn=_write,
            colorize_fn=_colorize,
            do_import_fn=capture_import,
            run_followup_scan_fn=lambda **_kwargs: 0,
        )

        def run():
            execution_phases.merge_and_import_batch_run(
                prepared=prepared,
                executed=executed,
                state_file=tmp_path / "state.json",
                deps=deps,
            )
    else:
        results = tmp_path / "results"
        results.mkdir()
        for index in indexes:
            (results / f"batch-{index + 1}.raw.txt").write_text("{}")
        (tmp_path / "run_summary.json").write_text(
            json.dumps(
                {
                    "runner": "codex",
                    "run_stamp": "synthetic",
                    "selected_batches": [index + 1 for index in indexes],
                    "blind_packet": str(blind),
                    "immutable_packet": str(immutable),
                }
            )
        )
        monkeypatch.setattr(
            orchestrator, "collect_batch_results", lambda **_kwargs: ([payload], [])
        )
        monkeypatch.setattr(
            orchestrator, "_merge_batch_results", lambda _results: payload
        )
        monkeypatch.setattr(
            orchestrator,
            "scored_dimensions_for_lang",
            lambda _lang: ["naming_quality", "logic_clarity"],
        )
        monkeypatch.setattr(orchestrator, "_do_import", capture_import)

        def run():
            orchestrator.do_import_run(
                str(tmp_path),
                state={},
                lang=SimpleNamespace(name="python"),
                state_file=str(tmp_path / "state.json"),
                allow_partial=allow_partial,
            )

    if passes:
        run()
        assert len(imports) == 1
        assert imports[0]["assessments"] == dict.fromkeys(assessed, 75.0)
        assert imports[0]["assessment_coverage"]["selected_dimensions"] == selected
        assert (
            imports[0]["provenance"]["packet_sha256"]
            == hashlib.sha256(blind.read_bytes()).hexdigest()
        )
        assert policies[0].trusted_assessment_source is True
        assert policies[0].allow_partial is allow_partial
    else:
        with pytest.raises(
            CommandError, match="incomplete selected-dimension coverage"
        ):
            run()
        assert imports == []
        assert policies == []
    # Both outcomes retain a replayable merged artifact and unchanged packet bytes.
    assert (tmp_path / "holistic_issues_merged.json").is_file()
    assert json.loads(blind.read_text()) == packet
