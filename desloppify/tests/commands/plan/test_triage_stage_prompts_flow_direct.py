"""Direct tests for triage stage prompt and enrich/sense flow split modules."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import desloppify.app.commands.plan.triage.runner.stage_prompts_instruction_blocks as prompts_instructions_mod
import desloppify.app.commands.plan.triage.runner.stage_prompts_observe as prompts_observe_mod
import desloppify.app.commands.plan.triage.runner.stage_prompts_sense as prompts_sense_mod
import desloppify.app.commands.plan.triage.runner.stage_prompts_validation as prompts_validation_mod
import desloppify.app.commands.plan.triage.stages.enrich as stage_flow_enrich_mod
import desloppify.app.commands.plan.triage.stages.sense_check as stage_flow_sense_mod


def _assert_sections(text: str, sections: tuple[str, ...]) -> None:
    for section in sections:
        assert f"## {section}" in text


class _Services:
    def __init__(self, plan: dict):
        self.plan = plan
        self.save_calls = 0
        self.logs: list[dict] = []

    def command_runtime(self, _args) -> SimpleNamespace:
        return SimpleNamespace(state={"issues": {}})

    def load_plan(self) -> dict:
        return self.plan

    def save_plan(self, _plan: dict) -> None:
        self.save_calls += 1

    def append_log_entry(self, _plan: dict, _action: str, **kwargs) -> None:
        self.logs.append(kwargs)


def test_stage_prompt_instruction_blocks_and_validation_requirements() -> None:
    stage_prompts = {
        "OBSERVE": prompts_instructions_mod._observe_instructions(),
        "REFLECT": prompts_instructions_mod._reflect_instructions(),
        "ORGANIZE": prompts_instructions_mod._organize_instructions(),
        "ENRICH": prompts_instructions_mod._enrich_instructions(),
        "SENSE-CHECK": prompts_instructions_mod._sense_check_instructions(),
    }

    for stage_name, prompt in stage_prompts.items():
        assert f"## {stage_name} Stage Instructions" in prompt

    for stage in ("observe", "reflect", "organize", "enrich", "sense-check"):
        text = prompts_validation_mod._validation_requirements(stage)
        assert text.startswith("## Validation Requirements")


def test_observe_and_sense_prompt_builders_include_expected_context(tmp_path) -> None:
    observe = prompts_observe_mod.build_observe_batch_prompt(
        batch_index=1,
        total_batches=2,
        dimension_group=["naming_quality"],
        issues_subset={
            "review::src/a.py::abcdef12": {
                "title": "Naming issue",
                "description": "rename to clear name",
                "detail": {"dimension": "naming_quality", "file_path": "src/a.py"},
            },
            "review::.::holistic::naming_quality::task_param_bag": {
                "title": "Holistic naming issue",
                "description": "shared task parameter bag hides intent",
                "detail": {
                    "dimension": "naming_quality",
                    "summary_hash": "1a2b3c4d",
                },
            },
        },
        repo_root=tmp_path,
    )

    _assert_sections(observe, ("Issues to Verify", "OBSERVE Batch Instructions", "IMPORTANT: Output Rules"))
    assert "observe batch 1/2" in observe
    assert "naming_quality" in observe
    assert f"Repo root: {tmp_path}" in observe
    assert "[abcdef12]" in observe
    assert "[1a2b3c4d]" in observe
    for required_field in ("- hash:", "verdict:", "verdict_reasoning:", "files_read:", "recommendation:"):
        assert required_field in observe
    assert "Do NOT run any `desloppify` commands" in observe

    plan = {
        "clusters": {
            "cluster-a": {
                "issue_ids": ["id1"],
                "action_steps": [
                    {
                        "title": "Update handler",
                        "detail": "Edit src/a.py and rename fields",
                        "issue_refs": ["id1"],
                        "effort": "small",
                    }
                ],
            }
        }
    }
    content_prompt = prompts_sense_mod.build_sense_check_content_prompt(
        cluster_name="cluster-a",
        plan=plan,
        repo_root=tmp_path,
    )
    _assert_sections(
        content_prompt,
        ("Your job", "What to check and fix", "How to report fixes", "What NOT to do", "Current Steps", "Output"),
    )
    structure_prompt = prompts_sense_mod.build_sense_check_structure_prompt(
        plan=plan,
        repo_root=tmp_path,
    )

    _assert_sections(
        structure_prompt,
        ("Your job", "What to check and fix", "What NOT to do", "Clusters", "Output"),
    )

    assert "cluster `cluster-a`" in content_prompt
    assert "Do NOT run any `desloppify` commands" in content_prompt
    assert "Update handler" in content_prompt
    assert "cross-cluster dependencies" in structure_prompt
    assert "Do NOT run any `desloppify` commands" in structure_prompt
    assert "SHARED FILES" in structure_prompt
    assert "MISSING CASCADE" in structure_prompt
    assert "CIRCULAR DEPS" in structure_prompt
    assert "desloppify plan cluster update" not in structure_prompt


def test_run_stage_enrich_handles_no_queue_and_records_stage(tmp_path, capsys) -> None:
    args = argparse.Namespace(report="x" * 120, attestation=None)

    empty_services = _Services(plan={})
    stage_flow_enrich_mod.run_stage_enrich(
        args,
        services=empty_services,
        deps=stage_flow_enrich_mod.EnrichStageDeps(
            has_triage_in_queue=lambda _plan: False,
            require_organize_stage_for_enrich=lambda _stages: True,
            underspecified_steps=lambda _plan: [],
            steps_with_bad_paths=lambda _plan, _root: [],
            steps_without_effort=lambda _plan: [],
            enrich_report_or_error=lambda report: report,
            resolve_reusable_report=lambda report, _existing: (report, False),
            record_enrich_stage=lambda *_a, **_k: [],
        ),
    )
    assert "nothing to enrich" in capsys.readouterr().out.lower()

    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "organize": {"confirmed_at": "2026-03-09T00:00:00+00:00"}
            }
        }
    }
    services = _Services(plan=plan)

    def _record_enrich(stages: dict, *, report: str, shallow_count: int, existing_stage, is_reuse):
        stages["enrich"] = {
            "stage": "enrich",
            "report": report,
            "timestamp": "2026-03-09T00:00:00+00:00",
        }
        return []

    stage_flow_enrich_mod.run_stage_enrich(
        args,
        services=services,
        deps=stage_flow_enrich_mod.EnrichStageDeps(
            has_triage_in_queue=lambda _plan: True,
            require_organize_stage_for_enrich=lambda _stages: True,
            underspecified_steps=lambda _plan: [],
            steps_with_bad_paths=lambda _plan, _root: [],
            steps_without_effort=lambda _plan: [],
            enrich_report_or_error=lambda report: report,
            resolve_reusable_report=lambda report, _existing: (report, False),
            record_enrich_stage=_record_enrich,
            get_project_root=lambda: tmp_path,
            print_user_message=lambda _msg: None,
        ),
    )
    out = capsys.readouterr().out
    assert "Enrich stage recorded" in out
    assert "enrich" in plan["epic_triage_meta"]["triage_stages"]
    assert services.save_calls >= 2


def test_record_sense_stage_and_run_stage_sense_check(tmp_path, capsys, monkeypatch) -> None:
    stages: dict = {}
    monkeypatch.setattr(
        "desloppify.app.commands.plan.triage.stages.records.utc_now",
        lambda: "2026-03-09T00:00:00+00:00",
    )
    monkeypatch.setattr(
        "desloppify.app.commands.plan.triage.stages.records.cascade_clear_later_confirmations",
        lambda _stages, _name: ["sense-check"],
    )
    cleared = stage_flow_sense_mod.record_sense_check_stage(
        stages,
        report="x" * 120,
        existing_stage=None,
        is_reuse=False,
    )
    assert stages["sense-check"]["stage"] == "sense-check"
    assert cleared == ["sense-check"]

    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "enrich": {"confirmed_at": "2026-03-09T00:00:00+00:00"}
            }
        }
    }
    services = _Services(plan=plan)
    args = argparse.Namespace(report="Verified all steps: src/services/main.ts lines 10-50 match descriptions. Structure and content accurate. " + "y" * 30)

    def _record_sense(stages: dict, *, report: str, existing_stage, is_reuse, value_targets=None):
        stages["sense-check"] = {
            "stage": "sense-check",
            "report": report,
            "timestamp": "2026-03-09T00:00:00+00:00",
        }
        return []

    stage_flow_sense_mod.run_stage_sense_check(
        args,
        services=services,
        deps=stage_flow_sense_mod.SenseCheckStageDeps(
            has_triage_in_queue=lambda _plan: True,
            resolve_reusable_report=lambda report, _existing: (report, False),
            record_sense_check_stage=_record_sense,
            get_project_root=lambda: tmp_path,
            underspecified_steps=lambda _plan: [],
            steps_missing_issue_refs=lambda _plan: [],
            steps_with_bad_paths=lambda _plan, _root: [],
            steps_with_vague_detail=lambda _plan, _root: [],
            steps_without_effort=lambda _plan: [],
        ),
    )
    out = capsys.readouterr().out
    assert "Sense-check stage recorded" in out
    assert "sense-check" in plan["epic_triage_meta"]["triage_stages"]
    assert services.save_calls >= 2
