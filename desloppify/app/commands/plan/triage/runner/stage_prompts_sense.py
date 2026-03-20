"""Sense-check prompt builders for triage runner."""

from __future__ import annotations

from pathlib import Path

from ..review_coverage import cluster_issue_ids


def _sense_check_job_block(*, mode: str) -> str:
    if mode == "self_record":
        return (
            "## Your job\n"
            "For EVERY step in this cluster, read the actual source file, verify\n"
            "every factual claim, and apply the needed cluster-step updates directly.\n"
        )
    return (
        "## Your job\n"
        "For EVERY step in this cluster, read the actual source file and verify\n"
        "every factual claim. Then fix anything wrong or vague.\n"
    )


def _sense_check_fix_list() -> str:
    return (
        "## What to check and fix\n"
        "1. LINE NUMBERS: Does the code at the claimed lines match what the step describes?\n"
        "   Fix: update the line range to match current file state.\n"
        "2. NAMES: Do the function/variable/type names in the step exist in the file?\n"
        "   Fix: correct the names.\n"
        "3. COUNTS: \"Update the 3 imports\" — are there actually 3? Or 5?\n"
        "   Fix: correct the count.\n"
        "4. STALENESS: Is the problem the issue describes still present in the code?\n"
        "   If already fixed, note in your report.\n"
        "5. VAGUENESS: Could a developer with zero context execute this step without\n"
        "   asking a single question? If not:\n"
        "   - Replace \"refactor X\" with the specific transformation\n"
        "   - Replace \"update imports\" with the specific file list\n"
        "   - Replace \"extract into new hook\" with the existing package/directory surface,\n"
        "     function signature, and return type\n"
        "   - ONLY reference file paths that already exist on disk\n"
        "   - If a new file is warranted, name the existing parent directory or package and\n"
        "     describe the new module generically; do NOT invent a future filename\n"
        "6. EFFORT TAGS: Does the tag match the actual scope? A one-line rename is \"trivial\",\n"
        "   not \"small\". Decomposing a 400-line file is \"large\", not \"medium\".\n"
        "7. DUPLICATES: If you notice this step does the same thing as a step in another\n"
        "   cluster, note it in your report.\n"
        "8. OVER-ENGINEERING: Would this change make the codebase *worse*? Flag steps that:\n"
        "   - Add abstractions, wrappers, or indirection for a one-time operation\n"
        "   - Introduce unnecessary config, feature flags, or generalization\n"
        "   - Make simple code harder to read for marginal benefit\n"
        "   - Gold-plate beyond what the issue actually requires\n"
        "   - Trade one smell for a worse one (e.g. fix duplication by adding a fragile base class)\n"
        "   If a step is net-negative, recommend removing it or simplifying the approach.\n"
        "   If the entire cluster is net-negative, say so clearly in your report.\n"
    )


def _sense_check_content_apply_block(
    *,
    mode: str,
    cli_command: str,
    cluster_name: str,
) -> str:
    if mode == "self_record":
        return (
            "## How to apply fixes\n"
            f"Use the exact CLI prefix: `{cli_command}`\n"
            "1. Inspect current state first:\n"
            f"   `{cli_command} plan cluster show {cluster_name}`\n"
            "2. Apply step corrections directly in this cluster:\n"
            f"   `{cli_command} plan cluster update {cluster_name} --update-step N --detail \"...\" --effort <trivial|small|medium|large> --issue-refs <id...>`\n"
            f"   `{cli_command} plan cluster update {cluster_name} --remove-step N`\n"
            "3. Re-check the cluster after edits:\n"
            f"   `{cli_command} plan cluster show {cluster_name}`\n"
        )
    return (
        "## How to report fixes\n"
        "Describe the exact step corrections needed, including the corrected detail text,\n"
        "the effort tag, and any stale/duplicate/over-engineered steps that should be removed.\n"
        "The orchestrator will apply the updates.\n"
    )


def _sense_check_content_not_to_do(mode: str) -> str:
    if mode == "self_record":
        return (
            "## What NOT to do\n"
            "- Do NOT reorder steps (the structure subagent handles that)\n"
            "- Do NOT add --depends-on (the structure subagent handles that)\n"
            "- Do NOT add new steps for missing cascade updates (the structure subagent handles that)\n"
            "- Do NOT introduce speculative future file or directory paths into step detail text\n"
            "- Do NOT name a concrete new file unless it already exists on disk\n"
            "- Do NOT modify any cluster other than the one assigned in this prompt\n"
            "- Do NOT run triage stage commands (`plan triage --stage ...`)\n"
            "- Do NOT debug or repair the CLI / environment\n"
        )
    return (
        "## What NOT to do\n"
        "- Do NOT reorder steps (the structure subagent handles that)\n"
        "- Do NOT add --depends-on (the structure subagent handles that)\n"
        "- Do NOT add new steps for missing cascade updates (the structure subagent handles that)\n"
        "- Do NOT invent future file or directory paths when rewriting steps\n"
        "- Do NOT name a concrete new file unless it already exists on disk\n"
        "- Do NOT run any `desloppify` commands\n"
        "- Do NOT debug or repair the CLI / environment\n"
    )


def _format_cluster_step(index: int, step: object) -> str:
    title = step.get("title", str(step)) if isinstance(step, dict) else str(step)
    detail = step.get("detail", "") if isinstance(step, dict) else ""
    effort = step.get("effort", "") if isinstance(step, dict) else ""
    refs = step.get("issue_refs", []) if isinstance(step, dict) else []
    line = f"{index}. **{title}**"
    if effort:
        line += f" [{effort}]"
    if refs:
        line += f" (refs: {', '.join(refs[:3])})"
    if detail:
        line += f"\n   {detail[:300]}"
    return line


def _sense_check_content_output_block(mode: str) -> str:
    if mode == "self_record":
        return (
            "\n## Output\n"
            "Write a plain-text summary of what you verified and what you changed in this cluster."
        )
    return (
        "\n## Output\n"
        "Write a plain-text report of your findings. The orchestrator records the stage."
    )


def _sense_check_structure_apply_block(*, mode: str, cli_command: str) -> str:
    if mode == "self_record":
        return (
            "## How to apply structure fixes\n"
            f"Use the exact CLI prefix: `{cli_command}`\n"
            "Apply only structure-level mutations:\n"
            f"- Add dependency edges: `{cli_command} plan cluster update <name> --depends-on <other-cluster>`\n"
            f"- Add missing cascade steps: `{cli_command} plan cluster update <name> --add-step \"...\" --detail \"...\" --effort <trivial|small|medium|large> --issue-refs <id...>`\n"
        )
    return ""


def _sense_check_structure_not_to_do(mode: str) -> str:
    if mode == "self_record":
        return (
            "## What NOT to do\n"
            "- Do NOT modify existing step detail text (content subagents handled that)\n"
            "- Do NOT change effort tags on existing steps\n"
            "- Do NOT remove existing steps\n"
            "- Do NOT add cascade steps that point at speculative future files; reference only existing files\n"
            "- Do NOT run triage stage commands (`plan triage --stage ...`)\n"
            "- Do NOT debug or repair the CLI / environment\n"
        )
    return (
        "## What NOT to do\n"
        "- Do NOT modify step detail text (the content subagent handles that)\n"
        "- Do NOT change effort tags (the content subagent handles that)\n"
        "- Do NOT remove steps or deduplicate (the content subagent handles that)\n"
        "- Do NOT add cascade steps that point at speculative future files\n"
        "- Do NOT run any `desloppify` commands\n"
        "- Do NOT debug or repair the CLI / environment\n"
    )


def _format_structure_cluster(name: str, cluster: dict) -> list[str]:
    steps = cluster.get("action_steps", [])
    deps = cluster.get("depends_on_clusters", [])
    issues = cluster_issue_ids(cluster)
    header = f"### {name} ({len(steps)} steps, {len(issues)} issues)"
    if deps:
        header += f"\n  depends_on: {', '.join(deps)}"
    lines = [header]
    for i, step in enumerate(steps, 1):
        title = step.get("title", str(step)) if isinstance(step, dict) else str(step)
        detail = step.get("detail", "") if isinstance(step, dict) else ""
        line = f"  {i}. {title}"
        if detail:
            line += f"\n     {detail[:200]}"
        lines.append(line)
    return lines


def _sense_check_structure_output_block(mode: str) -> str:
    if mode == "self_record":
        return (
            "\n## Output\n"
            "Write a plain-text summary of dependency/cascade fixes you applied."
        )
    return (
        "\n## Output\n"
        "Write a plain-text report of your findings. The orchestrator records the stage."
    )


def build_sense_check_content_prompt(
    *,
    cluster_name: str,
    plan: dict,
    repo_root: Path,
    policy_block: str = "",
    mode: str = "output_only",
    cli_command: str = "desloppify",
) -> str:
    """Build a content-verification prompt for a single cluster."""
    cluster = plan.get("clusters", {}).get(cluster_name, {})
    steps = cluster.get("action_steps", [])
    issue_ids = cluster_issue_ids(cluster)

    parts: list[str] = []
    parts.append(
        f"You are sense-checking cluster `{cluster_name}` "
        f"({len(steps)} steps, {len(issue_ids)} issues).\n"
        f"Repo root: {repo_root}"
    )
    parts.append(_sense_check_job_block(mode=mode))
    parts.append(_sense_check_fix_list())

    if policy_block:
        parts.append(policy_block)

    parts.append(
        _sense_check_content_apply_block(
            mode=mode,
            cli_command=cli_command,
            cluster_name=cluster_name,
        )
    )
    parts.append(_sense_check_content_not_to_do(mode))

    # Include cluster steps
    parts.append("## Current Steps\n")
    for i, step in enumerate(steps, 1):
        parts.append(_format_cluster_step(i, step))

    parts.append(_sense_check_content_output_block(mode))

    return "\n\n".join(parts)


def build_sense_check_structure_prompt(
    *,
    plan: dict,
    repo_root: Path,
    mode: str = "output_only",
    cli_command: str = "desloppify",
) -> str:
    """Build a structure-verification prompt for cross-cluster dependency checking."""
    clusters = plan.get("clusters", {})

    parts: list[str] = []
    parts.append(
        "You are checking cross-cluster dependencies for the entire triage plan.\n"
        f"Repo root: {repo_root}"
    )

    parts.append(
        "## Your job\n"
        "Build a file-touch graph: for each cluster, which files do its steps reference?\n"
        "Then check for unsafe relationships between clusters.\n"
    )

    parts.append(
        "## What to check and fix\n"
        "1. SHARED FILES: If cluster A and cluster B both have steps touching the same file,\n"
        "   and neither depends on the other → report which dependency edge should be added.\n"
        "2. MISSING CASCADE: If a step renames/removes a function or export, check whether\n"
        "   any other file imports it. If those importers aren't covered by any step in any\n"
        "   cluster → report the cascade step that should be added.\n"
        "   Include the cluster name, affected importers, and issue hash in your report.\n"
        "3. CIRCULAR DEPS: If adding a dependency would create a cycle, flag it in your report\n"
        "   instead of adding it.\n"
    )

    structure_apply = _sense_check_structure_apply_block(
        mode=mode,
        cli_command=cli_command,
    )
    if structure_apply:
        parts.append(structure_apply)
    parts.append(_sense_check_structure_not_to_do(mode))

    # Include all clusters with their steps and dependencies
    parts.append("## Clusters\n")
    for name, c in sorted(clusters.items()):
        if c.get("auto"):
            continue
        parts.extend(_format_structure_cluster(name, c))

    parts.append(_sense_check_structure_output_block(mode))

    return "\n\n".join(parts)


def build_sense_check_value_prompt(
    *,
    plan: dict,
    state: dict | None,
    repo_root: Path,
    strategist_briefing: dict | None = None,
    mode: str = "self_record",
    cli_command: str = "desloppify",
) -> str:
    """Build a value-check prompt for the YAGNI/KISS pass as sense-check's 3rd subagent."""
    from ..stages.helpers import value_check_targets

    targets = value_check_targets(plan, state)
    clusters = {name: c for name, c in plan.get("clusters", {}).items() if not c.get("auto")}

    parts: list[str] = []
    parts.append(
        "You are running the VALUE CHECK pass as part of sense-check.\n"
        f"Repo root: {repo_root}\n\n"
        f"Live queue targets: {len(targets)}"
    )

    job = (
        "## Your job\n"
        "Walk every live queue target and make the final YAGNI/KISS judgment.\n"
        "Ask: does doing this make the codebase genuinely better? Beauty is a valid\n"
        "reason to keep work, but not if it buys that beauty with new indirection,\n"
        "wrappers, abstraction layers, or confusion.\n"
    )
    parts.append(job)

    rubric = (
        "## Rubric\n"
        "For EVERY live queue target, choose exactly one:\n"
        "1. `keep` — clearly improves correctness, clarity, cohesion, simplicity, or elegance\n"
        "2. `tighten` — worth doing, but the plan must be simplified or made more concrete first\n"
        "3. `skip` — the fix would add churn, indirection, coordination, or abstraction for too little gain\n\n"
        "What should usually be skipped:\n"
        "- facade pruning that just spreads imports\n"
        "- abstraction-for-abstraction's-sake\n"
        "- tiny theoretical cleanups that make the code harder to follow\n"
        "- fixes whose implementation is more complicated than the current code\n\n"
        "What can still be worth keeping:\n"
        "- simplifications that delete layers or reduce branching\n"
        "- aesthetic cleanups that genuinely improve readability without adding machinery\n"
        "- focused unifications that make naming or flow more coherent with less confusion\n"
    )
    parts.append(rubric)

    if mode == "self_record":
        commands = (
            "## Commands\n"
            f"Use the exact CLI prefix: `{cli_command}`\n"
            f"- `{cli_command} next --count 100` to inspect the current execution queue\n"
            f"- `{cli_command} plan cluster show <name>` to inspect cluster members and steps\n"
            f"- `{cli_command} show <issue-id-or-hash> --no-budget` to re-read the underlying finding\n"
            f"- `{cli_command} plan cluster update <name> --update-step N --detail \"...\" --effort small`\n"
            f'- `{cli_command} plan skip --permanent <pattern> --note "<why>"'
            ' --attest "I have reviewed this triage skip against the code and I am not gaming the score'
            ' by suppressing a real defect."`\n'
            f"- `{cli_command} plan cluster delete <name>` if you skipped everything it contained\n"
        )
        parts.append(commands)
    else:
        parts.append(
            "## Output contract\n"
            "State the exact queue items to keep, tighten, or skip, plus any cluster-step\n"
            "updates or deletions needed. The orchestrator will apply them.\n"
        )

    process = (
        "## Required process\n"
        "1. Re-read the actual code behind each queue target.\n"
        "2. Apply the rubric above, not the raw issue title.\n"
        "3. Tighten any keeper whose steps are too vague, too broad, or too complicated.\n"
        "4. Permanently skip anything that fails the value test.\n"
        "5. Delete dead clusters after skipping all their members.\n"
    )
    parts.append(process)

    if strategist_briefing:
        lines = ["## Strategic Flags"]
        guidance = str(strategist_briefing.get("sense_check_guidance", "")).strip()
        if guidance:
            lines.append(guidance)
        rework_warnings = strategist_briefing.get("rework_warnings", [])
        for warning in rework_warnings:
            if not isinstance(warning, dict):
                continue
            dimension = warning.get("dimension", "?")
            resolved = warning.get("resolved", warning.get("resolved_count", 0))
            new_open = warning.get("new_open", warning.get("new_open_count", 0))
            lines.append(f"- Rework warning: {dimension} ({resolved} resolved, {new_open} new open)")
        anti_patterns = strategist_briefing.get("anti_patterns", [])
        for pattern in anti_patterns:
            if not isinstance(pattern, dict):
                continue
            description = str(pattern.get("description", "")).strip()
            if description:
                lines.append(f"- {description}")
        parts.append("\n".join(lines))

    # Include targets
    parts.append("## Live Queue Targets\n")
    for target in targets:
        if target in clusters:
            cluster = clusters[target]
            steps = cluster.get("action_steps", [])
            parts.append(f"- **{target}** ({len(steps)} steps)")
        else:
            parts.append(f"- {target}")

    # Include cluster details
    if clusters:
        parts.append("\n## Cluster Details\n")
        for name, cluster in sorted(clusters.items()):
            steps = cluster.get("action_steps", [])
            issues = cluster_issue_ids(cluster)
            parts.append(f"### {name} ({len(steps)} steps, {len(issues)} issues)")
            for i, step in enumerate(steps, 1):
                parts.append(_format_cluster_step(i, step))

    output_section = (
        "\n## Output\n"
        "Start with a `## Decision Ledger` section:\n"
        "```\n"
        "## Decision Ledger\n"
        "- cluster-or-id -> keep\n"
        "- cluster-or-id -> tighten\n"
        "- cluster-or-id -> skip\n"
        "```\n"
        "Then add short sections explaining the reasoning, with concrete file references.\n"
        "Cover every live queue target exactly once in the ledger.\n"
    )
    parts.append(output_section)

    return "\n\n".join(parts)


__all__ = [
    "build_sense_check_content_prompt",
    "build_sense_check_structure_prompt",
    "build_sense_check_value_prompt",
]
