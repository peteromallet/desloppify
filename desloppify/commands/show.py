"""show command: dig into findings by file, directory, detector, or pattern."""

import json
from collections import defaultdict
from pathlib import Path

from ..utils import c
from ..cli import _state_path, _write_query


# Detail keys to display, in order. Each entry is (key, label, formatter).
# Formatter is either None (use str(value)) or a callable(value) -> str.
_DETAIL_DISPLAY = [
    ("line", "line", None),
    ("lines", "lines", lambda v: ", ".join(str(l) for l in v[:5])),
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
    ("review", "review", lambda v: v[:80]),
    ("majority", "majority", None),
    ("minority", "minority", None),
    ("outliers", "outliers", lambda v: ", ".join(v[:5])),
]


def _format_detail(detail: dict) -> list[str]:
    """Build display parts from a finding's detail dict."""
    parts = []
    for key, label, fmt in _DETAIL_DISPLAY:
        val = detail.get(key)
        if val is None or val == 0:
            # Special case: importers=0 is meaningful (unlike count=0)
            if key == "importers" and val is not None:
                parts.append(f"{label}: {val}")
            continue
        parts.append(f"{label}: {fmt(val) if fmt else val}")

    # Special case: dupe pair display
    if detail.get("fn_a"):
        a, b = detail["fn_a"], detail["fn_b"]
        parts.append(f"{a['name']}:{a.get('line', '')} ↔ {b['name']}:{b.get('line', '')}")

    return parts


def cmd_show(args):
    """Show all findings for a file, directory, detector, or pattern."""
    from ..state import load_state, match_findings

    sp = _state_path(args)
    state = load_state(sp)

    if not state.get("last_scan"):
        print(c("No scans yet. Run: desloppify scan", "yellow"))
        return

    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(c(f"  {stale_warning}", "yellow"))

    chronic = getattr(args, "chronic", False)
    pattern = args.pattern

    if chronic:
        matches = [f for f in state["findings"].values()
                   if f.get("reopen_count", 0) >= 2 and f["status"] == "open"]
        status_filter = "open"
        pattern = pattern or "<chronic>"
    else:
        if not pattern:
            print(c("Pattern required (or use --chronic). Try: desloppify show --help", "yellow"))
            return
        status_filter = getattr(args, "status", "open")
        matches = match_findings(state, pattern, status_filter)

    if not matches:
        print(c(f"No {status_filter} findings matching: {pattern}", "yellow"))
        _write_query({"command": "show", "query": pattern, "status_filter": status_filter,
                      "total": 0, "findings": []})
        return

    # Always write structured query file
    payload = _build_show_payload(matches, pattern, status_filter)
    _write_query({"command": "show", **payload})

    # Optional: also write to a custom output file
    output_file = getattr(args, "output", None)
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(json.dumps(payload, indent=2) + "\n")
        print(c(f"Wrote {len(matches)} findings to {output_file}", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for f in matches:
        by_file[f["file"]].append(f)

    from ..plan import CONFIDENCE_ORDER
    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
    top = getattr(args, "top", 20) or 20

    print(c(f"\n  {len(matches)} {status_filter} findings matching '{pattern}'\n", "bold"))

    shown_files = sorted_files[:top]
    remaining_files = sorted_files[top:]
    remaining_findings = sum(len(fs) for _, fs in remaining_files)

    for filepath, findings in shown_files:
        findings.sort(key=lambda f: (f["tier"], CONFIDENCE_ORDER.get(f["confidence"], 9)))
        print(c(f"  {filepath}", "cyan") + c(f"  ({len(findings)} findings)", "dim"))

        for f in findings:
            status_icon = {"open": "○", "fixed": "✓", "wontfix": "—", "false_positive": "✗",
                          "auto_resolved": "◌"}.get(f["status"], "?")
            print(f"    {status_icon} T{f['tier']} [{f['confidence']}] {f['summary']}")

            detail_parts = _format_detail(f.get("detail", {}))
            if detail_parts:
                print(c(f"      {' · '.join(detail_parts)}", "dim"))
            if f.get("reopen_count", 0) >= 2:
                print(c(f"      ⟳ reopened {f['reopen_count']} times — fix properly or wontfix", "red"))
            if f.get("note"):
                print(c(f"      note: {f['note']}", "dim"))
            print(c(f"      {f['id']}", "dim"))
        print()

    if remaining_findings:
        print(c(f"  ... and {len(remaining_files)} more files ({remaining_findings} findings). Use --top {top + 20} to see more.\n", "dim"))

    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for f in matches:
        by_detector[f["detector"]] += 1
        by_tier[f["tier"]] += 1

    print(c("  Summary:", "bold"))
    print(c(f"    By tier:     {', '.join(f'T{t}:{n}' for t, n in sorted(by_tier.items()))}", "dim"))
    print(c(f"    By detector: {', '.join(f'{d}:{n}' for d, n in sorted(by_detector.items(), key=lambda x: -x[1]))}", "dim"))
    print()


def _build_show_payload(matches: list[dict], pattern: str, status_filter: str) -> dict:
    """Build the structured JSON payload shared by query file and --output."""
    by_file: dict[str, list] = defaultdict(list)
    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for f in matches:
        by_file[f["file"]].append(f)
        by_detector[f["detector"]] += 1
        by_tier[f["tier"]] += 1

    return {
        "query": pattern,
        "status_filter": status_filter,
        "total": len(matches),
        "summary": {
            "by_tier": {f"T{t}": n for t, n in sorted(by_tier.items())},
            "by_detector": dict(sorted(by_detector.items(), key=lambda x: -x[1])),
            "files": len(by_file),
        },
        "by_file": {
            fp: [{"id": f["id"], "tier": f["tier"], "confidence": f["confidence"],
                  "summary": f["summary"], "detail": f.get("detail", {})}
                 for f in fs]
            for fp, fs in sorted(by_file.items(), key=lambda x: -len(x[1]))
        },
    }
