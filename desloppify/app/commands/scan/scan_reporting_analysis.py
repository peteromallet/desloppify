"""Post-scan narrative and integrity reporting."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.engine.plan import has_living_plan, load_plan
from desloppify.intelligence import narrative as narrative_mod
from desloppify.core.output_api import colorize


def _coerce_coverage_confidence(value: object, *, default: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _current_scan_coverage(state: dict, lang) -> dict:
    scan_coverage = state.get("scan_coverage", {})
    if not isinstance(scan_coverage, dict):
        return {}
    lang_name = getattr(lang, "name", None) if lang is not None else None
    if isinstance(lang_name, str) and lang_name:
        entry = scan_coverage.get(lang_name, {})
        return entry if isinstance(entry, dict) else {}
    return {}


def _coverage_reduction_warnings(state: dict, lang) -> list[str]:
    coverage = _current_scan_coverage(state, lang)
    detectors = coverage.get("detectors", {})
    if not isinstance(detectors, dict):
        return []

    warnings: list[str] = []
    for detector, payload in detectors.items():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "full")).strip().lower()
        confidence = _coerce_coverage_confidence(payload.get("confidence"), default=1.0)
        if status != "reduced" and confidence >= 1.0:
            continue

        summary = str(payload.get("summary", "")).strip()
        impact = str(payload.get("impact", "")).strip()
        remediation = str(payload.get("remediation", "")).strip()
        detector_label = str(detector).strip() or "detector"

        line = f"Coverage reduced ({detector_label}): {summary or 'reduced detector confidence.'}"
        if impact:
            line += f" Repercussion: {impact}"
        if remediation:
            line += f" Fix: {remediation}"
        warnings.append(line)
    return warnings


def show_post_scan_analysis(
    diff: dict,
    state: dict,
    lang,
    *,
    target_strict_score: float = 95.0,
) -> tuple[list[str], dict]:
    """Print critical warnings + headline + pointers. Returns (warnings, narrative)."""
    # Critical warnings only (reopened, cascading, chronic, coverage reduction)
    warnings: list[str] = []
    if diff["reopened"] > 5:
        warnings.append(
            f"{diff['reopened']} findings reopened — was a previous fix reverted?"
        )
    if diff["new"] > 10 and diff["auto_resolved"] < 3:
        warnings.append(
            f"{diff['new']} new findings with few resolutions — likely cascading."
        )
    chronic = diff.get("chronic_reopeners", [])
    chronic_count = len(chronic) if isinstance(chronic, list) else chronic
    if chronic_count > 0:
        warnings.append(
            f"⟳ {chronic_count} chronic reopener{'s' if chronic_count != 1 else ''} — "
            "run `desloppify show --chronic` to see them."
        )
    warnings.extend(_coverage_reduction_warnings(state, lang))

    for warning in warnings:
        print(colorize(f"  {warning}", "yellow"))
    if warnings:
        print()

    # Load plan for narrative cluster awareness
    _plan_data = None
    _plan = load_plan()
    if _plan.get("queue_order") or _plan.get("clusters"):
        _plan_data = _plan

    # Single narrative headline
    lang_name = lang.name if lang else None
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(
            diff=diff,
            lang=lang_name,
            command="scan",
            plan=_plan_data,
        ),
    )
    if narrative.get("headline"):
        print(colorize(f"  → {narrative['headline']}", "cyan"))

    # Pointers — include plan reference when active
    _has_plan = _plan_data is not None or has_living_plan()

    print(colorize("  Run `desloppify next` for the highest-priority item.", "dim"))
    if _has_plan:
        print(colorize("  Run `desloppify plan` to see the updated living plan.", "dim"))
    print(colorize("  Run `desloppify status` for the full dashboard.", "dim"))
    print()

    return warnings, narrative


def show_score_integrity(state: dict, diff: dict):
    """Show Score Integrity section — surfaces wontfix debt and ignored findings."""
    stats = state.get("stats", {})
    wontfix = stats.get("wontfix", 0)
    ignored = diff.get("ignored", 0)
    ignore_patterns = diff.get("ignore_patterns", 0)
    score_confidence = state.get("score_confidence", {})
    confidence_reduced = (
        isinstance(score_confidence, dict)
        and str(score_confidence.get("status", "full")).lower() == "reduced"
    )

    if wontfix <= 5 and ignored <= 0 and ignore_patterns <= 0 and not confidence_reduced:
        return

    overall = state_mod.get_overall_score(state)
    strict = state_mod.get_strict_score(state)
    strict_gap = (
        round(overall - strict, 1) if overall is not None and strict is not None else 0
    )

    # Wontfix % of actionable findings (open + wontfix + fixed + auto_resolved + false_positive)
    actionable = (
        stats.get("open", 0)
        + wontfix
        + stats.get("fixed", 0)
        + stats.get("auto_resolved", 0)
        + stats.get("false_positive", 0)
    )
    wontfix_pct = round(wontfix / actionable * 100) if actionable else 0

    print(colorize("  " + "┄" * 2 + " Score Integrity " + "┄" * 37, "dim"))

    if wontfix > 5:
        if wontfix_pct > 50:
            style = "red"
            msg = (
                f"  ❌ {wontfix} wontfix ({wontfix_pct}%) — over half of findings swept under rug. "
                f"Strict gap: {strict_gap} pts"
            )
        elif wontfix_pct > 25:
            style = "yellow"
            msg = (
                f"  ⚠ {wontfix} wontfix ({wontfix_pct}%) — review whether past "
                "wontfix decisions still hold"
            )
        elif wontfix_pct > 10:
            style = "yellow"
            msg = (
                f"  ⚠ {wontfix} wontfix findings ({wontfix_pct}%) — strict {strict_gap} "
                "pts below lenient"
            )
        else:
            style = "dim"
            msg = f"  {wontfix} wontfix — strict gap: {strict_gap} pts"
        print(colorize(msg, style))

        # Show top 2 dimensions with biggest strict gap
        dim_scores = state.get("dimension_scores", {})
        if dim_scores:
            gaps = []
            for name, data in dim_scores.items():
                score = data.get("score", 100)
                strict_value = data.get("strict", score)
                gap = round(score - strict_value, 1)
                if gap > 0:
                    gaps.append((name, gap))
            gaps.sort(key=lambda x: -x[1])
            if gaps:
                top = gaps[:2]
                gap_str = ", ".join(f"{name} (−{gap} pts)" for name, gap in top)
                print(colorize(f"    Biggest gaps: {gap_str}", "dim"))

    if ignored > 0:
        style = "red" if ignore_patterns > 5 or ignored > 100 else "yellow"
        print(
            colorize(
                f"  ⚠ {ignore_patterns} ignore pattern{'s' if ignore_patterns != 1 else ''} "
                f"suppressed {ignored} finding{'s' if ignored != 1 else ''} this scan",
                style,
            )
        )
        print(
            colorize(
                "    Suppressed findings still count against strict and verified scores",
                "dim",
            )
        )
    elif ignore_patterns > 0:
        print(
            colorize(
                f"  {ignore_patterns} ignore pattern{'s' if ignore_patterns != 1 else ''} "
                "active (0 findings suppressed this scan)",
                "dim",
            )
        )

    if confidence_reduced:
        impacted_dimensions = score_confidence.get("dimensions", [])
        detectors = score_confidence.get("detectors", [])
        confidence = _coerce_coverage_confidence(
            score_confidence.get("confidence"),
            default=1.0,
        )
        dim_text = ""
        if isinstance(impacted_dimensions, list) and impacted_dimensions:
            preview = ", ".join(str(item) for item in impacted_dimensions[:3])
            if len(impacted_dimensions) > 3:
                preview += f", +{len(impacted_dimensions) - 3} more"
            dim_text = f" (dimensions: {preview})"
        print(
            colorize(
                f"  ⚠ Score confidence reduced to {confidence * 100:.0f}%{dim_text}",
                "yellow",
            )
        )
        if isinstance(detectors, list):
            for detector in detectors[:3]:
                if not isinstance(detector, dict):
                    continue
                summary = str(detector.get("summary", "")).strip()
                remediation = str(detector.get("remediation", "")).strip()
                if summary:
                    print(colorize(f"    - {summary}", "dim"))
                if remediation:
                    print(colorize(f"      Fix: {remediation}", "dim"))

    print(colorize("  " + "┄" * 55, "dim"))
    print()


__all__ = ["show_post_scan_analysis", "show_score_integrity"]  # show_score_integrity used by status
