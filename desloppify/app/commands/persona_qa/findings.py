"""Issue creation and import for persona QA findings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from desloppify.engine._state.issue_semantics import ensure_work_item_semantics
from desloppify.engine._state.schema import (
    Issue,
    StateModel,
    ensure_state_defaults,
    utc_now,
)


_SLUG_RE = re.compile(r"[^a-z0-9]+")

CONFIDENCE_MAP = {"blocker": "high", "usability": "medium", "polish": "low"}
TIER_MAP = {"blocker": 2, "usability": 3, "polish": 3}


def _slug(text: str) -> str:
    """Convert text to a URL-safe slug."""
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:60]


def make_browser_issue(
    persona: str,
    route: str,
    scenario: str,
    check: str,
    *,
    severity: str,
    summary: str,
    evidence: str,
    screenshot_path: str | None = None,
) -> Issue:
    """Create a WorkItem dict from a browser QA finding."""
    confidence = CONFIDENCE_MAP.get(severity, "medium")
    tier = TIER_MAP.get(severity, 3)
    safe_route = route.strip("/").replace("/", "_") or "root"
    persona_slug = _slug(persona)
    check_slug = _slug(check)
    issue_id = f"persona_qa::{persona_slug}::{safe_route}::{check_slug}"
    now = utc_now()

    issue: Issue = {
        "id": issue_id,
        "detector": "persona_qa",
        "file": route,
        "tier": tier,
        "confidence": confidence,
        "summary": summary,
        "detail": {
            "persona": persona,
            "scenario": scenario,
            "check": check,
            "evidence": evidence,
            "severity": severity,
            "route": route,
            "screenshot": screenshot_path,
        },
        "status": "open",
        "note": None,
        "first_seen": now,
        "last_seen": now,
        "resolved_at": None,
        "reopen_count": 0,
    }
    ensure_work_item_semantics(issue)
    return issue


def import_findings(findings_path: str, state: StateModel) -> tuple[int, int, int]:
    """Import findings JSON into state.

    Returns (created, updated, auto_resolved) counts.
    """
    ensure_state_defaults(state)
    data = json.loads(Path(findings_path).read_text(encoding="utf-8"))

    persona_name = data.get("persona", "unknown")
    now = utc_now()

    # Collect all issue IDs this import touches for reconciliation
    seen_ids: set[str] = set()
    created = 0
    updated = 0

    for scenario_data in data.get("scenarios", []):
        scenario_name = scenario_data.get("name", "")
        route = scenario_data.get("route", "/")
        for check_data in scenario_data.get("checks", []):
            check_text = check_data.get("check", "")
            passed = check_data.get("passed", True)
            severity = check_data.get("severity", "usability")
            evidence = check_data.get("evidence", "")
            screenshot = check_data.get("screenshot", None)

            # Build the issue to get its ID
            issue = make_browser_issue(
                persona=persona_name,
                route=route,
                scenario=scenario_name,
                check=check_text,
                severity=severity,
                summary=f"[{persona_name}] {check_text}: {evidence}" if evidence else f"[{persona_name}] {check_text}",
                evidence=evidence,
                screenshot_path=screenshot,
            )
            seen_ids.add(issue["id"])

            if passed:
                # Check passed — auto-resolve if previously open
                existing = state["work_items"].get(issue["id"])
                if existing and existing["status"] == "open":
                    existing["status"] = "auto_resolved"
                    existing["resolved_at"] = now
                    existing["last_seen"] = now
                    existing["note"] = "Auto-resolved: check now passes"
                continue

            # Check failed — create or update
            existing = state["work_items"].get(issue["id"])
            if existing:
                existing["last_seen"] = now
                existing["status"] = "open"
                existing["resolved_at"] = None
                existing["detail"] = issue["detail"]
                existing["summary"] = issue["summary"]
                if existing.get("reopen_count", 0) > 0 or existing.get("resolved_at"):
                    existing["reopen_count"] = existing.get("reopen_count", 0) + 1
                updated += 1
            else:
                state["work_items"][issue["id"]] = issue
                created += 1

    # Auto-resolve any persona_qa issues for this persona that weren't
    # in the import (scenarios/checks that are no longer tested don't get wiped)
    auto_resolved = 0
    persona_slug = _slug(persona_name)
    prefix = f"persona_qa::{persona_slug}::"
    for issue_id, issue in state["work_items"].items():
        if (
            issue_id.startswith(prefix)
            and issue["status"] == "open"
            and issue_id not in seen_ids
        ):
            # Only auto-resolve if the issue was included in the test run
            # (i.e. same persona) — don't touch issues from other personas
            pass  # Leave untouched — we only reconcile what was explicitly tested

    return created, updated, auto_resolved


def compute_potentials(profiles: list[dict[str, Any]]) -> int:
    """Total check items across all personas — the scoring denominator."""
    total = 0
    for profile in profiles:
        for scenario in profile.get("scenarios", []):
            total += len(scenario.get("check", []))
        total += len(profile.get("accessibility", []))
    return total


__all__ = [
    "compute_potentials",
    "import_findings",
    "make_browser_issue",
]
