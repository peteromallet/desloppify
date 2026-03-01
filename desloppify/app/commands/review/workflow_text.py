"""Shared review-workflow command text used by review/fix flows."""

from __future__ import annotations

DEFAULT_REVIEW_NEXT_COMMAND = (
    "desloppify review --run-batches --runner codex --parallel --scan-after-import"
)
CLAUDE_EXTERNAL_START_COMMAND = (
    "desloppify review --external-start --external-runner claude"
)


def normalized_next_command(next_command: str | None) -> str:
    """Return one normalized subjective follow-up command string."""
    text = str(next_command or "").strip()
    return text or DEFAULT_REVIEW_NEXT_COMMAND


def next_subjective_command_text(next_command: str | None) -> str:
    """Render one shared 'next subjective command' guidance line."""
    return (
        "Next command to improve subjective scores: "
        f"`{normalized_next_command(next_command)}`"
    )


def claude_durable_path_text(*, submit_command_hint: str = "--external-submit") -> str:
    """Render one shared Claude durable-path guidance line."""
    return (
        "Claude cloud durable path: "
        f"`{CLAUDE_EXTERNAL_START_COMMAND}` then run the printed "
        f"`{submit_command_hint}` command"
    )


def findings_only_fallback_text(
    *,
    include_prepare_step: bool = False,
    include_scan_after_import: bool = False,
) -> str:
    """Render one shared findings-only fallback guidance line."""
    import_cmd = "desloppify review --import findings.json"
    if include_scan_after_import:
        import_cmd = f"{import_cmd} && desloppify scan"
    if include_prepare_step:
        return (
            "Findings-only fallback: `desloppify review --prepare`, then "
            f"`{import_cmd}`"
        )
    return f"Findings-only fallback: `{import_cmd}`"


def prepare_agent_plan_lines(next_command: str) -> tuple[str, ...]:
    """Return shared plan lines for `review --prepare` output."""
    return (
        f"1. Preferred: `{normalized_next_command(next_command)}`",
        "2. Cloud/manual fallback: run external reviewers, merge to findings.json, then import",
        f"3. {claude_durable_path_text()}",
        f"4. {findings_only_fallback_text()}",
        '5. Emergency only: `--manual-override --attest "<why>"` (provisional; expires on next scan)',
    )


def fix_review_agent_plan_lines() -> tuple[str, ...]:
    """Return shared plan lines for `fix review` guidance."""
    return (
        "1. Read query.json — it includes file content, context, and prompts",
        "2. Evaluate each file against the dimensions above",
        "3. Save findings as JSON (for example: findings.json)",
        "4. Preferred (Codex local): desloppify review --run-batches --runner codex --parallel --scan-after-import",
        "5. " + claude_durable_path_text(submit_command_hint="--external-submit ... --scan-after-import"),
        f"6. {findings_only_fallback_text(include_scan_after_import=True)}",
    )


__all__ = [
    "CLAUDE_EXTERNAL_START_COMMAND",
    "DEFAULT_REVIEW_NEXT_COMMAND",
    "claude_durable_path_text",
    "fix_review_agent_plan_lines",
    "findings_only_fallback_text",
    "next_subjective_command_text",
    "normalized_next_command",
    "prepare_agent_plan_lines",
]
