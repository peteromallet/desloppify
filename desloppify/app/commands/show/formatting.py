"""Formatting helpers for show command rendering."""

from __future__ import annotations

DETAIL_DISPLAY = [
    ("line", "line", None),
    ("lines", "lines", lambda v: ", ".join(str(line_no) for line_no in v[:5])),
    ("category", "category", None),
    ("importers", "importers", None),
    ("count", "count", None),
    ("kind", "kind", None),
    ("signals", "signals", lambda v: ", ".join(v[:3])),
    ("concerns", "concerns", lambda v: ", ".join(v[:3])),
    ("hook_total", "hooks", None),
    ("prop_count", "props", None),
    ("smell_id", "smell", None),
    ("target", "target", None),
    ("sole_tool", "sole tool", None),
    ("direction", "direction", None),
    ("family", "family", None),
    ("patterns_used", "patterns", lambda v: ", ".join(v)),
    (
        "related_files",
        "related files",
        lambda v: ", ".join(v[:5]) + (f" +{len(v) - 5}" if len(v) > 5 else ""),
    ),
    ("review", "review", lambda v: v[:80]),
    ("majority", "majority", None),
    ("minority", "minority", None),
    ("outliers", "outliers", lambda v: ", ".join(v[:5])),
]


def _append_fn_pair_detail(parts: list[str], detail: dict) -> None:
    if not detail.get("fn_a"):
        return
    a, b = detail["fn_a"], detail["fn_b"]
    parts.append(f"{a['name']}:{a.get('line', '')} ↔ {b['name']}:{b.get('line', '')}")


def _append_pattern_evidence(parts: list[str], detail: dict) -> None:
    pattern_evidence = detail.get("pattern_evidence")
    if not isinstance(pattern_evidence, dict) or not pattern_evidence:
        return
    summary_parts = []
    for pattern_name, hits in pattern_evidence.items():
        if isinstance(hits, list):
            summary_parts.append(f"{pattern_name}:{len(hits)} file(s)")
    if summary_parts:
        parts.append(f"evidence: {', '.join(summary_parts)}")


def format_detail(detail: dict) -> list[str]:
    """Build display parts from a finding's detail dict."""
    parts: list[str] = []
    for key, label, formatter in DETAIL_DISPLAY:
        value = detail.get(key)
        if value is None or value == 0:
            if key == "importers" and value is not None:
                parts.append(f"{label}: {value}")
            continue
        parts.append(f"{label}: {formatter(value) if formatter else value}")

    _append_fn_pair_detail(parts, detail)
    _append_pattern_evidence(parts, detail)

    return parts


def suppressed_match_estimate(pattern: str, hidden_by_detector: dict[str, int]) -> int:
    """Estimate hidden-match count for a show pattern using detector-level noise totals."""
    if not isinstance(pattern, str) or not isinstance(hidden_by_detector, dict):
        return 0
    detector = pattern.split("::", 1)[0]
    return int(hidden_by_detector.get(detector, 0))


__all__ = ["DETAIL_DISPLAY", "format_detail", "suppressed_match_estimate"]
