"""Transparency and ignore-accountability sections for status output."""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from ..state import path_scoped_findings
from ..utils import colorize, print_table
from ..zones import EXCLUDED_ZONE_VALUES


def show_ignore_summary(
    ignores: list[str],
    suppression: Mapping[str, object],
    *,
    options: Mapping[str, object] | None = None,
    **legacy_options,
) -> None:
    """Show ignore list plus suppression accountability from recent scans."""
    opts: dict[str, object] = dict(options or {})
    for key, value in legacy_options.items():
        opts.setdefault(key, value)
    opts.setdefault("ignore_meta", {})
    opts.setdefault("score_integrity", {})
    opts.setdefault("include_suppressed", False)
    opts.setdefault("ignore_integrity", {})

    ignore_meta = opts["ignore_meta"] if isinstance(opts["ignore_meta"], dict) else {}
    score_integrity = opts["score_integrity"] if isinstance(opts["score_integrity"], dict) else {}
    include_suppressed = bool(opts["include_suppressed"])
    ignore_integrity = opts["ignore_integrity"] if isinstance(opts["ignore_integrity"], dict) else {}

    print(colorize(f"\n  Ignore list ({len(ignores)}):", "dim"))
    for pattern in ignores[:10]:
        note = (ignore_meta.get(pattern) or {}).get("note", "")
        print(colorize(f"    {pattern}  # {note}", "dim") if note else colorize(f"    {pattern}", "dim"))

    last_ignored = int(suppression.get("last_ignored", 0) or 0)
    last_raw = int(suppression.get("last_raw_findings", 0) or 0)
    last_pct = float(suppression.get("last_suppressed_pct", 0.0) or 0.0)
    if last_raw > 0:
        style = "red" if last_pct >= 30 else "yellow" if last_pct >= 10 else "dim"
        print(colorize(f"  Ignore suppression (last scan): {last_ignored}/{last_raw} findings hidden ({last_pct:.1f}%)", style))
    elif suppression.get("recent_scans", 0):
        print(colorize("  Ignore suppression (last scan): 0 findings hidden", "dim"))

    recent_scans = int(suppression.get("recent_scans", 0) or 0)
    recent_raw = int(suppression.get("recent_raw_findings", 0) or 0)
    if recent_scans > 1 and recent_raw > 0:
        recent_ignored = int(suppression.get("recent_ignored", 0) or 0)
        recent_pct = float(suppression.get("recent_suppressed_pct", 0.0) or 0.0)
        print(colorize(f"    Recent ({recent_scans} scans): {recent_ignored}/{recent_raw} findings hidden ({recent_pct:.1f}%)", "dim"))

    warn = score_integrity.get("ignore_suppression_warning")
    if isinstance(warn, dict):
        print(
            colorize(
                f"  Ignore warning: {warn.get('suppressed_pct', 0):.1f}% findings hidden "
                f"({warn.get('ignored', 0)} ignored, {warn.get('ignore_patterns', 0)} patterns)",
                "yellow",
            )
        )

    if not include_suppressed:
        return
    by_detector = ignore_integrity.get("ignored_by_detector", {})
    if isinstance(by_detector, dict) and by_detector:
        pairs = ", ".join(f"{detector}:{count}" for detector, count in sorted(by_detector.items(), key=lambda item: (-item[1], item[0])))
        print(colorize(f"  Suppressed by detector (last scan): {pairs}", "dim"))


def build_detector_transparency(
    state: Mapping[str, object],
    *,
    ignore_integrity: Mapping[str, object] | None = None,
) -> dict:
    """Build strict-failure visibility metrics by detector."""

    ignore_data = dict(ignore_integrity or {}) if isinstance(ignore_integrity, Mapping) else {}
    suppressed_raw = ignore_data.get("ignored_by_detector", {})
    suppressed_by_detector = (
        {key: int(value or 0) for key, value in suppressed_raw.items()}
        if isinstance(suppressed_raw, dict)
        else {}
    )

    visible_by_detector: dict[str, int] = defaultdict(int)
    excluded_by_detector: dict[str, int] = defaultdict(int)
    strict_statuses = {"open", "wontfix"}
    scoped = path_scoped_findings(dict(state.get("findings", {})), state.get("scan_path"))
    for finding in scoped.values():
        if finding.get("status") not in strict_statuses:
            continue
        detector = finding.get("detector", "unknown")
        zone = finding.get("zone", "production")
        if zone in EXCLUDED_ZONE_VALUES:
            excluded_by_detector[detector] += 1
        else:
            visible_by_detector[detector] += 1

    detectors = sorted(set(visible_by_detector) | set(excluded_by_detector) | set(suppressed_by_detector))
    rows = []
    for detector in detectors:
        visible = visible_by_detector.get(detector, 0)
        suppressed = suppressed_by_detector.get(detector, 0)
        excluded = excluded_by_detector.get(detector, 0)
        rows.append(
            {
                "detector": detector,
                "visible": visible,
                "suppressed": suppressed,
                "excluded": excluded,
                "total_detected": visible + suppressed + excluded,
            }
        )
    rows.sort(key=lambda row: (-row["total_detected"], row["detector"]))
    return {
        "rows": rows,
        "totals": {
            "visible": sum(row["visible"] for row in rows),
            "suppressed": sum(row["suppressed"] for row in rows),
            "excluded": sum(row["excluded"] for row in rows),
            "detectors": len(rows),
        },
    }


def show_detector_transparency(transparency: dict) -> None:
    """Render detector-level strict visibility metrics."""
    if not isinstance(transparency, dict):
        return
    rows = transparency.get("rows", [])
    totals = transparency.get("totals", {})
    if not rows:
        return

    suppressed_total = int(totals.get("suppressed", 0) or 0)
    excluded_total = int(totals.get("excluded", 0) or 0)
    if suppressed_total <= 0 and excluded_total <= 0:
        return

    table_rows = [
        [row["detector"], str(row["visible"]), str(row["suppressed"]), str(row["excluded"]), str(row["total_detected"])]
        for row in rows
        if row["suppressed"] > 0 or row["excluded"] > 0
    ]
    if not table_rows:
        return

    print(colorize("\n  Strict Transparency (last scan):", "bold"))
    print_table(["Detector", "Visible", "Suppressed", "Excluded", "All"], table_rows, [24, 8, 11, 9, 6])

    visible_total = int(totals.get("visible", 0) or 0)
    hidden_total = suppressed_total + excluded_total
    all_total = visible_total + hidden_total
    if all_total <= 0:
        return
    hidden_pct = round(hidden_total / all_total * 100, 1)
    style = "red" if hidden_pct >= 40 else "yellow" if hidden_pct >= 20 else "dim"
    print(colorize(f"  Hidden strict failures: {hidden_total}/{all_total} ({hidden_pct:.1f}%)", style))
