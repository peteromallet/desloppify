"""Remediation plan generation from holistic review findings."""

from __future__ import annotations

from pathlib import Path

from ..state import utc_now


def generate_remediation_plan(state: dict, lang_name: str, *,
                               output_path: Path | None = None) -> str:
    """Generate a prioritized markdown remediation plan from open holistic findings.

    Computes score impact per finding, sorts by impact, and produces a
    structured document the user can work through.

    Returns the markdown content. If *output_path* is given, also writes the file.
    """
    from ..scoring import CONFIDENCE_WEIGHTS, HOLISTIC_MULTIPLIER

    findings = state.get("findings", {})
    holistic = [
        (fid, f) for fid, f in findings.items()
        if f["status"] == "open"
        and f.get("detector") == "review"
        and f.get("detail", {}).get("holistic")
    ]

    if not holistic:
        content = _empty_plan(state, lang_name)
        if output_path:
            from ..utils import safe_write_text
            safe_write_text(output_path, content)
        return content

    obj_score = state.get("objective_score") or 0
    obj_strict = state.get("objective_strict") or 0

    # Get review potential for score impact estimation
    potential = 0
    for lang_pots in state.get("potentials", {}).values():
        potential += lang_pots.get("review", 0)

    # Compute weight and estimated impact per finding
    entries = []
    total_weight = 0.0
    for fid, f in holistic:
        conf = f.get("confidence", "low")
        weight = CONFIDENCE_WEIGHTS.get(conf, 0.3) * HOLISTIC_MULTIPLIER
        detail = f.get("detail", {})
        entries.append({
            "id": fid,
            "dimension": detail.get("dimension", "unknown"),
            "summary": f.get("summary", ""),
            "confidence": conf,
            "weight": weight,
            "impact_pts": (weight / potential * 100) if potential > 0 else 0,
            "related_files": detail.get("related_files", []),
            "evidence": detail.get("evidence", []),
            "suggestion": detail.get("suggestion", ""),
            "reasoning": detail.get("reasoning", ""),
        })
        total_weight += weight

    entries.sort(key=lambda x: -x["weight"])
    total_impact = (total_weight / potential * 100) if potential > 0 else 0

    lines: list[str] = []
    _w = lines.append

    _w("# Holistic Review: Remediation Plan\n")
    _w(f"**Generated**: {utc_now()[:10]}  ")
    _w(f"**Current score**: {obj_score:.1f}/100 (strict: {obj_strict:.1f}/100)  ")
    _w(f"**Open holistic findings**: {len(entries)}  ")
    _w(f"**Estimated improvement**: ~{total_impact:.1f} pts if all addressed\n")
    _w("---\n")

    _w("## How to use this plan\n")
    _w("1. Work through findings in priority order (highest impact first)")
    _w("2. For each finding, follow the suggested fix steps")
    _w("3. After fixing, run the `resolve` command shown for that finding")
    _w("4. Run `desloppify scan` to update automated findings and score")
    _w("5. To re-evaluate holistic issues, re-run the full cycle:")
    _w(f"   `desloppify --lang {lang_name} review --prepare --holistic --path <src>`")
    _w("   Then have an agent investigate and import — previously addressed")
    _w("   findings auto-resolve if not re-reported.\n")
    _w("---\n")

    for i, entry in enumerate(entries, 1):
        stars = 3 if entry["weight"] >= 8 else 2 if entry["weight"] >= 5 else 1
        impact_label = "+" * stars

        _w(f"## Priority {i}: {entry['summary']}\n")
        _w(f"**Dimension**: {entry['dimension'].replace('_', ' ')} | "
           f"**Confidence**: {entry['confidence']} | "
           f"**Impact**: {impact_label} (~{entry['impact_pts']:.1f} pts)\n")

        if entry["evidence"]:
            _w("### Evidence\n")
            for ev in entry["evidence"]:
                _w(f"- {ev}")
            _w("")

        if entry["suggestion"]:
            _w("### Suggested fix\n")
            _w(f"{entry['suggestion']}\n")

        if entry["related_files"]:
            _w("### Files to modify\n")
            for rf in entry["related_files"]:
                _w(f"- `{rf}`")
            _w("")

        if entry["reasoning"]:
            _w("### Why this matters\n")
            _w(f"{entry['reasoning']}\n")

        _w("### After fixing\n")
        _w("```bash")
        _w(f"desloppify --lang {lang_name} resolve fixed \"{entry['id']}\"")
        _w("```\n")
        _w("---\n")

    _w("## Re-evaluate\n")
    _w("After addressing findings, re-run the holistic review cycle:\n")
    _w("```bash")
    _w(f"desloppify --lang {lang_name} review --prepare --holistic --path <src>")
    _w("# Agent investigates batches and writes findings.json")
    _w(f"desloppify --lang {lang_name} review --import findings.json --holistic")
    _w("```\n")
    _w("Previously addressed findings will auto-resolve if not re-reported by the agent.")
    _w("")

    content = "\n".join(lines)
    if output_path:
        from ..utils import safe_write_text
        safe_write_text(output_path, content)
    return content


def _empty_plan(state: dict, lang_name: str) -> str:
    """Generate a short plan when no holistic findings are open."""
    obj_score = state.get("objective_score") or 0
    return (
        "# Holistic Review: Remediation Plan\n\n"
        f"**Score**: {obj_score:.1f}/100\n\n"
        "No open holistic findings. The codebase is clean at the architectural level.\n\n"
        "To start a new holistic review cycle:\n"
        "```bash\n"
        f"desloppify --lang {lang_name} review --prepare --holistic --path <src>\n"
        "```\n"
    )
