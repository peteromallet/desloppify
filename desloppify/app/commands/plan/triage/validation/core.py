"""Validation and guardrail helpers for triage stage workflow."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import save_plan
from desloppify.engine.plan_triage import (
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
)
from desloppify.state import utc_now

from .completion_policy import (
    _completion_clusters_valid,
    _completion_strategy_valid,
    _confirm_existing_stages_valid,
    _confirm_note_valid,
    _confirm_strategy_valid,
    _confirmed_text_or_error,
    _note_cites_new_issues_or_error,
    _require_prior_strategy_for_confirm,
    _resolve_completion_strategy,
    _resolve_confirm_existing_strategy,
)
from .completion_stages import (
    _auto_confirm_enrich_for_complete,
    _auto_confirm_stage_for_complete,
    _require_enrich_stage_for_complete,
    _require_organize_stage_for_complete,
    _require_sense_check_stage_for_complete,
)
from .enrich_checks import (
    _cluster_file_overlaps,
    _clusters_with_directory_scatter,
    _clusters_with_high_step_ratio,
    _enrich_report_or_error,
    _require_organize_stage_for_enrich,
    _steps_missing_issue_refs,
    _steps_referencing_skipped_issues,
    _steps_with_bad_paths,
    _steps_with_vague_detail,
    _steps_without_effort,
    _underspecified_steps,
)
from ..confirmations.basic import MIN_ATTESTATION_LEN, validate_attestation
from ..helpers import manual_clusters_with_issues, observe_dimension_breakdown
from ..stages.helpers import unclustered_review_issues, unenriched_clusters


@dataclass(frozen=True)
class AutoConfirmStageRequest:
    """Configuration for one fold-confirm stage auto-confirmation."""

    stage_name: str
    stage_label: str
    blocked_heading: str
    confirm_cmd: str
    inline_hint: str
    dimensions: list[str] | None = None
    cluster_names: list[str] | None = None


def _auto_confirm_stage(
    *,
    plan: dict,
    stage_record: dict,
    attestation: str | None,
    request: AutoConfirmStageRequest,
    save_plan_fn=None,
) -> bool:
    """Shared auto-confirm flow for stage fold-confirm operations."""
    if save_plan_fn is None:
        save_plan_fn = save_plan
    if stage_record.get("confirmed_at"):
        return True
    if not attestation or len(attestation.strip()) < MIN_ATTESTATION_LEN:
        print(colorize(f"  {request.blocked_heading}", "red"))
        print(colorize(f"  Run: {request.confirm_cmd}", "dim"))
        print(colorize(f"  {request.inline_hint}", "dim"))
        return False

    confirmed_text = attestation.strip()
    validation_err = validate_attestation(
        confirmed_text,
        request.stage_name,
        dimensions=request.dimensions,
        cluster_names=request.cluster_names,
    )
    if validation_err:
        print(colorize(f"  {validation_err}", "red"))
        return False

    stage_record["confirmed_at"] = utc_now()
    stage_record["confirmed_text"] = confirmed_text
    save_plan_fn(plan)
    print(colorize(f"  ✓ {request.stage_label} auto-confirmed via --attestation.", "green"))
    return True


def _auto_confirm_observe_if_attested(
    *,
    plan: dict,
    stages: dict,
    attestation: str | None,
    triage_input,
    save_plan_fn=None,
) -> bool:
    observe_stage = stages.get("observe")
    if observe_stage is None:
        return False
    _by_dim, dim_names = observe_dimension_breakdown(triage_input)
    return _auto_confirm_stage(
        plan=plan,
        stage_record=observe_stage,
        attestation=attestation,
        request=AutoConfirmStageRequest(
            stage_name="observe",
            stage_label="Observe",
            blocked_heading="Cannot reflect: observe stage not confirmed.",
            confirm_cmd="desloppify plan triage --confirm observe",
            inline_hint="Or pass --attestation to auto-confirm observe inline.",
            dimensions=dim_names,
        ),
        save_plan_fn=save_plan_fn,
    )


def _validate_recurring_dimension_mentions(
    *,
    report: str,
    recurring_dims: list[str],
    recurring: dict,
) -> bool:
    if not recurring_dims:
        return True
    report_lower = report.lower()
    mentioned = [dim for dim in recurring_dims if dim.lower() in report_lower]
    if mentioned:
        return True
    print(colorize("  Recurring patterns detected but not addressed in report:", "red"))
    for dim in recurring_dims:
        info = recurring[dim]
        print(
            colorize(
                f"    {dim}: {len(info['resolved'])} resolved, "
                f"{len(info['open'])} still open — potential loop",
                "yellow",
            )
        )
    print(colorize("  Your report must mention at least one recurring dimension name.", "dim"))
    return False


def _analyze_reflect_issue_accounting(
    *,
    report: str,
    valid_ids: set[str],
) -> tuple[set[str], list[str], list[str]]:
    """Return cited, missing, and duplicate issue IDs referenced by reflect."""
    short_id_buckets: dict[str, list[str]] = {}
    short_hex_map: dict[str, str] = {}
    for issue_id in sorted(valid_ids):
        short_id = issue_id.rsplit("::", 1)[-1]
        short_id_buckets.setdefault(short_id, []).append(issue_id)
        if re.fullmatch(r"[0-9a-f]{8,}", short_id):
            existing = short_hex_map.get(short_id)
            if existing is None:
                short_hex_map[short_id] = issue_id
            elif existing != issue_id:
                # Ambiguous hex short IDs cannot be resolved safely.
                short_hex_map.pop(short_id, None)

    def _extract_ledger_key(line: str) -> str | None:
        match = re.match(r"-\s*(.+?)\s*->", line)
        if not match:
            return None
        token = match.group(1).strip().strip("`").strip()
        if token.startswith("[") and token.endswith("]"):
            token = token[1:-1].strip()
        return token or None

    ledger_hits: Counter[str] | None = None
    short_id_usage: Counter[str] = Counter()
    in_ledger = False
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"##\s+Coverage Ledger", line, re.IGNORECASE):
            in_ledger = True
            ledger_hits = Counter()
            continue
        if in_ledger and re.match(r"##\s+", line):
            break
        if not in_ledger:
            continue
        token = _extract_ledger_key(line)
        if token:
            if token in valid_ids:
                ledger_hits[token] += 1
                continue
            bucket = short_id_buckets.get(token)
            if bucket:
                bucket_index = short_id_usage[token]
                issue_id = bucket[bucket_index] if bucket_index < len(bucket) else bucket[-1]
                short_id_usage[token] += 1
                ledger_hits[issue_id] += 1
                continue
        for hex_token in re.findall(r"[0-9a-f]{8,}", line):
            issue_id = short_hex_map.get(hex_token)
            if issue_id:
                ledger_hits[issue_id] += 1
    if ledger_hits is not None and ledger_hits:
        cited = set(ledger_hits)
        duplicates = sorted(issue_id for issue_id, count in ledger_hits.items() if count > 1)
        missing = sorted(valid_ids - cited)
        return cited, missing, duplicates
    cited = extract_issue_citations(report, valid_ids)
    # Also match valid IDs that appear literally in the report
    # (handles non-hex IDs like test fixtures).
    for issue_id in valid_ids:
        if issue_id in report:
            cited.add(issue_id)
    short_hits = Counter(
        short_hex_map[token]
        for token in re.findall(r"[0-9a-f]{8,}", report)
        if token in short_hex_map
    )
    duplicates = sorted(issue_id for issue_id, count in short_hits.items() if count > 1)
    missing = sorted(valid_ids - cited)
    return cited, missing, duplicates


def _validate_reflect_issue_accounting(
    *,
    report: str,
    valid_ids: set[str],
) -> tuple[bool, set[str], list[str], list[str]]:
    """Ensure the reflect blueprint accounts for every open review issue exactly once."""
    cited, missing, duplicates = _analyze_reflect_issue_accounting(
        report=report,
        valid_ids=valid_ids,
    )
    if not missing and not duplicates:
        return True, cited, missing, duplicates
    print(
        colorize(
            "  Reflect report must account for every open review issue exactly once.",
            "red",
        )
    )
    if missing:
        missing_short = ", ".join(issue_id.rsplit("::", 1)[-1] for issue_id in missing[:10])
        print(colorize(f"    Missing: {missing_short}", "yellow"))
    if duplicates:
        duplicate_short = ", ".join(
            issue_id.rsplit("::", 1)[-1] for issue_id in duplicates[:10]
        )
        print(colorize(f"    Duplicated: {duplicate_short}", "yellow"))
    print(colorize("  Fix the reflect blueprint before running organize.", "dim"))
    return False, cited, missing, duplicates


def _require_reflect_stage_for_organize(stages: dict) -> bool:
    if "reflect" in stages:
        return True
    if "observe" not in stages:
        print(colorize("  Cannot organize: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return False
    print(colorize("  Cannot organize: reflect stage not complete.", "red"))
    print(colorize('  Run: desloppify plan triage --stage reflect --report "..."', "dim"))
    return False


def _auto_confirm_reflect_for_organize(
    *,
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
    triage_input=None,
    command_runtime_fn=None,
    collect_triage_input_fn=collect_triage_input,
    detect_recurring_patterns_fn=detect_recurring_patterns,
    save_plan_fn=None,
) -> bool:
    reflect_stage = stages.get("reflect")
    if reflect_stage is None:
        return False

    resolved_triage_input = triage_input
    if resolved_triage_input is None:
        runtime_factory = command_runtime_fn or command_runtime
        runtime = runtime_factory(args)
        resolved_triage_input = collect_triage_input_fn(plan, runtime.state)

    valid_ids = set(resolved_triage_input.open_issues.keys())
    accounting_ok, cited_ids, missing_ids, duplicate_ids = _validate_reflect_issue_accounting(
        report=str(reflect_stage.get("report", "")),
        valid_ids=valid_ids,
    )
    if not accounting_ok:
        return False
    reflect_stage["cited_ids"] = sorted(cited_ids)
    reflect_stage["missing_issue_ids"] = missing_ids
    reflect_stage["duplicate_issue_ids"] = duplicate_ids

    recurring = detect_recurring_patterns_fn(
        resolved_triage_input.open_issues,
        resolved_triage_input.resolved_issues,
    )
    _by_dim, observe_dims = observe_dimension_breakdown(resolved_triage_input)
    reflect_dims = sorted(set((list(recurring.keys()) if recurring else []) + observe_dims))
    reflect_clusters = [name for name in plan.get("clusters", {}) if not plan["clusters"][name].get("auto")]
    return _auto_confirm_stage(
        plan=plan,
        stage_record=reflect_stage,
        attestation=attestation,
        request=AutoConfirmStageRequest(
            stage_name="reflect",
            stage_label="Reflect",
            blocked_heading="Cannot organize: reflect stage not confirmed.",
            confirm_cmd="desloppify plan triage --confirm reflect",
            inline_hint="Or pass --attestation to auto-confirm reflect inline.",
            dimensions=reflect_dims,
            cluster_names=reflect_clusters,
        ),
        save_plan_fn=save_plan_fn,
    )


def _manual_clusters_or_error(plan: dict) -> list[str] | None:
    manual_clusters = manual_clusters_with_issues(plan)
    if manual_clusters:
        return manual_clusters
    any_clusters = [name for name, cluster in plan.get("clusters", {}).items() if cluster.get("issue_ids")]
    if any_clusters:
        print(colorize("  Cannot organize: only auto-clusters exist.", "red"))
        print(colorize("  Create manual clusters that group issues by root cause:", "dim"))
    else:
        print(colorize("  Cannot organize: no clusters with issues exist.", "red"))
    print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
    print(colorize("    desloppify plan cluster add <name> <issue-patterns>", "dim"))
    return None


def _clusters_enriched_or_error(plan: dict) -> bool:
    gaps = unenriched_clusters(plan)
    if not gaps:
        return True
    print(colorize(f"  Cannot organize: {len(gaps)} cluster(s) need enrichment.", "red"))
    for name, missing in gaps:
        print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
    print()
    print(colorize("  Each cluster needs a description and action steps:", "dim"))
    print(colorize('    desloppify plan cluster update <name> --description "what this cluster addresses" --steps "step 1" "step 2"', "dim"))
    return False


def _unclustered_review_issues_or_error(plan: dict, state: dict) -> bool:
    """Block if open review issues aren't in any manual cluster. Return True if OK."""
    unclustered = unclustered_review_issues(plan, state)
    if not unclustered:
        return True
    print(colorize(f"  Cannot organize: {len(unclustered)} review issue(s) have no cluster.", "red"))
    for fid in unclustered[:10]:
        short = fid.rsplit("::", 2)[-2] if "::" in fid else fid
        print(colorize(f"    {short}", "yellow"))
    if len(unclustered) > 10:
        print(colorize(f"    ... and {len(unclustered) - 10} more", "yellow"))
    print()
    print(colorize("  Every review issue needs an action plan. Either:", "dim"))
    print(colorize("    1. Add to a cluster: desloppify plan cluster add <name> <pattern>", "dim"))
    print(colorize('    2. Wontfix it: desloppify plan skip --permanent <pattern> --note "reason" --attest "..."', "dim"))
    return False


def _organize_report_or_error(report: str | None) -> str | None:
    if not report:
        print(colorize("  --report is required for --stage organize.", "red"))
        print(colorize("  Summarize your prioritized organization:", "dim"))
        print(colorize("  - Did you defer contradictory issues before clustering?", "dim"))
        print(colorize("  - What clusters did you create and why?", "dim"))
        print(colorize("  - Explicit priority ordering: which cluster 1st, 2nd, 3rd and why?", "dim"))
        print(colorize("  - What depends on what? What unblocks the most?", "dim"))
        return None
    if len(report) < 100:
        print(colorize(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        print(colorize("  Explain what you organized, your priorities, and focus order.", "dim"))
        return None
    return report


__all__ = [
    "_auto_confirm_enrich_for_complete",
    "_auto_confirm_observe_if_attested",
    "AutoConfirmStageRequest",
    "_auto_confirm_stage_for_complete",
    "_auto_confirm_reflect_for_organize",
    "_cluster_file_overlaps",
    "_clusters_with_directory_scatter",
    "_clusters_with_high_step_ratio",
    "_clusters_enriched_or_error",
    "_enrich_report_or_error",
    "_unclustered_review_issues_or_error",
    "_validate_reflect_issue_accounting",
    "_completion_clusters_valid",
    "_completion_strategy_valid",
    "_confirm_existing_stages_valid",
    "_confirm_note_valid",
    "_confirm_strategy_valid",
    "_confirmed_text_or_error",
    "_manual_clusters_or_error",
    "_note_cites_new_issues_or_error",
    "_organize_report_or_error",
    "_require_enrich_stage_for_complete",
    "_require_organize_stage_for_complete",
    "_require_organize_stage_for_enrich",
    "_require_prior_strategy_for_confirm",
    "_require_reflect_stage_for_organize",
    "_require_sense_check_stage_for_complete",
    "_resolve_completion_strategy",
    "_resolve_confirm_existing_strategy",
    "_underspecified_steps",
    "_steps_missing_issue_refs",
    "_steps_referencing_skipped_issues",
    "_steps_with_bad_paths",
    "_steps_with_vague_detail",
    "_steps_without_effort",
    "_validate_recurring_dimension_mentions",
]
