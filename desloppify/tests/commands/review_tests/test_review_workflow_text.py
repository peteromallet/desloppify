"""Unit tests for shared review workflow guidance text."""

from __future__ import annotations

import desloppify.app.commands.review.workflow_text as workflow_text_mod


def test_prepare_agent_plan_lines_include_preferred_and_fallback_paths() -> None:
    lines = workflow_text_mod.prepare_agent_plan_lines("desloppify review --run-batches")
    assert lines[0].startswith("1. Preferred:")
    assert any("Cloud/manual fallback" in line for line in lines)
    assert any("Findings-only fallback" in line for line in lines)


def test_fix_review_agent_plan_lines_include_codex_and_claude_paths() -> None:
    lines = workflow_text_mod.fix_review_agent_plan_lines()
    assert any("--runner codex --parallel --scan-after-import" in line for line in lines)
    assert any("Claude cloud durable path" in line for line in lines)
    assert any("Findings-only fallback" in line for line in lines)

