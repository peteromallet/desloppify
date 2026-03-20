"""Per-stage subagent prompt builders for triage runners."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root
from desloppify.engine._plan.triage.strategist_data import collect_strategist_input
from desloppify.engine._state.progression import load_progression
from desloppify.engine.plan_triage import (
    TriageInput,
    build_triage_prompt,
)

from ..services import TriageServices, default_triage_services
from .stage_prompts_instruction_blocks import _STAGE_INSTRUCTIONS
from .stage_prompts_instruction_shared import (
    _STAGES,
    PromptMode,
    render_cli_reference,
    triage_prompt_preamble,
)
from .stage_prompts_observe import (
    _observe_batch_instructions,
    build_observe_batch_prompt,
)
from .stage_prompts_strategist import build_strategist_prompt
from .stage_prompts_sense import (
    build_sense_check_content_prompt,
    build_sense_check_structure_prompt,
    build_sense_check_value_prompt,
)
from .stage_prompts_validation import _validation_requirements


def _required_issue_hashes(triage_input: TriageInput) -> list[str]:
    """Return sorted short hashes for open review issues."""
    review_issues = getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {}))
    return sorted(issue_id.rsplit("::", 1)[-1] for issue_id in review_issues)


def _compact_issue_summary(triage_input: TriageInput) -> str:
    """Return a compact issue summary for later triage stages."""
    review_issues = getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {}))
    by_dim: Counter[str] = Counter()
    for issue in review_issues.values():
        detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
        by_dim[str(detail.get("dimension", "unknown"))] += 1
    dims = ", ".join(f"{name} ({count})" for name, count in sorted(by_dim.items()))
    parts = [
        "## Issue Summary",
        f"Open review issues: {len(review_issues)}",
    ]
    if dims:
        parts.append(f"Open dimensions: {dims}")
    if triage_input.new_since_last:
        parts.append(f"New since last triage: {len(triage_input.new_since_last)}")
    if triage_input.resolved_since_last:
        parts.append(f"Resolved since last triage: {len(triage_input.resolved_since_last)}")

    # Cluster summary if clusters exist
    existing = triage_input.existing_clusters or {}
    if existing:
        parts.append("")
        parts.append("## Clusters")
        for cname, cdata in existing.items():
            desc = cdata.get("description") or ""
            count = len(cdata.get("issue_ids", []))
            desc_str = f" ({desc})" if desc else ""
            parts.append(f"- {cname}: {count} issues{desc_str}")

    return "\n".join(parts)


_INVESTIGATION_COMMANDS = """\

## Available Investigation Commands

To see full detail for a specific issue:
  desloppify show <issue-id-or-hash-pattern> --no-budget
To see all open review issues with suggestions:
  desloppify show review --status open --no-budget
To see a cluster's steps, members, and suggestions:
  desloppify plan cluster show <name>
To list all clusters:
  desloppify plan cluster list --verbose"""


def _issue_context_for_stage(
    stage: str,
    triage_input: TriageInput,
    mode: PromptMode = "self_record",
) -> str:
    """Return the amount of issue context appropriate for a stage."""
    if stage in {"observe", "reflect"}:
        parts = ["## Issue Data\n\n" + build_triage_prompt(triage_input)]
        if stage == "reflect":
            short_ids = _required_issue_hashes(triage_input)
            parts.append(
                "## Required Issue Hashes\n"
                f"Total open review issues: {len(short_ids)}\n"
                "Every one of these hashes must appear exactly once in your cluster/skip blueprint.\n"
                "Do not repeat hashes outside that blueprint.\n"
                + ", ".join(short_ids)
            )
            parts.append(
                "## Coverage Ledger Template\n"
                "Your final report MUST contain a `## Coverage Ledger` section with one line per issue.\n"
                "Allowed forms:\n"
                '- `- abcd1234 -> cluster "cluster-name"`\n'
                '- `- abcd1234 -> skip "specific-reason-tag"`\n'
                "Do not mention hashes outside the `## Coverage Ledger` section.\n"
                + "\n".join(f"- {short_id} -> TODO" for short_id in short_ids)
            )
        return "\n\n".join(parts)
    summary = _compact_issue_summary(triage_input)
    if mode == "self_record":
        summary += _INVESTIGATION_COMMANDS
    return summary


def _format_assessments_table(assessments: list[dict]) -> str:
    """Format structured observe assessments as a readable table for downstream stages."""
    if not assessments:
        return ""
    lines = ["### Structured Observe Assessments\n"]
    lines.append("| Hash | Verdict | Recommendation |")
    lines.append("|------|---------|----------------|")
    for a in assessments:
        h = a.get("hash", "?")
        v = a.get("verdict", "?")
        r = a.get("recommendation", "")
        # Truncate recommendation for table readability
        if len(r) > 80:
            r = r[:77] + "..."
        lines.append(f"| {h} | {v} | {r} |")
    return "\n".join(lines)


def _format_disposition_table(
    dispositions: dict[str, dict],
    assessments: list[dict],
) -> str:
    """Format the unified disposition map for downstream stages.

    Partitions issues into:
    - Auto-skipped by observe (false-positive/exaggerated)
    - Genuine issues requiring disposition
    - Actionability-flagged issues (over-engineering/not-worth-it)
    """
    if not dispositions and not assessments:
        return ""

    auto_skipped: list[dict] = []
    genuine: list[dict] = []
    actionability: list[dict] = []

    # Build from assessments for hash display, enriched by dispositions
    for a in assessments:
        h = a.get("hash", "?")
        v = a.get("verdict", "?")
        r = a.get("recommendation", "")
        if len(r) > 80:
            r = r[:77] + "..."
        entry = {"hash": h, "verdict": v, "recommendation": r}

        if v in ("false positive", "exaggerated"):
            auto_skipped.append(entry)
        elif v in ("over engineering", "not worth it"):
            actionability.append(entry)
        else:
            genuine.append(entry)

    lines = ["### Issue Disposition Summary\n"]

    if auto_skipped:
        lines.append(f"**Auto-skipped by observe ({len(auto_skipped)} issues)** — no action needed:\n")
        lines.append("| Hash | Verdict | Recommendation |")
        lines.append("|------|---------|----------------|")
        for e in auto_skipped:
            lines.append(f"| {e['hash']} | {e['verdict']} | {e['recommendation']} |")
        lines.append("")

    if genuine:
        lines.append(f"**Genuine issues requiring disposition ({len(genuine)} issues):**\n")
        lines.append("| Hash | Verdict | Recommendation |")
        lines.append("|------|---------|----------------|")
        for e in genuine:
            lines.append(f"| {e['hash']} | {e['verdict']} | {e['recommendation']} |")
        lines.append("")

    if actionability:
        lines.append(
            f"**Actionability-flagged issues ({len(actionability)} issues)** "
            "— observe thinks these aren't worth it, reflect decides:\n"
        )
        lines.append("| Hash | Verdict | Recommendation |")
        lines.append("|------|---------|----------------|")
        for e in actionability:
            lines.append(f"| {e['hash']} | {e['verdict']} | {e['recommendation']} |")
        lines.append("")

    return "\n".join(lines)


def _format_assessment_file_evidence(assessments: list[dict]) -> str:
    """Format file-level observe evidence for clustering-heavy downstream stages."""
    if not assessments:
        return ""
    lines = ["### Observe File Evidence\n"]
    for assessment in assessments:
        issue_hash = str(assessment.get("hash", "?"))
        files_read = [
            str(path).strip()
            for path in assessment.get("files_read", [])
            if str(path).strip()
        ]
        verdict = str(assessment.get("verdict", "?")).strip() or "?"
        reasoning = str(assessment.get("verdict_reasoning", "")).strip()
        recommendation = str(assessment.get("recommendation", "")).strip()
        lines.append(f"- {issue_hash}: {verdict}")
        if files_read:
            lines.append(f"  files_read: {', '.join(files_read)}")
        if reasoning:
            lines.append(f"  verdict_reasoning: {reasoning}")
        if recommendation:
            lines.append(f"  recommendation: {recommendation}")
    return "\n".join(lines)


def _relevant_prior_reports(
    stage: str,
    prior_reports: dict[str, str],
    stages_data: dict | None = None,
) -> list[tuple[str, str]]:
    """Return the stage reports that matter for the current stage."""
    wanted = {
        "observe": ("strategize",),
        "reflect": ("strategize", "observe"),
        "organize": ("strategize", "reflect"),
        "enrich": ("organize",),
        "sense-check": ("strategize", "organize", "enrich"),
    }.get(stage, tuple(prior_reports))
    result = [(name, prior_reports[name]) for name in wanted if name in prior_reports]

    # Append structured observe assessments / disposition table for downstream stages
    if stage in {"reflect", "organize", "sense-check"} and stages_data:
        observe_data = stages_data.get("observe", {})
        assessments = observe_data.get("assessments", [])

        # Use disposition table when dispositions exist, fall back to assessments table.
        # Note: stages_data is the triage_stages dict; dispositions are on
        # epic_triage_meta which we don't have here. Use assessments to build
        # the partitioned view since the verdict info is the same.
        if assessments:
            disp_table = _format_disposition_table({}, assessments)
            if disp_table:
                result.append(("observe-dispositions", disp_table))
            else:
                table = _format_assessments_table(assessments)
                if table:
                    result.append(("observe-assessments", table))
        if stage == "organize":
            evidence = _format_assessment_file_evidence(assessments)
            if evidence:
                result.append(("observe-evidence", evidence))

    return result


def _extract_strategist_briefing(
    stages_data: dict | None,
    plan: dict | None = None,
) -> dict | None:
    if isinstance(plan, dict):
        meta = plan.get("epic_triage_meta", {})
        if isinstance(meta, dict):
            briefing = meta.get("strategist_briefing")
            if isinstance(briefing, dict):
                return briefing
    if not isinstance(stages_data, dict):
        return None
    strategize = stages_data.get("strategize", {})
    if not isinstance(strategize, dict):
        return None
    report = strategize.get("report", "")
    if not isinstance(report, str) or not report.strip():
        return None
    try:
        parsed = json.loads(report)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _format_strategize_focus_lines(briefing: dict) -> list[str]:
    lines: list[str] = []
    for entry in briefing.get("focus_dimensions", []) or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        reason = str(entry.get("reason", "")).strip()
        trend = str(entry.get("trend", "")).strip()
        headroom = entry.get("headroom")
        suffix_parts = []
        if trend:
            suffix_parts.append(f"trend={trend}")
        if headroom not in (None, ""):
            suffix_parts.append(f"headroom={headroom}")
        suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
        lines.append(f"- {name}{suffix}: {reason}")
    return lines


def _format_strategize_avoid_lines(briefing: dict) -> list[str]:
    lines: list[str] = []
    for entry in briefing.get("avoid_areas", []) or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        area_type = str(entry.get("type", "")).strip()
        prefix = f"- {name}"
        if area_type:
            prefix += f" [{area_type}]"
        lines.append(f"{prefix}: {reason}")
    return lines


def _format_strategist_for_observe(briefing: dict) -> str:
    parts = ["## Strategic Context"]
    guidance = str(briefing.get("observe_guidance", "")).strip()
    if guidance:
        parts.append(guidance)
    hotspots = briefing.get("file_churn_hotspots", []) or []
    if hotspots:
        parts.append("### File Churn Hotspots")
        for entry in hotspots[:5]:
            if not isinstance(entry, dict):
                continue
            parts.append(
                f"- {entry.get('file', '?')}: {entry.get('count', entry.get('resolved_count', 0))} churn "
                f"(detectors: {', '.join(entry.get('detectors', [])[:4])})"
            )
    return "\n".join(parts)


def _format_strategist_for_reflect(briefing: dict) -> str:
    parts = ["## Strategic Constraints"]
    guidance = str(briefing.get("reflect_guidance", "")).strip()
    if guidance:
        parts.append(guidance)
    focus_lines = _format_strategize_focus_lines(briefing)
    if focus_lines:
        parts.append("### Focus Dimensions")
        parts.extend(focus_lines)
    avoid_lines = _format_strategize_avoid_lines(briefing)
    if avoid_lines:
        parts.append("### Avoid Areas")
        parts.extend(avoid_lines)
    rework = briefing.get("rework_warnings", []) or []
    if rework:
        parts.append("### Rework Warnings")
        for warning in rework:
            if not isinstance(warning, dict):
                continue
            parts.append(
                f"- {warning.get('dimension', '?')}: {warning.get('resolved', warning.get('resolved_count', 0))} resolved, "
                f"{warning.get('new_open', warning.get('new_open_count', 0))} new open"
            )
    return "\n".join(parts)


def _format_strategist_for_organize(briefing: dict) -> str:
    parts = ["## Strategic Priorities"]
    guidance = str(briefing.get("organize_guidance", "")).strip()
    if guidance:
        parts.append(guidance)
    focus_lines = _format_strategize_focus_lines(briefing)
    if focus_lines:
        parts.append("### Prioritize")
        parts.extend(focus_lines)
    avoid_lines = _format_strategize_avoid_lines(briefing)
    if avoid_lines:
        parts.append("### Avoid")
        parts.extend(avoid_lines)
    return "\n".join(parts)


def _format_strategist_for_sense_check(briefing: dict) -> str:
    parts = ["## Strategic Flags"]
    guidance = str(briefing.get("sense_check_guidance", "")).strip()
    if guidance:
        parts.append(guidance)
    for warning in briefing.get("rework_warnings", []) or []:
        if not isinstance(warning, dict):
            continue
        parts.append(
            f"- Rework loop: {warning.get('dimension', '?')} "
            f"({warning.get('resolved', warning.get('resolved_count', 0))} resolved, "
            f"{warning.get('new_open', warning.get('new_open_count', 0))} new open)"
        )
    for pattern in briefing.get("anti_patterns", []) or []:
        if not isinstance(pattern, dict):
            continue
        description = str(pattern.get("description", "")).strip()
        if description:
            parts.append(f"- {description}")
    return "\n".join(parts)


def build_stage_prompt(
    stage: str,
    triage_input: TriageInput,
    prior_reports: dict[str, str],
    *,
    repo_root: Path,
    mode: PromptMode = "self_record",
    cli_command: str = "desloppify",
    stages_data: dict | None = None,
    plan: dict | None = None,
    state: dict | None = None,
) -> str:
    """Build a complete subagent prompt for a triage stage."""
    if stage == "strategize":
        if plan is None or state is None:
            raise ValueError("build_stage_prompt(stage='strategize') requires plan and state")
        strategist_input = collect_strategist_input(
            state,
            plan,
            progression_events=load_progression(),
        )
        prompt = build_strategist_prompt(
            strategist_input,
            repo_root=repo_root,
            mode="output_only",
        )
        validation = _validation_requirements(stage)
        return f"{prompt}\n\n{validation}" if validation else prompt

    parts: list[str] = []

    # Preamble
    parts.append(
        triage_prompt_preamble(mode).format(
            stage=stage.upper(),
            repo_root=repo_root,
            cli_command=cli_command,
        )
    )

    # Prior stage reports
    relevant_prior_reports = _relevant_prior_reports(stage, prior_reports, stages_data)
    if relevant_prior_reports:
        parts.append("## Prior Stage Reports\n")
        for prior_stage, report in relevant_prior_reports:
            parts.append(f"### {prior_stage.upper()} Report\n{report}\n")

    briefing = _extract_strategist_briefing(stages_data, plan)
    if briefing:
        if stage == "observe":
            parts.append(_format_strategist_for_observe(briefing))
        elif stage == "reflect":
            parts.append(_format_strategist_for_reflect(briefing))
        elif stage == "organize":
            parts.append(_format_strategist_for_organize(briefing))
        elif stage == "sense-check":
            parts.append(_format_strategist_for_sense_check(briefing))

    # Issue data / summary
    parts.append(_issue_context_for_stage(stage, triage_input, mode))

    # Stage-specific instructions
    instruction_fn = _STAGE_INSTRUCTIONS.get(stage)
    if instruction_fn:
        parts.append(instruction_fn(mode))

    # CLI reference
    if mode == "self_record":
        parts.append(render_cli_reference(cli_command))

    # Validation requirements
    parts.append(_validation_requirements(stage))

    return "\n\n".join(parts)


def cmd_stage_prompt(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Print the current prompt for a triage stage, built from live plan data."""
    stage = args.stage_prompt
    resolved_services = services or default_triage_services()
    plan = resolved_services.load_plan()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    si = resolved_services.collect_triage_input(plan, state)
    repo_root = get_project_root()

    # Extract real prior reports from plan.json
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    prior_reports: dict[str, str] = {}
    for prior_stage in _STAGES:
        if prior_stage == stage:
            break
        report = stages.get(prior_stage, {}).get("report", "")
        if report:
            prior_reports[prior_stage] = report

    prompt = build_stage_prompt(
        stage,
        si,
        prior_reports,
        repo_root=repo_root,
        stages_data=stages,
        plan=plan,
        state=state,
    )
    print(prompt)


__all__ = [
    "build_observe_batch_prompt",
    "build_sense_check_content_prompt",
    "build_sense_check_structure_prompt",
    "build_sense_check_value_prompt",
    "build_stage_prompt",
    "cmd_stage_prompt",
    "_observe_batch_instructions",
    "_validation_requirements",
]
