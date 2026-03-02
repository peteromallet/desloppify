"""Merge conceptually duplicate open review findings."""

from __future__ import annotations

import argparse

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.queue_progress import show_score_with_plan_context
from desloppify.core.issues_render import finding_weight
from desloppify.core.output_api import colorize
from desloppify.engine.work_queue import list_open_review_findings
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.intelligence.review.finding_merge import (
    merge_list_fields,
    normalize_word_set,
    pick_longer_text,
    track_merged_from,
)
from desloppify.state import save_state, utc_now


def _summary_similarity(a: str, b: str) -> float:
    left = normalize_word_set(a)
    right = normalize_word_set(b)
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    union = len(left | right)
    return float(overlap) / float(union) if union else 0.0


def _parse_holistic_identifier(finding_id: str) -> str:
    parts = [part for part in str(finding_id).split("::") if part]
    if len(parts) < 2:
        return ""
    candidate = parts[-2].strip()
    if not candidate or candidate in {"holistic", "changed", "stale", "unreviewed"}:
        return ""
    return candidate


def _related_files_set(finding: dict) -> set[str]:
    related = finding.get("detail", {}).get("related_files", [])
    if not isinstance(related, list):
        return set()
    return {str(path).strip() for path in related if str(path).strip()}


def _same_issue_concept(
    left: dict,
    right: dict,
    *,
    similarity_threshold: float,
) -> bool:
    left_detail = left.get("detail", {})
    right_detail = right.get("detail", {})
    if left_detail.get("dimension") != right_detail.get("dimension"):
        return False

    left_summary = str(left.get("summary", "")).strip()
    right_summary = str(right.get("summary", "")).strip()
    similarity = _summary_similarity(left_summary, right_summary)

    left_files = _related_files_set(left)
    right_files = _related_files_set(right)
    files_overlap = not left_files or not right_files or bool(left_files & right_files)

    left_identifier = _parse_holistic_identifier(left.get("id", ""))
    right_identifier = _parse_holistic_identifier(right.get("id", ""))
    if left_identifier and right_identifier and left_identifier == right_identifier:
        # Identifier match still requires at least one corroborating signal
        return similarity >= 0.3 or files_overlap

    if similarity < similarity_threshold:
        return False
    if not files_overlap:
        return False
    return True


def _merge_finding_details(primary: dict, duplicate: dict) -> None:
    primary_detail = primary.setdefault("detail", {})
    duplicate_detail = duplicate.get("detail", {})

    merge_list_fields(primary_detail, duplicate_detail, ("related_files", "evidence"))
    pick_longer_text(primary_detail, duplicate_detail, "suggestion")
    track_merged_from(primary_detail, duplicate.get("id", ""))


def do_merge(args: argparse.Namespace) -> None:
    """Merge conceptually duplicate open review findings."""
    runtime = command_runtime(args)
    state = runtime.state
    state_file = runtime.state_path
    narrative = compute_narrative(state, context=NarrativeContext(command="review"))
    items = list_open_review_findings(state)

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        return

    try:
        similarity = float(getattr(args, "similarity", 0.8))
    except (TypeError, ValueError):
        similarity = 0.8
    similarity = max(0.0, min(1.0, similarity))

    open_holistic = [
        finding
        for finding in items
        if finding.get("detector") == "review"
        and finding.get("detail", {}).get("holistic")
    ]
    if len(open_holistic) < 2:
        print(colorize("\n  Not enough holistic review findings to merge.\n", "dim"))
        return

    consumed: set[str] = set()
    merge_groups: list[list[dict]] = []
    for candidate in open_holistic:
        candidate_id = candidate.get("id", "")
        if not candidate_id or candidate_id in consumed:
            continue
        group = [candidate]
        consumed.add(candidate_id)
        for other in open_holistic:
            other_id = other.get("id", "")
            if not other_id or other_id in consumed:
                continue
            if _same_issue_concept(
                candidate,
                other,
                similarity_threshold=similarity,
            ):
                consumed.add(other_id)
                group.append(other)
        if len(group) > 1:
            merge_groups.append(group)

    if not merge_groups:
        print(
            colorize(
                "\n  No duplicate issue concepts found at the current similarity threshold.\n",
                "dim",
            )
        )
        return

    dry_run = bool(getattr(args, "dry_run", False))
    prev = state_mod.score_snapshot(state)
    timestamp = utc_now()
    merged_pairs: list[tuple[str, list[str]]] = []
    for group in merge_groups:
        ranked = sorted(
            group,
            key=lambda finding: (finding_weight(finding)[0], finding.get("id", "")),
            reverse=True,
        )
        primary = ranked[0]
        duplicates = ranked[1:]
        merged_pairs.append((primary.get("id", ""), [d.get("id", "") for d in duplicates]))
        if dry_run:
            continue
        for duplicate in duplicates:
            _merge_finding_details(primary, duplicate)
            duplicate["status"] = "auto_resolved"
            duplicate["resolved_at"] = timestamp
            duplicate["note"] = f"merged into {primary.get('id', '')}"
            duplicate["resolution_attestation"] = {
                "kind": "issue_merge",
                "text": "Merged conceptually duplicate review finding",
                "attested_at": timestamp,
                "scan_verified": False,
            }
        primary_detail = primary.setdefault("detail", {})
        primary_detail["merged_at"] = timestamp

    print(
        colorize(
            f"\n  Merge groups: {len(merge_groups)} | "
            f"duplicate findings: {sum(len(group) - 1 for group in merge_groups)}",
            "bold",
        )
    )
    for index, (primary_id, duplicate_ids) in enumerate(merged_pairs, 1):
        preview = ", ".join(duplicate_ids[:3])
        if len(duplicate_ids) > 3:
            preview = f"{preview}, +{len(duplicate_ids) - 3} more"
        print(colorize(f"  [{index}] keep {primary_id}", "dim"))
        print(colorize(f"      merge {preview}", "dim"))

    if dry_run:
        print(colorize("\n  Dry run only: no state changes written.\n", "yellow"))
        return

    save_state(state, state_file)
    print(colorize("\n  State updated with merged issue groups.", "green"))
    show_score_with_plan_context(state, prev)
    write_query(
        {
            "command": "review",
            "action": "merge",
            "groups": len(merge_groups),
            "duplicates_merged": sum(len(group) - 1 for group in merge_groups),
            "next_command": "desloppify show review --status open",
            "narrative": narrative,
        }
    )
