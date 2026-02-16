"""show command: dig into findings by file, directory, detector, or pattern."""

from __future__ import annotations

import json
from collections import defaultdict

from ..utils import colorize
from ._helpers import _write_query, state_path
from ._show_terminal import render_show_results


_DETAIL_DISPLAY = [
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
    ("pattern_evidence", "evidence", lambda v: ", ".join(
        f"{k}:{len(v.get(k, []))} file(s)" for k in sorted(v.keys())
    )),
    ("related_files", "related files", lambda v: ", ".join(v[:5]) + (f" +{len(v) - 5}" if len(v) > 5 else "")),
    ("review", "review", lambda v: v[:80]),
    ("majority", "majority", None),
    ("minority", "minority", None),
    ("outliers", "outliers", lambda v: ", ".join(v[:5])),
]


def _format_detail(detail: dict) -> list[str]:
    """Build display parts from a finding's detail dict."""
    parts = []
    for key, label, formatter in _DETAIL_DISPLAY:
        value = detail.get(key)
        if value is None or value == 0:
            if key == "importers" and value is not None:
                parts.append(f"{label}: {value}")
            continue
        parts.append(f"{label}: {formatter(value) if formatter else value}")

    if detail.get("fn_a"):
        left = detail["fn_a"]
        right = detail["fn_b"]
        parts.append(f"{left['name']}:{left.get('line', '')} ↔ {right['name']}:{right.get('line', '')}")
    return parts


def _resolve_matches(state: dict, args, pattern: str, chronic: bool) -> tuple[list[dict], str, str]:
    from ..state import match_findings, path_scoped_findings

    if chronic:
        scoped = path_scoped_findings(state["findings"], state.get("scan_path"))
        matches = [f for f in scoped.values() if f.get("reopen_count", 0) >= 2 and f["status"] == "open"]
        return matches, "open", (pattern or "<chronic>")

    status_filter = getattr(args, "status", "open")
    matches = match_findings(state, pattern, status_filter)
    scoped_ids = set(path_scoped_findings(state["findings"], state.get("scan_path")).keys())
    return [f for f in matches if f["id"] in scoped_ids], status_filter, pattern


def _write_show_query(args, state: dict, payload: dict) -> None:
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang

    lang = resolve_lang(args)
    narrative = compute_narrative(
        state,
        lang=(lang.name if lang else None),
        command="show",
        config=getattr(args, "_config", None),
    )
    _write_query({"command": "show", **payload, "narrative": narrative})


def _write_output_file(output_file: str, matches_count: int, payload: dict) -> None:
    from ..utils import safe_write_text

    try:
        safe_write_text(output_file, json.dumps(payload, indent=2) + "\n")
        print(colorize(f"Wrote {matches_count} findings to {output_file}", "green"))
    except OSError as exc:
        print(colorize(f"Could not write to {output_file}: {exc}", "red"))
        raise SystemExit(1) from exc


def cmd_show(args) -> None:
    """Show all findings for a file, directory, detector, or pattern."""
    from ..state import (
        apply_finding_noise_budget,
        load_state,
        resolve_finding_noise_settings,
    )
    from ..utils import check_tool_staleness

    state = load_state(state_path(args))
    if not state.get("last_scan"):
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
        return

    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    pattern = args.pattern
    chronic = getattr(args, "chronic", False)
    if not chronic and not pattern:
        print(colorize("Pattern required (or use --chronic). Try: desloppify show --help", "yellow"))
        return

    matches, status_filter, pattern = _resolve_matches(state, args, pattern, chronic)
    include_suppressed = getattr(args, "include_suppressed", False)
    if not matches:
        print(colorize(f"No {status_filter} findings matching: {pattern}", "yellow"))
        if include_suppressed:
            ignored_by_detector = (state.get("ignore_integrity", {}) or {}).get("ignored_by_detector", {})
            suppressed = _suppressed_match_estimate(pattern, ignored_by_detector)
            if suppressed > 0:
                print(
                    colorize(
                        f"  ~{suppressed} matching finding(s) were suppressed by ignore patterns in the last scan.",
                        "dim",
                    )
                )
        _write_query({"command": "show", "query": pattern, "status_filter": status_filter, "total": 0, "findings": []})
        return

    noise_budget, global_noise_budget, budget_warning = resolve_finding_noise_settings(args._config)
    surfaced_matches, hidden_by_detector = apply_finding_noise_budget(
        matches,
        budget=noise_budget,
        global_budget=global_noise_budget,
    )
    payload = _build_show_payload(
        surfaced_matches,
        pattern,
        status_filter,
        total_matches=len(matches),
        hidden_by_detector=hidden_by_detector,
        noise_budget=noise_budget,
        global_noise_budget=global_noise_budget,
    )
    _write_show_query(args, state, payload)

    output_file = getattr(args, "output", None)
    if output_file:
        _write_output_file(output_file, len(surfaced_matches), payload)
        return

    render_show_results(
        surfaced_matches,
        pattern=pattern,
        status_filter=status_filter,
        top=(getattr(args, "top", 20) or 20),
        show_code=getattr(args, "code", False),
        noise_budget=noise_budget,
        global_noise_budget=global_noise_budget,
        budget_warning=budget_warning,
        hidden_by_detector=hidden_by_detector,
        format_detail=_format_detail,
    )


def _build_show_payload(
    matches: list[dict],
    pattern: str,
    status_filter: str,
    *,
    meta: dict | None = None,
    **legacy_meta,
) -> dict:
    """Build the structured JSON payload shared by query file and --output."""
    payload_meta = dict(meta or {})
    for key, value in legacy_meta.items():
        payload_meta.setdefault(key, value)
    payload_meta.setdefault("total_matches", None)
    payload_meta.setdefault("hidden_by_detector", None)
    payload_meta.setdefault("noise_budget", None)
    payload_meta.setdefault("global_noise_budget", None)

    by_file: dict[str, list] = defaultdict(list)
    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for finding in matches:
        by_file[finding["file"]].append(finding)
        by_detector[finding["detector"]] += 1
        by_tier[finding["tier"]] += 1

    payload = {
        "query": pattern,
        "status_filter": status_filter,
        "total": len(matches),
        "summary": {
            "by_tier": {f"T{tier}": count for tier, count in sorted(by_tier.items())},
            "by_detector": dict(sorted(by_detector.items(), key=lambda item: -item[1])),
            "files": len(by_file),
        },
        "by_file": {
            filepath: [
                {
                    "id": finding["id"],
                    "tier": finding["tier"],
                    "confidence": finding["confidence"],
                    "summary": finding["summary"],
                    "detail": finding.get("detail", {}),
                }
                for finding in file_findings
            ]
            for filepath, file_findings in sorted(by_file.items(), key=lambda item: -len(item[1]))
        },
    }

    total_matches = payload_meta["total_matches"]
    if total_matches is not None:
        payload["total_matching"] = total_matches
    hidden_by_detector = payload_meta["hidden_by_detector"]
    if hidden_by_detector:
        payload["hidden"] = {"by_detector": hidden_by_detector, "total": sum(hidden_by_detector.values())}
    noise_budget = payload_meta["noise_budget"]
    if noise_budget is not None:
        payload["noise_budget"] = noise_budget
    global_noise_budget = payload_meta["global_noise_budget"]
    if global_noise_budget is not None:
        payload["noise_global_budget"] = global_noise_budget
    return payload


def _suppressed_match_estimate(pattern: str, ignored_by_detector: dict) -> int:
    """Estimate suppressed match count from per-detector ignore stats."""
    if not isinstance(ignored_by_detector, dict) or not pattern:
        return 0
    detector = pattern.split("::", 1)[0]
    return int(ignored_by_detector.get(pattern, ignored_by_detector.get(detector, 0)) or 0)
