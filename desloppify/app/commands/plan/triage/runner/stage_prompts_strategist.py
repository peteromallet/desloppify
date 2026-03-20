"""Prompt builder for the strategize stage."""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.engine._plan.triage.strategist_data import StrategistInput


def _json_block(payload: object) -> str:
    return "```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```"


def build_strategist_prompt(
    strategist_input: StrategistInput,
    *,
    repo_root: Path,
    mode: str = "output_only",
) -> str:
    """Build the LLM prompt for the strategize stage."""
    score = strategist_input.score_trajectory
    parts = [
        "You are a Big Picture Strategist.",
        "Analyze cross-cycle codebase health history and produce strategic guidance for the upcoming triage cycle.",
        f"Repo root: {repo_root}",
        "",
        "## Job",
        "- Read the structured history below.",
        "- Detect strategic mistakes that the per-stage triage flow cannot see on its own.",
        "- Focus on rework loops, score-neutral churn, dimension neglect, skip-heavy execution, and growing wontfix debt.",
        "- Produce valid JSON only. No prose outside the JSON object.",
        "",
        "## Score Trajectory",
        _json_block(
            {
                "strict_scores": score.strict_scores,
                "strict_delta": score.strict_delta,
                "trend": score.trend,
                "best_scan_delta": score.best_scan_delta,
                "worst_scan_delta": score.worst_scan_delta,
            }
        ),
        "",
        "## Structured History",
        _json_block(strategist_input.to_prompt_payload()),
        "",
        "## Anti-Pattern Checklist",
        "- repeated refactoring of the same area",
        "- dimension stagnation despite investment",
        "- score-neutral churn",
        "- neglected high-headroom dimensions",
        "- growing wontfix debt",
        "- skip-heavy execution",
        "",
        "## Output Contract",
        "Return a JSON object with these keys:",
        '- `computed_at`: ISO timestamp',
        '- `lookback_scans`: integer',
        '- `focus_dimensions`: list of `{name, reason, headroom, trend}`',
        '- `avoid_areas`: list of `{name, reason, type}`',
        '- `rework_warnings`: list of `{dimension, resolved, new_open, files}`',
        '- `file_churn_hotspots`: list of `{file, count, detectors}`',
        '- `stagnant_dimensions`: list of strings',
        '- `debt_trend`: `"growing" | "stable" | "shrinking"`',
        '- `score_trend`: `"improving" | "stable" | "declining"`',
        '- `momentum_dimensions`: list of strings',
        '- `executive_summary`: 2-3 paragraph big-picture briefing',
        '- `observe_guidance`: prose for observe',
        '- `reflect_guidance`: prose for reflect',
        '- `organize_guidance`: prose for organize',
        '- `sense_check_guidance`: prose for sense-check value judgment',
        '- `anti_patterns`: list of `{type, description, evidence}`',
        '- `strategic_issues` (optional): list of `{identifier, summary, priority, recommendation, dimensions_affected}`',
        '  - `identifier`: short kebab-case id (e.g., "rework-loop-naming")',
        '  - `summary`: one-line description of the strategic concern',
        '  - `priority`: `"critical" | "high" | "medium"`',
        '  - `recommendation`: concrete recommended action',
        '  - `dimensions_affected`: list of dimension name strings',
        "",
        "When you detect score regressions, rework loops, or strategic misalignment, create "
        "strategic_issues with concrete recommendations. These will become high-priority work "
        "items at the front of the execution queue.",
        "",
        "Observe guidance should emphasize where verification effort is likely to be wasted or missed.",
        "Reflect guidance should describe focus dimensions, avoid areas, and recurring-loop constraints.",
        "Organize guidance should describe priority ordering and areas to avoid churning again.",
        "Sense-check guidance should call out rework risks and value traps.",
    ]
    if mode == "self_record":
        parts.append("")
        parts.append("The orchestrator will record the JSON for you. Do not run triage commands.")
    return "\n".join(parts)


__all__ = ["build_strategist_prompt"]
