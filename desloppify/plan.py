"""Finding generation (detector → findings), tier assignment, plan output.

Runs all detectors, converts raw results into normalized findings with stable IDs,
assigns tiers, and generates prioritized plans.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from .utils import colorize

TIER_LABELS = {
    1: "Auto-fixable (imports, logs, dead deprecated)",
    2: "Quick fixes (unused vars, dead exports, exact dupes, orphaned files, cross-tool imports)",
    3: "Needs judgment (smells, near-dupes, single-use, small cycles, state sync)",
    4: "Major refactors (structural decomposition, large import cycles)",
}

CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def generate_findings(
    path: Path, *, include_slow: bool = True, lang=None,
    zone_overrides: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Run all detectors and convert results to normalized findings.

    Dispatches through the LangConfig phase pipeline.
    Auto-detects language when none is specified.
    Returns (findings, potentials) where potentials maps detector names to checked counts.
    """
    if lang is None:
        from .lang import get_lang, auto_detect_lang, available_langs
        from .utils import PROJECT_ROOT
        detected = auto_detect_lang(PROJECT_ROOT)
        if detected is None:
            langs = available_langs()
            if not langs:
                raise ValueError("No language plugins available")
            detected = langs[0]
        lang = get_lang(detected)
    return _generate_findings_from_lang(path, lang, include_slow=include_slow,
                                         zone_overrides=zone_overrides)


def _generate_findings_from_lang(
    path: Path, lang, *, include_slow: bool = True,
    zone_overrides: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Run detector phases from a LangConfig."""
    stderr = lambda msg: print(colorize(msg, "dim"), file=sys.stderr)

    # Build zone map if language has zone rules
    if lang.zone_rules and lang.file_finder:
        from .zones import FileZoneMap, ZONE_POLICIES
        from .utils import rel
        files = lang.file_finder(path)
        lang._zone_map = FileZoneMap(files, lang.zone_rules, rel_fn=rel,
                                      overrides=zone_overrides)
        counts = lang._zone_map.counts()
        zone_str = ", ".join(f"{z}: {n}" for z, n in sorted(counts.items()) if n > 0)
        stderr(f"  Zones: {zone_str}")

    phases = lang.phases
    if not include_slow:
        phases = [p for p in phases if not p.slow]

    findings: list[dict] = []
    all_potentials: dict[str, int] = {}
    total = len(phases)
    for i, phase in enumerate(phases):
        stderr(f"  [{i+1}/{total}] {phase.label}...")
        phase_findings, phase_potentials = phase.run(path, lang)
        all_potentials.update(phase_potentials)
        findings += phase_findings

    # Stamp language and zone on all findings
    for f in findings:
        f["lang"] = lang.name
        if lang._zone_map is not None:
            zone = lang._zone_map.get(f.get("file", ""))
            f["zone"] = zone.value
            # Apply zone policy confidence downgrades
            policy = ZONE_POLICIES.get(zone)
            if policy and f.get("detector") in policy.downgrade_detectors:
                f["confidence"] = "low"

    stderr(f"\n  Total: {len(findings)} findings")
    return findings, all_potentials


def _plan_header(state: dict, stats: dict) -> list[str]:
    """Build the plan header: title, score line, and codebase metrics."""
    from .state import get_overall_score, get_objective_score, get_strict_score

    overall_score = get_overall_score(state)
    objective_score = get_objective_score(state)
    strict_score = get_strict_score(state)
    if overall_score is not None and objective_score is not None and strict_score is not None:
        header_score = (
            f"**Health:** overall {overall_score:.1f}/100 | "
            f"objective {objective_score:.1f}/100 | "
            f"strict {strict_score:.1f}/100"
        )
    elif overall_score is not None:
        header_score = f"**Score: {overall_score:.1f}/100**"
    else:
        header_score = "**Scores unavailable**"

    # Codebase metrics
    metrics = state.get("codebase_metrics", {})
    total_files = sum(m.get("total_files", 0) for m in metrics.values())
    total_loc = sum(m.get("total_loc", 0) for m in metrics.values())
    total_dirs = sum(m.get("total_directories", 0) for m in metrics.values())

    lines = [
        f"# Desloppify Plan — {date.today().isoformat()}",
        "",
        f"{header_score} | "
        f"{stats.get('open', 0)} open | "
        f"{stats.get('fixed', 0)} fixed | "
        f"{stats.get('wontfix', 0)} wontfix | "
        f"{stats.get('auto_resolved', 0)} auto-resolved",
        "",
    ]
    if total_files:
        from .utils import LOC_COMPACT_THRESHOLD
        loc_str = f"{total_loc:,}" if total_loc < LOC_COMPACT_THRESHOLD else f"{total_loc // 1000}K"
        lines.append(f"\n{total_files} files · {loc_str} LOC · {total_dirs} directories\n")

    return lines


def _plan_dimension_table(state: dict) -> list[str]:
    """Build the dimension health table rows (empty list when no data)."""
    dim_scores = state.get("dimension_scores", {})
    if not dim_scores:
        return []

    lines = [
        "## Health by Dimension",
        "",
        "| Dimension | Tier | Checks | Issues | Health | Strict | Action |",
        "|-----------|------|--------|--------|--------|--------|--------|",
    ]
    from .scoring import DIMENSIONS
    from .registry import dimension_action_type
    static_names: set[str] = set()
    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        static_names.add(dim.name)
        checks = ds.get("checks", 0)
        issues = ds.get("issues", 0)
        score_val = ds.get("score", 100)
        strict_val = ds.get("strict", score_val)
        bold = "**" if score_val < 93 else ""
        action = dimension_action_type(dim.name)
        lines.append(
            f"| {bold}{dim.name}{bold} | T{dim.tier} | "
            f"{checks:,} | {issues} | {score_val:.1f}% | {strict_val:.1f}% | {action} |"
        )
    # Append subjective dimensions not in static DIMENSIONS
    assessment_dims = [(name, ds) for name, ds in sorted(dim_scores.items())
                       if name not in static_names]
    if assessment_dims:
        lines.append("| **Subjective Dimensions** | | | | | | |")
        for name, ds in assessment_dims:
            issues = ds.get("issues", 0)
            score_val = ds.get("score", 100)
            strict_val = ds.get("strict", score_val)
            tier = ds.get("tier", 4)
            bold = "**" if score_val < 93 else ""
            lines.append(
                f"| {bold}{name}{bold} | T{tier} | "
                f"— | {issues} | {score_val:.1f}% | {strict_val:.1f}% | review |"
            )
    lines.append("")
    return lines


def _plan_tier_sections(findings: dict) -> list[str]:
    """Build per-tier sections listing open findings grouped by file."""
    open_findings = [f for f in findings.values() if f["status"] == "open"]
    by_tier_file: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for f in open_findings:
        by_tier_file[f["tier"]][f["file"]].append(f)

    lines: list[str] = []
    for tier_num in [1, 2, 3, 4]:
        tier_files = by_tier_file.get(tier_num, {})
        if not tier_files:
            continue
        label = TIER_LABELS.get(tier_num, f"Tier {tier_num}")
        tier_count = sum(len(fs) for fs in tier_files.values())
        lines.extend([
            "---",
            f"## Tier {tier_num}: {label} ({tier_count} open)",
            "",
        ])

        # Sort files by finding count (most findings first)
        sorted_files = sorted(tier_files.items(), key=lambda x: -len(x[1]))
        for filepath, file_findings in sorted_files:
            # Sort findings within file: high confidence first
            file_findings.sort(key=lambda f: (CONFIDENCE_ORDER.get(f["confidence"], 9), f["id"]))
            lines.append(f"### `{filepath}` ({len(file_findings)} findings)")
            lines.append("")
            for f in file_findings:
                conf_badge = f"[{f['confidence']}]"
                lines.append(f"- [ ] {conf_badge} {f['summary']}")
                lines.append(f"      `{f['id']}`")
            lines.append("")

    return lines


def generate_plan_md(state: dict) -> str:
    """Generate a prioritized markdown plan from state."""
    findings = state["findings"]
    stats = state.get("stats", {})

    lines = _plan_header(state, stats)
    lines.extend(_plan_dimension_table(state))

    # Tier breakdown summary
    by_tier = stats.get("by_tier", {})
    for tier_num in [1, 2, 3, 4]:
        ts = by_tier.get(str(tier_num), {})
        t_open = ts.get("open", 0)
        t_total = sum(ts.values())
        t_addressed = t_total - t_open
        pct = round(t_addressed / t_total * 100) if t_total else 100
        label = TIER_LABELS.get(tier_num, f"Tier {tier_num}")
        lines.append(f"- **Tier {tier_num}** ({label}): {t_open} open / {t_total} total ({pct}% addressed)")
    lines.append("")

    # Per-tier open finding sections
    lines.extend(_plan_tier_sections(findings))

    # Addressed findings summary
    addressed = [f for f in findings.values() if f["status"] != "open"]
    if addressed:
        by_status: dict[str, int] = defaultdict(int)
        for f in addressed:
            by_status[f["status"]] += 1
        lines.extend([
            "---",
            "## Addressed",
            "",
        ])
        for status, count in sorted(by_status.items()):
            lines.append(f"- **{status}**: {count}")

        # Show wontfix items with their reasons
        wontfix = [f for f in addressed if f["status"] == "wontfix" and f.get("note")]
        if wontfix:
            lines.extend(["", "### Wontfix (with explanations)", ""])
            for f in wontfix[:30]:
                lines.append(f"- `{f['id']}` — {f['note']}")
        lines.append("")

    return "\n".join(lines)


def get_next_item(state: dict, tier: int | None = None,
                  scan_path: str | None = None) -> dict | None:
    """Get the highest-priority open finding."""
    items = get_next_items(state, tier, 1, scan_path=scan_path)
    return items[0] if items else None


def get_next_items(state: dict, tier: int | None = None, count: int = 1,
                   scan_path: str | None = None) -> list[dict]:
    """Get the N highest-priority open findings.

    Priority: tier (ascending) → confidence (high first) → detail count.
    When scan_path is set, only returns findings within that path.
    """
    from .state import path_scoped_findings
    findings = path_scoped_findings(state["findings"], scan_path)
    open_findings = [f for f in findings.values() if f["status"] == "open"]
    if tier is not None:
        open_findings = [f for f in open_findings if f["tier"] == tier]
    if not open_findings:
        return []

    open_findings.sort(key=lambda f: (
        f["tier"],
        CONFIDENCE_ORDER.get(f["confidence"], 9),
        -f.get("detail", {}).get("count", 0),
        f["id"],
    ))
    return open_findings[:count]
