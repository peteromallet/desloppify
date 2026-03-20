"""Direct tests for shared triage prompt instruction text helpers."""

from __future__ import annotations

import desloppify.app.commands.plan.triage.runner.stage_prompts_instruction_shared as shared_mod


def _assert_sections(text: str, sections: tuple[str, ...]) -> None:
    for section in sections:
        assert f"## {section}" in text


def test_triage_prompt_preamble_mode_contracts() -> None:
    output_only = shared_mod.triage_prompt_preamble("output_only")
    self_record = shared_mod.triage_prompt_preamble("self_record")

    _assert_sections(output_only, ("Standards", "Output Contract"))
    _assert_sections(self_record, ("Standards",))

    # Both modes are templates and should keep stage/repo placeholders.
    for rendered in (output_only, self_record):
        assert "**{stage}**" in rendered
        assert "Repo root: {repo_root}" in rendered

    # Output-only mode must be read-only guidance with explicit no-mutation rules.
    assert "Do NOT run any `desloppify` commands." in output_only
    assert "Do NOT mutate `plan.json` directly or indirectly." in output_only
    assert "record your work" not in output_only

    # Self-record mode must describe stage-scoped CLI recording behavior.
    assert "record your work" in self_record
    assert "Only run commands for YOUR stage ({stage})" in self_record
    assert "{cli_command}" in self_record


def test_render_cli_reference_substitutes_cli_command() -> None:
    rendered = shared_mod.render_cli_reference(cli_command="dx")
    _assert_sections(
        rendered,
        ("CLI Command Reference", "Stage recording", "Cluster management", "Skip/dismiss", "Effort tags"),
    )

    for stage in shared_mod._STAGES:
        assert f"dx plan triage --stage {stage}" in rendered

    for command_family in (
        "dx plan cluster create",
        "dx plan cluster add",
        "dx plan cluster update",
        "dx plan cluster show",
        "dx plan cluster list",
        "dx plan skip --permanent",
    ):
        assert command_family in rendered

    command_lines = [
        line.strip()
        for line in rendered.splitlines()
        if line.strip().startswith("dx ")
    ]
    assert command_lines
    assert all(line.startswith("dx ") for line in command_lines)
    assert "desloppify plan " not in rendered
    assert "reviewed" in rendered
    assert "not gaming" in rendered


def test_shared_stage_constants_cover_all_expected_stages() -> None:
    assert shared_mod._STAGES == (
        "strategize",
        "observe",
        "reflect",
        "organize",
        "enrich",
        "sense-check",
    )
