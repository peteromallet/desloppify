"""State-backed work queue for review findings.

Review findings live in state["findings"]. This module provides:
- Listing/sorting open review findings by impact
- Rendering issue details from state on demand
- Storing investigation notes on findings
- Expiring stale holistic findings during scan
"""

from __future__ import annotations

from datetime import datetime, timezone


def finding_weight(finding: dict) -> tuple[float, float, str]:
    """Compute (weight, impact_pts, finding_id) for a finding.

    Returns the scoring weight, estimated score impact in points,
    and the finding ID as a stable tiebreaker for deterministic ordering.
    """
    from .scoring import CONFIDENCE_WEIGHTS, HOLISTIC_MULTIPLIER

    conf = finding.get("confidence", "low")
    is_holistic = finding.get("detail", {}).get("holistic", False)

    if is_holistic:
        weight = CONFIDENCE_WEIGHTS.get(conf, 0.3) * HOLISTIC_MULTIPLIER
    else:
        weight = CONFIDENCE_WEIGHTS.get(conf, 0.3)

    return weight, weight, finding.get("id", "")


def impact_label(weight: float) -> str:
    """Convert weight to a human-readable impact label."""
    if weight >= 8:
        return "+++"
    elif weight >= 5:
        return "++"
    return "+"


def list_open_review_findings(state: dict) -> list[dict]:
    """Return open review findings sorted by impact (highest first)."""
    findings = state.get("findings", {})
    review = [
        f for f in findings.values()
        if f.get("status") == "open" and f.get("detector") == "review"
    ]
    def _sort_key(f):
        w, _, fid = finding_weight(f)
        return (-w, fid)
    review.sort(key=_sort_key)
    return review


def update_investigation(state: dict, finding_id: str, text: str) -> bool:
    """Store investigation text on a finding. Returns False if not found/not open."""
    finding = state.get("findings", {}).get(finding_id)
    if not finding or finding.get("status") != "open":
        return False
    detail = finding.setdefault("detail", {})
    detail["investigation"] = text
    detail["investigated_at"] = datetime.now(timezone.utc).isoformat()
    return True


def expire_stale_holistic(state: dict, max_age_days: int = 30) -> list[str]:
    """Auto-resolve holistic review findings older than max_age_days.

    Returns list of expired finding IDs.
    """
    now = datetime.now(timezone.utc)
    expired: list[str] = []

    for fid, f in state.get("findings", {}).items():
        if f.get("detector") != "review":
            continue
        if f.get("status") != "open":
            continue
        if not f.get("detail", {}).get("holistic"):
            continue

        last_seen = f.get("last_seen")
        if not last_seen:
            continue

        try:
            seen_dt = datetime.fromisoformat(last_seen)
        except (ValueError, TypeError):
            continue

        age_days = (now - seen_dt).days
        if age_days > max_age_days:
            f["status"] = "auto_resolved"
            f["resolved_at"] = now.isoformat()
            f["note"] = "holistic review expired — re-run review to re-evaluate"
            expired.append(fid)

    return expired


def render_issue_detail(finding: dict, lang_name: str,
                         number: int | None = None,
                         subjective_assessments: dict | None = None) -> str:
    """Render one finding as a markdown work order from state."""
    fid = finding["id"]
    detail = finding.get("detail", {})
    is_holistic = detail.get("holistic", False)
    dimension = detail.get("dimension", "unknown").replace("_", " ")
    confidence = finding.get("confidence", "low")

    # Identifier from finding ID
    parts = fid.split("::")
    if len(parts) >= 3:
        identifier = parts[-2]
    else:
        identifier = finding.get("file", "unknown")

    weight, impact_pts, _fid = finding_weight(finding)
    label = impact_label(weight)

    lines: list[str] = []
    _w = lines.append

    _w(f"# {dimension}: {identifier}\n")
    _w(f"**Finding**: `{fid}`  ")
    _w(f"**Dimension**: {dimension} | **Confidence**: {confidence}  ")
    _w(f"**Score impact**: {label} (~{impact_pts:.1f} pts)\n")

    # Assessment context
    if subjective_assessments:
        dim_key = detail.get("dimension", "")
        assessment = subjective_assessments.get(dim_key)
        if assessment:
            source = assessment.get("source", "review")
            assessed_at = assessment.get("assessed_at", "")[:10]
            _w(f"**Dimension assessment**: {dimension} — {assessment['score']}/100 "
               f"({source} review, {assessed_at})")
            _w("Fixing this issue and re-reviewing should improve the "
               f"{dimension} score.\n")

    # Problem
    _w("## Problem\n")
    _w(f"{finding.get('summary', '')}\n")

    # Evidence
    evidence = detail.get("evidence", [])
    if evidence:
        _w("## Evidence\n")
        for ev in evidence:
            _w(f"- {ev}")
        _w("")

    # Evidence lines (per-file findings)
    evidence_lines = detail.get("evidence_lines", [])
    if evidence_lines:
        _w("## Code References\n")
        for ev in evidence_lines:
            _w(f"- {ev}")
        _w("")

    # Suggested fix
    suggestion = detail.get("suggestion", "")
    if suggestion:
        _w("## Suggested Fix\n")
        _w(f"{suggestion}\n")

    # Files
    if is_holistic:
        related_files = detail.get("related_files", [])
        if related_files:
            _w("## Files\n")
            for rf in related_files:
                _w(f"- `{rf}`")
            _w("")
    else:
        file_path = finding.get("file", "")
        if file_path and file_path != ".":
            _w("## Files\n")
            _w(f"- `{file_path}`")
            _w("")

    # Why this matters
    reasoning = detail.get("reasoning", "")
    if reasoning:
        _w("## Why This Matters\n")
        _w(f"{reasoning}\n")

    # Investigation section (if present)
    investigation = detail.get("investigation")
    if investigation:
        investigated_at = detail.get("investigated_at", "")
        date_str = ""
        if investigated_at:
            try:
                dt = datetime.fromisoformat(investigated_at)
                date_str = f" ({dt.strftime('%Y-%m-%d')})"
            except (ValueError, TypeError):
                pass
        _w(f"## Investigation{date_str}\n")
        _w(f"{investigation}\n")

    # Status-aware footer
    if investigation:
        _w("## Ready to Fix\n")
        _w("When done:\n")
        _w("```bash")
        _w(f'desloppify --lang {lang_name} resolve fixed "{fid}"')
        _w("```\n")
    else:
        num_str = str(number) if number is not None else "<number>"
        _w("## Status: Needs Investigation\n")
        _w("Investigate the files above, then resolve with a note:\n")
        _w("```bash")
        _w(f'desloppify --lang {lang_name} resolve fixed "{fid}" --note "description of fix"')
        _w("```\n")
        _w("Or save detailed analysis first:\n")
        _w("```bash")
        _w(f"desloppify --lang {lang_name} issues update {num_str} --file analysis.md")
        _w("```\n")

    return "\n".join(lines)
