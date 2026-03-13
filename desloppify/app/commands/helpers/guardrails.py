"""Shared triage guardrail helpers for command entrypoints."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from desloppify import state as state_mod
from desloppify.app.commands.helpers.issue_id_display import short_issue_id
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS, CommandError
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.sync.context import has_objective_backlog, is_mid_cycle
from desloppify.engine.plan_state import load_plan
from desloppify.engine.plan_triage import (
    TRIAGE_CMD_RUN_STAGES_CLAUDE,
    TRIAGE_CMD_RUN_STAGES_CODEX,
    TriageSnapshot,
    build_triage_snapshot,
    triage_phase_banner,
)

logger = logging.getLogger(__name__)
_REVIEW_DETECTORS = frozenset({"review", "concerns"})


@dataclass
class TriageGuardrailResult:
    """Structured result from triage staleness detection."""

    is_stale: bool = False
    pending_behind_objective_backlog: bool = False
    new_ids: set[str] = field(default_factory=set)
    _plan: dict | None = field(default=None, repr=False)
    _snapshot: TriageSnapshot | None = field(default=None, repr=False)


def triage_guardrail_status(
    *,
    plan: dict | None = None,
    state: dict | None = None,
) -> TriageGuardrailResult:
    """Pure detection: is triage stale? Returns structured result, no side effects."""
    try:
        resolved_plan = plan if isinstance(plan, dict) else load_plan()
    except PLAN_LOAD_EXCEPTIONS as exc:
        logger.debug("Triage guardrail status skipped: plan could not be loaded.", exc_info=exc)
        return TriageGuardrailResult()

    resolved_state = state or {}

    snapshot = build_triage_snapshot(resolved_plan, resolved_state)
    if not snapshot.is_triage_stale:
        return TriageGuardrailResult(_plan=resolved_plan, _snapshot=snapshot)

    pending_behind_objective_backlog = (
        not snapshot.has_triage_in_queue
        and bool(resolved_state)
        and is_mid_cycle(resolved_plan)
        and has_objective_backlog(resolved_state, None)
    )

    return TriageGuardrailResult(
        is_stale=True,
        pending_behind_objective_backlog=pending_behind_objective_backlog,
        new_ids=set(snapshot.new_since_triage_ids),
        _plan=resolved_plan,
        _snapshot=snapshot,
    )


def triage_guardrail_messages(
    *,
    plan: dict | None = None,
    state: dict | None = None,
) -> list[str]:
    """Return warning strings without printing."""
    resolved_state = state or {}
    result = triage_guardrail_status(plan=plan, state=state)
    if not result.is_stale:
        return []

    messages: list[str] = []
    if result.new_ids:
        if result.pending_behind_objective_backlog:
            messages.append(
                f"{len(result.new_ids)} new review issue(s) arrived since the last triage."
                " They will activate after the current objective backlog is clear."
            )
        else:
            messages.append(
                f"{len(result.new_ids)} new review issue(s) not yet triaged."
                " Run the staged triage runner to incorporate them "
                f"(`{TRIAGE_CMD_RUN_STAGES_CODEX}` or `{TRIAGE_CMD_RUN_STAGES_CLAUDE}`)."
            )

    if result._plan is not None:
        banner = triage_phase_banner(result._plan, resolved_state, snapshot=result._snapshot)
        if banner:
            messages.append(banner)

    return messages


def print_triage_guardrail_info(
    *,
    plan: dict | None = None,
    state: dict | None = None,
) -> bool:
    """Print yellow info banner if triage is stale. Returns True if banner was shown."""
    messages = triage_guardrail_messages(plan=plan, state=state)
    for msg in messages:
        print(colorize(f"  {msg}", "yellow"))
    return bool(messages)


def require_triage_current_or_exit(
    *,
    state: dict,
    plan: dict | None = None,
    patterns: list[str] | None = None,
    bypass: bool = False,
    attest: str = "",
) -> None:
    """Gate: exit(1) if triage is stale and not bypassed. Name signals the exit."""
    result = triage_guardrail_status(plan=plan, state=state)
    if not result.is_stale:
        return

    if bypass and attest and len(attest.strip()) >= 30:
        print(colorize(
            "  Triage guardrail bypassed with attestation.",
            "yellow",
        ))
        return

    if result.pending_behind_objective_backlog and patterns:
        matched_targets = _matched_open_targets(state, patterns)
        if matched_targets and not _targets_include_review_work(matched_targets):
            banner = triage_phase_banner(
                result._plan or {},
                state,
                snapshot=result._snapshot,
            )
            if banner:
                print(colorize(f"  {banner}", "yellow"))
            return

    new_ids = result.new_ids
    if result.pending_behind_objective_backlog:
        lines = [
            "BLOCKED: review issues changed since the last triage, but triage is pending"
            " behind the current objective backlog.",
            "",
            "  Finish current objective work first; triage will activate after the backlog clears.",
            '  To bypass: --force-resolve --attest "I understand the plan may be stale..."',
        ]
        raise CommandError("\n".join(lines))

    lines = [
        f"BLOCKED: {len(new_ids) or 'some'} new review issue(s) have not been triaged."
    ]
    if new_ids:
        for fid in sorted(new_ids)[:5]:
            issue = state.get("issues", {}).get(fid, {})
            lines.append(f"    * [{short_issue_id(fid)}] {issue.get('summary', '')}")
        if len(new_ids) > 5:
            lines.append(f"    ... and {len(new_ids) - 5} more")
    lines.append("")
    lines.append(f"  NEXT STEP (Codex):  {TRIAGE_CMD_RUN_STAGES_CODEX}")
    lines.append(f"  NEXT STEP (Claude): {TRIAGE_CMD_RUN_STAGES_CLAUDE}")
    lines.append("  Manual fallback:    desloppify plan triage")
    lines.append("  (Review new issues, then either --confirm-existing or re-plan.)")
    lines.append("")
    lines.append("  View new execution items:  desloppify plan queue --sort recent")
    lines.append("  View broader backlog:      desloppify backlog")
    lines.append('  To bypass: --force-resolve --attest "I understand the plan may be stale..."')
    raise CommandError("\n".join(lines))


def _matched_open_targets(state: dict, patterns: list[str]) -> list[dict]:
    matched_by_id: dict[str, dict] = {}
    for pattern in patterns:
        for issue in state_mod.match_issues(state, pattern, status_filter="open"):
            issue_id = str(issue.get("id", "")).strip()
            if issue_id and issue_id not in matched_by_id:
                matched_by_id[issue_id] = issue
    return list(matched_by_id.values())


def _targets_include_review_work(matched_targets: list[dict]) -> bool:
    return any(issue.get("detector") in _REVIEW_DETECTORS for issue in matched_targets)


__all__ = [
    "TriageGuardrailResult",
    "print_triage_guardrail_info",
    "require_triage_current_or_exit",
    "triage_guardrail_messages",
    "triage_guardrail_status",
]
