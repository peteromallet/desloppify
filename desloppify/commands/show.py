"""show command: dig into findings by file, directory, detector, or pattern."""

import json
from collections import defaultdict

from ..utils import colorize
from ._helpers import state_path, _write_query


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
    ("related_files", "related files", lambda v: ", ".join(v[:5]) + (f" +{len(v)-5}" if len(v) > 5 else "")),
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

    sp = state_path(args)
    state = load_state(sp)

    if not state.get("last_scan"):
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
        return

    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    chronic = getattr(args, "chronic", False)
    show_code = getattr(args, "code", False)
    pattern = args.pattern

    if chronic:
        from ..state import path_scoped_findings
        scoped = path_scoped_findings(state["findings"], state.get("scan_path"))
        matches = [f for f in scoped.values()
                   if f.get("reopen_count", 0) >= 2 and f["status"] == "open"]
        status_filter = "open"
        pattern = pattern or "<chronic>"
    else:
        if not pattern:
            print(colorize("Pattern required (or use --chronic). Try: desloppify show --help", "yellow"))
            return
        status_filter = getattr(args, "status", "open")
        matches = match_findings(state, pattern, status_filter)
        # Filter to scan path scope
        from ..state import path_scoped_findings
        scoped_ids = set(path_scoped_findings(state["findings"], state.get("scan_path")).keys())
        matches = [f for f in matches if f["id"] in scoped_ids]

    if not matches:
        print(colorize(f"No {status_filter} findings matching: {pattern}", "yellow"))
        _write_query({"command": "show", "query": pattern, "status_filter": status_filter,
                      "total": 0, "findings": []})
        return

    # Always write structured query file
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, lang=lang_name, command="show")
    payload = _build_show_payload(matches, pattern, status_filter)
    _write_query({"command": "show", **payload, "narrative": narrative})

    # Optional: also write to a custom output file
    output_file = getattr(args, "output", None)
    if output_file:
        try:
            from ..utils import safe_write_text
            safe_write_text(output_file, json.dumps(payload, indent=2) + "\n")
            print(colorize(f"Wrote {len(matches)} findings to {output_file}", "green"))
        except OSError as e:
            print(colorize(f"Could not write to {output_file}: {e}", "red"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for f in matches:
        by_file[f["file"]].append(f)

    from ..plan import CONFIDENCE_ORDER
    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
    top = getattr(args, "top", 20) or 20

    print(colorize(f"\n  {len(matches)} {status_filter} findings matching '{pattern}'\n", "bold"))

    shown_files = sorted_files[:top]
    remaining_files = sorted_files[top:]
    remaining_findings = sum(len(fs) for _, fs in remaining_files)

    for filepath, findings in shown_files:
        findings.sort(key=lambda f: (f["tier"], CONFIDENCE_ORDER.get(f["confidence"], 9)))
        display_path = "Codebase-wide" if filepath == "." else filepath
        print(colorize(f"  {display_path}", "cyan") + colorize(f"  ({len(findings)} findings)", "dim"))

        for f in findings:
            status_icon = {"open": "○", "fixed": "✓", "wontfix": "—", "false_positive": "✗",
                          "auto_resolved": "◌"}.get(f["status"], "?")
            zone_tag = ""
            zone = f.get("zone", "production")
            if zone != "production":
                zone_tag = colorize(f" [{zone}]", "dim")
            print(f"    {status_icon} T{f['tier']} [{f['confidence']}] {f['summary']}{zone_tag}")

            detail_parts = _format_detail(f.get("detail", {}))
            if detail_parts:
                print(colorize(f"      {' · '.join(detail_parts)}", "dim"))
            if show_code:
                detail = f.get("detail", {})
                target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
                if target_line and f["file"] not in (".", ""):
                    from ..utils import read_code_snippet
                    snippet = read_code_snippet(f["file"], target_line)
                    if snippet:
                        print(snippet)
            if f.get("reopen_count", 0) >= 2:
                print(colorize(f"      ⟳ reopened {f['reopen_count']} times — fix properly or wontfix", "red"))
            if f.get("note"):
                print(colorize(f"      note: {f['note']}", "dim"))
            print(colorize(f"      {f['id']}", "dim"))
        print()

    if remaining_findings:
        print(colorize(f"  ... and {len(remaining_files)} more files ({remaining_findings} findings). Use --top {top + 20} to see more.\n", "dim"))

    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for f in matches:
        by_detector[f["detector"]] += 1
        by_tier[f["tier"]] += 1

    print(colorize("  Summary:", "bold"))
    print(colorize(f"    By tier:     {', '.join(f'T{t}:{n}' for t, n in sorted(by_tier.items()))}", "dim"))
    print(colorize(f"    By detector: {', '.join(f'{d}:{n}' for d, n in sorted(by_detector.items(), key=lambda x: -x[1]))}", "dim"))
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
