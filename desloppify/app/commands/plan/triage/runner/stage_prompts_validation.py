"""Validation requirement text blocks for triage prompt stages."""

from __future__ import annotations

_STAGES = ("strategize", "observe", "reflect", "organize", "enrich", "sense-check")


def _validation_requirements(stage: str) -> str:
    """What must be true for the stage to pass validation."""
    if stage == "strategize":
        return (
            "## Validation Requirements\n"
            "- Output must be valid JSON matching the StrategistBriefing schema\n"
            "- executive_summary must be 100+ characters\n"
            "- observe_guidance and reflect_guidance must each be 50+ characters\n"
            "- focus_dimensions must list at least 1 dimension\n"
            "- score_trend must be one of: improving, stable, declining\n"
            "- debt_trend must be one of: growing, stable, shrinking\n"
        )
    if stage == "observe":
        return (
            "## Validation Requirements\n"
            "- Stage must be recorded with a 100+ char report\n"
            "- Report must cite at least 10% of issue IDs (or 5, whichever is smaller)\n"
            "- Every assessment entry must have: recognized verdict (genuine/false-positive/exaggerated/over-engineering/not-worth-it), non-empty verdict_reasoning, non-empty files_read, non-empty recommendation\n"
            "- Stage must be confirmed with an 80+ char attestation mentioning dimension names\n"
        )
    if stage == "reflect":
        return (
            "## Validation Requirements\n"
            "- Stage must be recorded with a 100+ char report\n"
            "- Report must mention recurring dimension names (if any exist)\n"
            "- Report must include a `## Coverage Ledger` section\n"
            "- Report must account for every open review issue exactly once (no missing or duplicate hashes)\n"
            "- Stage must be confirmed with an 80+ char attestation\n"
        )
    if stage == "organize":
        return (
            "## Validation Requirements\n"
            "- At least one manual cluster with issues must exist\n"
            "- All manual clusters must have description and action steps\n"
            "- All review issues must be in a cluster or skipped\n"
            "- Overlapping clusters must have --depends-on relationships\n"
            "- Cluster descriptions must reflect current issues (not stale/skipped ones)\n"
            "- Clusters must group by file/area proximity, not by dimension or theme\n"
            "- A cluster whose issues span 5+ unrelated directories will be flagged\n"
            "- Consolidate shared-file changes and link every issue via --issue-refs\n"
            "- Step count must reflect actual work; a single-issue cluster may have one step\n"
            "- Stage must be recorded and confirmed\n"
        )
    if stage == "enrich":
        return (
            "## Validation Requirements (ALL BLOCKING — not advisory)\n"
            "- Every step needs --detail with 80+ chars INCLUDING a file path\n"
            "- Every step needs --issue-refs linking to review issue(s)\n"
            "- Every step needs --effort tag (trivial/small/medium/large)\n"
            "- No bad file paths in step details (must exist on disk)\n"
            "- No steps referencing skipped/wontfixed issues\n"
            "- Stage must be recorded and confirmed\n"
        )
    if stage == "sense-check":
        return (
            "## Validation Requirements (ALL BLOCKING)\n"
            "- Re-runs ALL enrich-level checks (detail, issue_refs, effort, paths, vagueness)\n"
            "- Stage must be recorded with a 100+ char report\n"
            "- Report must include a `## Decision Ledger` with one line per live queue target\n"
            "- Every live queue target must appear exactly once as keep, tighten, or skip\n"
            "- Report must cite real file paths to prove the code was re-read\n"
            "- Stage must be confirmed with an 80+ char attestation mentioning cluster names or clearly describing the verified sense-check work\n"
        )
    return ""


def render_validation_requirements(stage: str | None = None) -> str:
    """Render validation requirements for one stage, or every triage stage."""
    stages = (stage,) if stage else _STAGES
    blocks = []
    for stage_name in stages:
        requirements = _validation_requirements(stage_name)
        if not requirements:
            continue
        blocks.append(f"# {stage_name}\n\n{requirements}")
    return "\n\n".join(blocks)


__all__ = ["_validation_requirements", "render_validation_requirements"]
