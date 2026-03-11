"""Parsing helpers for epic triage output."""

from __future__ import annotations

import re

from desloppify.engine._plan.schema import VALID_EPIC_DIRECTIONS

from .prompt import ContradictionNote, DismissedIssue, TriageResult

ISSUE_ID_RE = re.compile(r"[a-z_]+::[a-f0-9]{8,}")
BRACKET_SHORT_ID_RE = re.compile(r"\[([a-z0-9_]{6,16})\]")

def extract_issue_citations(text: str, valid_ids: set[str]) -> set[str]:
    """Extract issue IDs cited in free text.

    Matches full issue IDs (e.g. ``review::abcdef12``) or bare 8+ char
    hex suffixes that correspond to a known issue.
    """
    if not text or not valid_ids:
        return set()

    cited: set[str] = set()

    # Prefer exact literal references for modern hierarchical IDs.
    for valid_id in valid_ids:
        if valid_id in text:
            cited.add(valid_id)

    # Support bracketed short hashes used in queue displays, e.g. [planmode].
    short_map: dict[str, str] = {}
    ambiguous_short: set[str] = set()
    for valid_id in valid_ids:
        suffix = valid_id.rsplit("::", 1)[-1]
        short = suffix[:8].lower()
        if not short:
            continue
        existing = short_map.get(short)
        if existing is None:
            short_map[short] = valid_id
        elif existing != valid_id:
            ambiguous_short.add(short)

    for short in ambiguous_short:
        short_map.pop(short, None)

    for short in BRACKET_SHORT_ID_RE.findall(text.lower()):
        mapped = short_map.get(short)
        if mapped:
            cited.add(mapped)

    # Match full issue IDs
    for match in ISSUE_ID_RE.finditer(text):
        candidate = match.group()
        if candidate in valid_ids:
            cited.add(candidate)
    # Match 8+ char hex suffixes
    for token in re.findall(r"[0-9a-f]{8,}", text):
        for valid_id in valid_ids:
            if valid_id.endswith("::" + token):
                cited.add(valid_id)
                break
    return cited


def _parse_action_steps(raw_steps: object) -> list[dict]:
    steps: list[dict] = []
    if not isinstance(raw_steps, list):
        return steps
    for raw_step in raw_steps:
        if isinstance(raw_step, dict):
            title = str(raw_step.get("title", "")).strip()
            if not title:
                continue
            step: dict = {"title": title}
            detail = raw_step.get("detail")
            if isinstance(detail, str) and detail.strip():
                step["detail"] = detail.strip()
            refs = raw_step.get("issue_refs")
            if isinstance(refs, list):
                normalized_refs = [str(ref).strip() for ref in refs if str(ref).strip()]
                if normalized_refs:
                    step["issue_refs"] = normalized_refs
            done = raw_step.get("done")
            if isinstance(done, bool):
                step["done"] = done
            steps.append(step)
    return steps


def parse_triage_result(raw: dict, valid_ids: set[str]) -> TriageResult:
    """Parse and validate raw LLM output into a TriageResult.

    Invalid issue IDs are silently dropped from epics and dismissals.
    """
    strategy_summary = str(raw.get("strategy_summary", ""))

    epics: list[dict] = []
    for raw_epic in raw.get("epics", []):
        if not isinstance(raw_epic, dict):
            continue
        name = str(raw_epic.get("name", "")).strip()
        if not name:
            continue
        # Validate direction
        direction = str(raw_epic.get("direction", "simplify")).strip()
        if direction not in VALID_EPIC_DIRECTIONS:
            direction = "simplify"
        # Filter to valid issue IDs
        issue_ids = [
            fid for fid in raw_epic.get("issue_ids", [])
            if isinstance(fid, str) and fid in valid_ids
        ]
        dismissed = [
            fid for fid in raw_epic.get("dismissed", [])
            if isinstance(fid, str) and fid in valid_ids
        ]
        action_steps = _parse_action_steps(raw_epic.get("action_steps", []))

        epics.append({
            "name": name,
            "thesis": str(raw_epic.get("thesis", "")),
            "direction": direction,
            "root_cause": str(raw_epic.get("root_cause", "")),
            "issue_ids": issue_ids,
            "dismissed": dismissed,
            "agent_safe": bool(raw_epic.get("agent_safe", False)),
            "dependency_order": int(raw_epic.get("dependency_order", 999)),
            "action_steps": action_steps,
            "status": str(raw_epic.get("status", "pending")),
        })

    dismissed_issues: list[DismissedIssue] = []
    for d in raw.get("dismissed_issues", []):
        if not isinstance(d, dict):
            continue
        fid = str(d.get("issue_id", ""))
        if fid in valid_ids:
            dismissed_issues.append(
                DismissedIssue(issue_id=fid, reason=str(d.get("reason", "")))
            )

    contradiction_notes: list[ContradictionNote] = []
    for c in raw.get("contradiction_notes", []):
        if not isinstance(c, dict):
            continue
        contradiction_notes.append(ContradictionNote(
            kept=str(c.get("kept", "")),
            dismissed=str(c.get("dismissed", "")),
            reason=str(c.get("reason", "")),
        ))

    priority_rationale = str(raw.get("priority_rationale", ""))

    return TriageResult(
        strategy_summary=strategy_summary,
        epics=epics,
        dismissed_issues=dismissed_issues,
        contradiction_notes=contradiction_notes,
        priority_rationale=priority_rationale,
    )

__all__ = ["ISSUE_ID_RE", "extract_issue_citations", "parse_triage_result"]
