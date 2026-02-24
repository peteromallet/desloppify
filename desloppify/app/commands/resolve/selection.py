"""Validation and preflight helpers for resolve command flows."""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass

from desloppify import state as state_mod
from desloppify.engine.work_queue import ATTEST_EXAMPLE
from desloppify.utils import colorize

_REQUIRED_ATTESTATION_PHRASES = ("i have actually", "not gaming")
_ATTESTATION_KEYWORD_HINT = ("I have actually", "not gaming")


@dataclass(frozen=True)
class ResolveQueryContext:
    patterns: list[str]
    status: str
    resolved: list[str]
    next_command: str
    prev_overall: float | None
    prev_objective: float | None
    prev_strict: float | None
    prev_verified: float | None
    attestation: str | None
    narrative: dict
    state: dict


def _missing_attestation_keywords(attestation: str | None) -> list[str]:
    normalized = " ".join((attestation or "").strip().lower().split())
    return [
        phrase for phrase in _REQUIRED_ATTESTATION_PHRASES if phrase not in normalized
    ]


def _validate_attestation(attestation: str | None) -> bool:
    return not _missing_attestation_keywords(attestation)


def _show_attestation_requirement(
    label: str, attestation: str | None, example: str
) -> None:
    missing = _missing_attestation_keywords(attestation)
    if not attestation:
        print(colorize(f"{label} requires --attest.", "yellow"))
    elif missing:
        missing_str = ", ".join(f"'{keyword}'" for keyword in missing)
        print(
            colorize(
                f"{label} attestation is missing required keyword(s): {missing_str}.",
                "yellow",
            )
        )
    print(
        colorize(
            f"Required keywords: '{_ATTESTATION_KEYWORD_HINT[0]}' and '{_ATTESTATION_KEYWORD_HINT[1]}'.",
            "yellow",
        )
    )
    print(colorize(f'Example: --attest "{example}"', "dim"))


def _validate_resolve_inputs(args: argparse.Namespace, attestation: str | None) -> None:
    if args.status == "wontfix" and not args.note:
        print(
            colorize(
                "Wontfix items become technical debt. Add --note to record your reasoning for future review.",
                "yellow",
            )
        )
        sys.exit(1)
    if args.status == "open":
        return
    if not _validate_attestation(attestation):
        _show_attestation_requirement("Manual resolve", attestation, ATTEST_EXAMPLE)
        sys.exit(1)


def _previous_score_snapshot(state: dict) -> state_mod.ScoreSnapshot:
    """Load a score snapshot for comparison after resolve operations."""
    return state_mod.score_snapshot(state)


def _preview_resolve_count(state: dict, patterns: list[str]) -> int:
    """Count unique open findings matching the provided patterns."""
    matched_ids: set[str] = set()
    for pattern in patterns:
        for finding in state_mod.match_findings(state, pattern, status_filter="open"):
            finding_id = finding.get("id")
            if finding_id:
                matched_ids.add(finding_id)
    return len(matched_ids)


def _estimate_wontfix_strict_delta(
    state: dict,
    args: argparse.Namespace,
    *,
    attestation: str | None,
    resolve_all_patterns_fn,
) -> float:
    """Estimate strict score drop if this resolve command is applied as wontfix."""
    before = state_mod.get_strict_score(state)
    if before is None:
        return 0.0

    preview_state = copy.deepcopy(state)
    resolve_all_patterns_fn(preview_state, args, attestation=attestation)
    after = state_mod.get_strict_score(preview_state)
    if after is None:
        return 0.0
    return max(0.0, before - after)


def _enforce_batch_wontfix_confirmation(
    state: dict,
    args: argparse.Namespace,
    *,
    attestation: str | None,
    resolve_all_patterns_fn,
) -> None:
    if args.status != "wontfix":
        return

    preview_count = _preview_resolve_count(state, args.patterns)
    if preview_count <= 10:
        return
    if getattr(args, "confirm_batch_wontfix", False):
        return

    strict_delta = _estimate_wontfix_strict_delta(
        state,
        args,
        attestation=attestation,
        resolve_all_patterns_fn=resolve_all_patterns_fn,
    )
    print(
        colorize(
            f"Large wontfix batch detected ({preview_count} findings).",
            "yellow",
        )
    )
    if strict_delta > 0:
        print(
            colorize(
                f"Estimated strict-score debt added now: {strict_delta:.1f} points.",
                "yellow",
            )
        )
    print(
        colorize(
            "Re-run with --confirm-batch-wontfix if this debt is intentional.",
            "yellow",
        )
    )
    sys.exit(1)
