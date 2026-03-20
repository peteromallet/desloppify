"""Observe-batch prompt builders for triage runner."""

from __future__ import annotations

from pathlib import Path

from .stage_prompts_instruction_shared import (
    observe_example_report_quality,
    observe_false_positive_guidance,
    observe_structured_template,
    observe_verification_checklist,
)


def _observe_batch_instructions(issue_count: int, total_batches: int) -> str:
    return f"""\
## OBSERVE Batch Instructions

You are one of {total_batches} parallel observe batches. Your task: verify every issue
assigned to you against the actual source code.

{observe_false_positive_guidance()}

Do NOT analyze themes, strategy, or relationships between issues. Just verify: is each issue real?

{observe_verification_checklist()}

{observe_example_report_quality()}

**Your report must include for EVERY issue ({issue_count} total):**
1. The issue hash
2. Your verdict (genuine / false positive / exaggerated / over-engineering / not-worth-it)
3. Your verdict reasoning (what you found when you read the code)
4. The file paths you actually read
5. Your recommendation

## IMPORTANT: Output Rules

**Do NOT run any `desloppify` commands.** Do NOT run `desloppify plan triage --stage observe`.
You are a parallel batch — the orchestrator will merge all batch outputs and record the stage.

**Write your analysis as plain text only.**
**Do NOT use the old one-line `[hash] VERDICT — evidence` format.**
Use this structured template for EVERY issue:
{observe_structured_template()}

Before finishing, do a self-check:
- Every issue in the batch has one entry
- Every entry has a non-empty `files_read` list
- Every entry has a concrete `recommendation`
"""


def build_observe_batch_prompt(
    batch_index: int,
    total_batches: int,
    dimension_group: list[str],
    issues_subset: dict[str, dict],
    *,
    repo_root: Path,
    strategist_guidance: str | None = None,
) -> str:
    """Build a scoped observe prompt for a single dimension-group batch.

    Unlike build_stage_prompt(), this produces a prompt for observe only,
    scoped to a subset of issues. The batch subprocess writes analysis to
    stdout — it does NOT run ``desloppify plan triage --stage observe``.
    The orchestrator merges batch outputs and records observe once.
    """
    parts: list[str] = []

    # Batch context header
    parts.append(
        f"You are observe batch {batch_index}/{total_batches}.\n"
        f"Dimensions assigned to you: {', '.join(dimension_group)}\n"
        f"Total issues in this batch: {len(issues_subset)}\n\n"
        f"Repo root: {repo_root}"
    )
    if strategist_guidance:
        parts.append("## Strategic Context\n\n" + strategist_guidance.strip())

    # Issue data — inline the subset directly
    parts.append("## Issues to Verify\n")
    for fid, f in sorted(issues_subset.items()):
        detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        title = f.get("title", fid)
        file_path = detail.get("file_path", "")
        description = detail.get("description", f.get("description", ""))
        line = f"- [{fid[:8]}] ({dim}) **{title}**"
        if file_path:
            line += f" — `{file_path}`"
        if description:
            line += f"\n  {description[:300]}"
        parts.append(line)

    # Batch-specific observe instructions (no subagent/CLI references)
    parts.append(_observe_batch_instructions(len(issues_subset), total_batches))

    return "\n\n".join(parts)


__all__ = ["_observe_batch_instructions", "build_observe_batch_prompt"]
