"""Epic synthesis engine — LLM-driven meta-plan for review findings.

Clusters review findings by root cause, dismisses false positives,
resolves contradictions, and orders by dependency. The synthesis is incremental:
it updates existing synthesis-clusters rather than recreating from scratch.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    VALID_EPIC_DIRECTIONS,
    Cluster,
    PlanModel,
    ensure_plan_defaults,
    synthesis_clusters,
)
from desloppify.engine._plan.stale_dimensions import (
    SYNTHESIS_ID,
    review_finding_snapshot_hash,
)
from desloppify.engine._state.schema import StateModel, utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Finding-ID citation extraction
# ---------------------------------------------------------------------------

FINDING_ID_RE = re.compile(r"[a-z_]+::[a-f0-9]{8,}")


def extract_finding_citations(text: str, valid_ids: set[str]) -> set[str]:
    """Extract finding IDs cited in free text.

    Matches full finding IDs (e.g. ``review::abcdef12``) or bare 8+ char
    hex suffixes that correspond to a known finding.
    """
    cited: set[str] = set()
    # Match full finding IDs
    for match in FINDING_ID_RE.finditer(text):
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


# ---------------------------------------------------------------------------
# Completed-work helpers
# ---------------------------------------------------------------------------

def last_real_review_timestamp(state: dict) -> str | None:
    """ISO timestamp of most recent genuine review import (not manual override/scan reset)."""
    REAL_MODES = {"holistic", "per_file", "trusted_internal", "attested_external"}
    audit = state.get("assessment_import_audit", [])
    if isinstance(audit, list):
        for entry in reversed(audit):
            if isinstance(entry, dict) and entry.get("mode") in REAL_MODES:
                ts = entry.get("timestamp")
                if ts:
                    return str(ts)
    holistic = (state.get("review_cache") or {}).get("holistic")
    if isinstance(holistic, dict):
        return holistic.get("reviewed_at")
    return None


def detect_recurring_patterns(
    open_findings: dict[str, dict],
    resolved_findings: dict[str, dict],
) -> dict[str, dict]:
    """Detect dimensions with both resolved AND current open findings.

    Returns ``{dimension: {"open": [ids], "resolved": [ids]}}``.
    A dimension with both resolved and open findings signals a potential
    loop — similar issues recur after previous fixes.
    """
    def _dimension(f: dict) -> str:
        detail = f.get("detail", {})
        if isinstance(detail, dict):
            return detail.get("dimension", "")
        return ""

    open_by_dim: dict[str, list[str]] = {}
    for fid, f in open_findings.items():
        dim = _dimension(f)
        if dim:
            open_by_dim.setdefault(dim, []).append(fid)

    resolved_by_dim: dict[str, list[str]] = {}
    for fid, f in resolved_findings.items():
        dim = _dimension(f)
        if dim:
            resolved_by_dim.setdefault(dim, []).append(fid)

    recurring: dict[str, dict] = {}
    for dim in set(open_by_dim) & set(resolved_by_dim):
        recurring[dim] = {
            "open": open_by_dim[dim],
            "resolved": resolved_by_dim[dim],
        }
    return recurring


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SynthesisInput:
    """All data the LLM needs to produce/update epics."""

    open_findings: dict[str, dict]       # id -> finding (review + concerns)
    mechanical_findings: dict[str, dict]  # id -> finding (non-review, for context)
    existing_epics: dict[str, Cluster]    # current synthesis-clusters to update
    dimension_scores: dict[str, Any]      # for context
    new_since_last: set[str]             # finding IDs new since last synthesis
    resolved_since_last: set[str]        # finding IDs resolved since last
    previously_dismissed: list[str]      # IDs dismissed in prior synthesis
    synthesis_version: int               # next version number
    resolved_findings: dict[str, dict]   # full finding objects for resolved IDs
    completed_clusters: list[dict]       # clusters completed since last synthesis


@dataclass
class DismissedFinding:
    """A finding the LLM says doesn't make sense."""

    finding_id: str
    reason: str


@dataclass
class ContradictionNote:
    """Record of a resolved contradiction."""

    kept: str
    dismissed: str
    reason: str


@dataclass
class SynthesisResult:
    """Parsed and validated LLM synthesis output."""

    strategy_summary: str
    epics: list[dict]
    dismissed_findings: list[DismissedFinding] = field(default_factory=list)
    contradiction_notes: list[ContradictionNote] = field(default_factory=list)
    priority_rationale: str = ""


@dataclass
class SynthesisMutationResult:
    """What changed when synthesis was applied to the plan."""

    epics_created: int = 0
    epics_updated: int = 0
    epics_completed: int = 0
    findings_dismissed: int = 0
    findings_reassigned: int = 0
    strategy_summary: str = ""
    synthesis_version: int = 0
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

def collect_synthesis_input(plan: PlanModel, state: StateModel) -> SynthesisInput:
    """Gather all data needed for the synthesis LLM prompt."""
    ensure_plan_defaults(plan)
    findings = state.get("findings", {})
    meta = plan.get("epic_synthesis_meta", {})
    epics = synthesis_clusters(plan)

    open_review: dict[str, dict] = {}
    open_mechanical: dict[str, dict] = {}
    for fid, f in findings.items():
        if f.get("status") != "open":
            continue
        if f.get("detector") in ("review", "concerns"):
            open_review[fid] = f
        else:
            open_mechanical[fid] = f

    synthesized_ids = set(meta.get("synthesized_ids", []))
    current_review_ids = set(open_review.keys())
    new_since = current_review_ids - synthesized_ids
    resolved_since = synthesized_ids - current_review_ids
    previously_dismissed = list(meta.get("dismissed_ids", []))
    version = int(meta.get("version", 0)) + 1

    # Resolved finding objects (for REFLECT stage)
    resolved_finding_objs = {
        fid: findings[fid] for fid in resolved_since if fid in findings
    }

    # Completed clusters since last synthesis completion
    last_completed = meta.get("last_completed_at", "")
    all_completed: list[dict] = plan.get("completed_clusters", [])
    if last_completed:
        recent_completed = [
            c for c in all_completed
            if c.get("completed_at", "") > last_completed
        ]
    else:
        recent_completed = list(all_completed)

    return SynthesisInput(
        open_findings=open_review,
        mechanical_findings=open_mechanical,
        existing_epics=dict(epics),
        dimension_scores=state.get("dimension_scores", {}),
        new_since_last=new_since,
        resolved_since_last=resolved_since,
        previously_dismissed=previously_dismissed,
        synthesis_version=version,
        resolved_findings=resolved_finding_objs,
        completed_clusters=recent_completed,
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM_PROMPT = """\
You are maintaining the meta-plan for this codebase. Your goal is to produce
a coherent, prioritized strategy to address ALL open review findings.

Your plan should:
- Cluster findings by ROOT CAUSE, not by dimension or detector
- Give each cluster (epic) a clear thesis: one imperative sentence
- Order epics by dependency: what must be done first for later work to make sense
- Dismiss findings that don't make sense, are contradictory, or are false positives
- Mark which epics are agent-safe (can be executed mechanically) vs need human judgment
- Avoid creating work that contradicts other work in the plan
- Be ambitious but realistic — aim to resolve all findings coherently

Available directions for epics: delete, merge, flatten, enforce, simplify, decompose, extract, inline.

Available plan tools (the agent executing your plan has access to these):
- `desloppify plan queue` — view all items in priority order
- `desloppify plan focus epic/<name>` — focus the queue on one epic
- `desloppify plan skip <id> --permanent --note "why" --attest "..."` — permanently dismiss
- `desloppify plan skip <id> --note "revisit later"` — temporarily defer
- `desloppify plan done <id> --note "what I did" --attest "..."` — mark resolved
- `desloppify plan move <id> top|bottom|before|after <target>` — reorder
- `desloppify plan cluster show <name>` — inspect a cluster
- `desloppify scan` — re-scan after making changes to verify progress
- `desloppify show review --status open` — see all open review findings

Your output defines the ENTIRE work plan. Findings not assigned to any epic
will remain in the queue as individual items. Dismissed findings will be
removed from the queue with your stated reason.

Respond with a single JSON object matching this schema:
{
  "strategy_summary": "2-4 sentence narrative: what the meta-plan says, top priorities, current state",
  "epics": [
    {
      "name": "slug-name",
      "thesis": "imperative one-liner",
      "direction": "delete|merge|flatten|enforce|simplify|decompose|extract|inline",
      "root_cause": "why this cluster exists",
      "finding_ids": ["id1", "id2"],
      "dismissed": ["id3"],
      "agent_safe": true,
      "dependency_order": 1,
      "action_steps": ["step 1", "step 2"],
      "status": "pending"
    }
  ],
  "dismissed_findings": [
    {"finding_id": "id", "reason": "why this finding doesn't make sense"}
  ],
  "contradiction_notes": [
    {"kept": "finding_id", "dismissed": "finding_id", "reason": "why"}
  ],
  "priority_rationale": "why the dependency_order is what it is"
}
"""


def build_synthesis_prompt(si: SynthesisInput) -> str:
    """Build the user-facing prompt content with all finding data."""
    parts: list[str] = []

    # Section: existing epics
    if si.existing_epics:
        parts.append("## Existing Epics (update these, don't recreate)")
        for name, epic in sorted(si.existing_epics.items()):
            status = epic.get("status", "pending")
            thesis = epic.get("thesis", "")
            direction = epic.get("direction", "")
            fids = epic.get("finding_ids", [])
            parts.append(
                f"- {name} [{status}] ({direction}): {thesis}"
                f"\n  Findings: {', '.join(fids[:10])}"
                f"{'...' if len(fids) > 10 else ''}"
            )
        parts.append("")

    # Section: what changed
    if si.new_since_last:
        parts.append(f"## New findings since last synthesis ({len(si.new_since_last)})")
        for fid in sorted(si.new_since_last):
            f = si.open_findings.get(fid, {})
            parts.append(f"- {fid}: {f.get('summary', '(no summary)')}")
        parts.append("")

    if si.resolved_since_last:
        parts.append(f"## Resolved since last synthesis ({len(si.resolved_since_last)})")
        for fid in sorted(si.resolved_since_last):
            parts.append(f"- {fid}")
        parts.append("")

    # Section: all open review findings
    parts.append(f"## All open review findings ({len(si.open_findings)})")
    for fid, f in sorted(si.open_findings.items()):
        detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
        suggestion = detail.get("suggestion", "")
        dimension = detail.get("dimension", "")
        confidence = f.get("confidence", "medium")
        file_path = f.get("file", "")
        summary = f.get("summary", "")
        parts.append(f"- [{confidence}] {fid}")
        parts.append(f"  File: {file_path}")
        if dimension:
            parts.append(f"  Dimension: {dimension}")
        parts.append(f"  Summary: {summary}")
        if suggestion:
            parts.append(f"  Suggestion: {suggestion}")
    parts.append("")

    # Section: dimension scores for context
    if si.dimension_scores:
        parts.append("## Dimension scores (context)")
        for name, data in sorted(si.dimension_scores.items()):
            if isinstance(data, dict):
                score = data.get("score", "?")
                strict = data.get("strict", score)
                issues = data.get("issues", 0)
                parts.append(f"- {name}: {score}% (strict: {strict}%, {issues} issues)")
        parts.append("")

    # Section: previously dismissed
    if si.previously_dismissed:
        parts.append(f"## Previously dismissed ({len(si.previously_dismissed)})")
        parts.append("Maintain unless contradicted by new evidence.")
        for fid in si.previously_dismissed:
            parts.append(f"- {fid}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def parse_synthesis_result(raw: dict, valid_ids: set[str]) -> SynthesisResult:
    """Parse and validate raw LLM output into a SynthesisResult.

    Invalid finding IDs are silently dropped from epics and dismissals.
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
        # Filter to valid finding IDs
        finding_ids = [
            fid for fid in raw_epic.get("finding_ids", [])
            if isinstance(fid, str) and fid in valid_ids
        ]
        dismissed = [
            fid for fid in raw_epic.get("dismissed", [])
            if isinstance(fid, str) and fid in valid_ids
        ]
        action_steps = [
            str(s) for s in raw_epic.get("action_steps", [])
            if isinstance(s, str)
        ]

        epics.append({
            "name": name,
            "thesis": str(raw_epic.get("thesis", "")),
            "direction": direction,
            "root_cause": str(raw_epic.get("root_cause", "")),
            "finding_ids": finding_ids,
            "dismissed": dismissed,
            "agent_safe": bool(raw_epic.get("agent_safe", False)),
            "dependency_order": int(raw_epic.get("dependency_order", 999)),
            "action_steps": action_steps,
            "status": str(raw_epic.get("status", "pending")),
        })

    dismissed_findings: list[DismissedFinding] = []
    for d in raw.get("dismissed_findings", []):
        if not isinstance(d, dict):
            continue
        fid = str(d.get("finding_id", ""))
        if fid in valid_ids:
            dismissed_findings.append(
                DismissedFinding(finding_id=fid, reason=str(d.get("reason", "")))
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

    return SynthesisResult(
        strategy_summary=strategy_summary,
        epics=epics,
        dismissed_findings=dismissed_findings,
        contradiction_notes=contradiction_notes,
        priority_rationale=priority_rationale,
    )


# ---------------------------------------------------------------------------
# Plan mutation
# ---------------------------------------------------------------------------

def apply_synthesis_to_plan(
    plan: PlanModel,
    state: StateModel,
    synthesis: SynthesisResult,
    *,
    trigger: str = "manual",
) -> SynthesisMutationResult:
    """Apply parsed synthesis result to the living plan.

    1. Creates/updates synthesis-clusters in plan["clusters"]
    2. Marks dismissed findings as synthesized_out skips
    3. Reorders queue_order to group epic members by dependency_order
    4. Updates epic_synthesis_meta with snapshot hash
    """
    ensure_plan_defaults(plan)
    now = utc_now()
    result = SynthesisMutationResult()
    result.strategy_summary = synthesis.strategy_summary

    clusters = plan["clusters"]
    skipped: dict = plan["skipped"]
    order: list[str] = plan["queue_order"]
    meta = plan.get("epic_synthesis_meta", {})
    version = int(meta.get("version", 0)) + 1
    result.synthesis_version = version

    # --- Update/create synthesis-clusters ------------------------------------
    for epic_data in sorted(synthesis.epics, key=lambda e: e.get("dependency_order", 999)):
        raw_name = epic_data["name"]
        epic_name = f"{EPIC_PREFIX}{raw_name}" if not raw_name.startswith(EPIC_PREFIX) else raw_name

        existing = clusters.get(epic_name)
        if existing and existing.get("thesis"):
            # Update existing synthesis-cluster
            existing["thesis"] = epic_data["thesis"]
            existing["direction"] = epic_data["direction"]
            existing["root_cause"] = epic_data.get("root_cause", "")
            existing["finding_ids"] = epic_data["finding_ids"]
            existing["dismissed"] = epic_data.get("dismissed", [])
            existing["agent_safe"] = epic_data.get("agent_safe", False)
            existing["dependency_order"] = epic_data["dependency_order"]
            existing["action_steps"] = epic_data.get("action_steps", [])
            existing["updated_at"] = now
            existing["synthesis_version"] = version
            existing["description"] = epic_data["thesis"]
            # Don't overwrite in_progress status from agent
            if existing.get("status") != "in_progress":
                existing["status"] = epic_data.get("status", "pending")
            result.epics_updated += 1
        else:
            # Create new synthesis-cluster
            cluster: Cluster = {
                "name": epic_name,
                "description": epic_data["thesis"],
                "finding_ids": epic_data["finding_ids"],
                "auto": True,
                "cluster_key": f"epic::{epic_name}",
                "action": f"desloppify plan focus {epic_name}",
                "user_modified": False,
                "created_at": now,
                "updated_at": now,
                # Epic fields
                "thesis": epic_data["thesis"],
                "direction": epic_data["direction"],
                "root_cause": epic_data.get("root_cause", ""),
                "supersedes": [],
                "dismissed": epic_data.get("dismissed", []),
                "agent_safe": epic_data.get("agent_safe", False),
                "dependency_order": epic_data["dependency_order"],
                "action_steps": epic_data.get("action_steps", []),
                "source_clusters": [],
                "status": epic_data.get("status", "pending"),
                "synthesis_version": version,
            }
            clusters[epic_name] = cluster
            result.epics_created += 1

    # --- Dismiss findings ---------------------------------------------------
    dismissed_ids: list[str] = []
    for df in synthesis.dismissed_findings:
        fid = df.finding_id
        dismissed_ids.append(fid)
        # Remove from queue, add to skipped as synthesized_out
        if fid in order:
            order.remove(fid)
        skipped[fid] = {
            "finding_id": fid,
            "kind": "synthesized_out",
            "reason": df.reason,
            "note": f"Dismissed by epic synthesis v{version}",
            "attestation": None,
            "created_at": now,
            "review_after": None,
            "skipped_at_scan": int(state.get("scan_count", 0)),
        }
        result.findings_dismissed += 1

    # Also handle per-epic dismissed lists
    for epic_data in synthesis.epics:
        for fid in epic_data.get("dismissed", []):
            if fid not in dismissed_ids and fid in order:
                order.remove(fid)
                dismissed_ids.append(fid)
                skipped[fid] = {
                    "finding_id": fid,
                    "kind": "synthesized_out",
                    "reason": f"Dismissed by epic synthesis v{version}",
                    "note": None,
                    "attestation": None,
                    "created_at": now,
                    "review_after": None,
                    "skipped_at_scan": int(state.get("scan_count", 0)),
                }
                result.findings_dismissed += 1

    # --- Reorder queue: epic findings grouped by dependency_order -----------
    epic_finding_ids: set[str] = set()
    epic_ordered_ids: list[str] = []
    for epic_data in sorted(synthesis.epics, key=lambda e: e.get("dependency_order", 999)):
        for fid in epic_data["finding_ids"]:
            if fid not in epic_finding_ids and fid not in dismissed_ids:
                epic_finding_ids.add(fid)
                epic_ordered_ids.append(fid)

    # Rebuild order: epic items first (by dependency), then non-epic items in original order
    non_epic_items = [fid for fid in order if fid not in epic_finding_ids]
    # Insert epic items at the front (after synthesis::pending if present)
    new_order: list[str] = []
    # Keep synthesis::pending at front if present (it will be pruned next sync)
    if SYNTHESIS_ID in non_epic_items:
        non_epic_items.remove(SYNTHESIS_ID)
    new_order.extend(epic_ordered_ids)
    new_order.extend(non_epic_items)
    order.clear()
    order.extend(new_order)

    # --- Update synthesis meta -----------------------------------------------
    current_hash = review_finding_snapshot_hash(state)
    open_review_ids = sorted(
        fid for fid, f in state.get("findings", {}).items()
        if f.get("status") == "open"
        and f.get("detector") in ("review", "concerns")
    )

    plan["epic_synthesis_meta"] = {
        "synthesized_ids": open_review_ids,
        "last_run": now,
        "version": version,
        "dismissed_ids": dismissed_ids,
        "finding_snapshot_hash": current_hash,
        "strategy_summary": synthesis.strategy_summary,
        "trigger": trigger,
    }
    plan["updated"] = now

    return result


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

@dataclass
class SynthesisDeps:
    """Injectable dependencies for the synthesis engine."""

    llm_call: Any = None  # Callable[[str, str], str] — (system, user) -> response


def synthesize_epics(
    plan: PlanModel,
    state: StateModel,
    *,
    deps: SynthesisDeps | None = None,
    dry_run: bool = False,
    trigger: str = "manual",
) -> SynthesisMutationResult:
    """Run epic synthesis: collect input, call LLM, apply results.

    If ``dry_run`` is True, collects input and builds prompt but does not
    call the LLM or mutate the plan.

    If ``deps.llm_call`` is None, returns a dry-run result with the prompt.
    """
    ensure_plan_defaults(plan)
    si = collect_synthesis_input(plan, state)

    prompt = build_synthesis_prompt(si)
    valid_ids = set(si.open_findings.keys())

    if dry_run or deps is None or deps.llm_call is None:
        result = SynthesisMutationResult(dry_run=True)
        result.strategy_summary = f"[dry-run] Prompt built with {len(si.open_findings)} findings"
        return result

    # Call LLM
    try:
        raw_response = deps.llm_call(_SYNTHESIS_SYSTEM_PROMPT, prompt)
        raw_json = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.error("Epic synthesis LLM response parse error: %s", exc)
        result = SynthesisMutationResult()
        result.strategy_summary = f"Synthesis failed: {exc}"
        return result

    synthesis = parse_synthesis_result(raw_json, valid_ids)
    return apply_synthesis_to_plan(plan, state, synthesis, trigger=trigger)


__all__ = [
    "DismissedFinding",
    "FINDING_ID_RE",
    "SynthesisDeps",
    "SynthesisInput",
    "SynthesisMutationResult",
    "SynthesisResult",
    "apply_synthesis_to_plan",
    "build_synthesis_prompt",
    "collect_synthesis_input",
    "detect_recurring_patterns",
    "extract_finding_citations",
    "last_real_review_timestamp",
    "parse_synthesis_result",
    "synthesize_epics",
]
