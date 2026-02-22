"""Terminal rendering helpers for `desloppify show`."""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

from desloppify.engine.planning import CONFIDENCE_ORDER
from desloppify.file_discovery import rel
from desloppify.utils import colorize, read_code_snippet


def _print_pattern_evidence(pattern_evidence: dict) -> None:
    for pattern_name, matches in sorted(pattern_evidence.items()):
        if not matches:
            continue
        file_items: list[str] = []
        for match in matches[:5]:
            file_part = match.get("file", "")
            line_part = match.get("line")
            if file_part and isinstance(line_part, int):
                file_items.append(f"{file_part}:{line_part}")
            elif file_part:
                file_items.append(file_part)
        if file_items:
            suffix = f" +{len(matches) - 5}" if len(matches) > 5 else ""
            print(colorize(f"      evidence {pattern_name}: {', '.join(file_items)}{suffix}", "dim"))


def _print_code_snippets(finding: dict, show_code: bool) -> None:
    if not show_code:
        return

    detail = finding.get("detail", {})
    target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
    if target_line and finding["file"] not in (".", ""):
        snippet = read_code_snippet(finding["file"], target_line)
        if snippet:
            print(snippet)
        return

    pattern_evidence = detail.get("pattern_evidence")
    if not isinstance(pattern_evidence, dict):
        return
    shown = 0
    for _pattern_name, matches in sorted(pattern_evidence.items()):
        for match in matches:
            file_part = match.get("file")
            line_part = match.get("line")
            if not file_part or not isinstance(line_part, int):
                continue
            snippet = read_code_snippet(file_part, line_part)
            if snippet:
                print(snippet)
                shown += 1
            if shown >= 3:
                return


def _print_single_finding(finding: dict, *, show_code: bool, format_detail) -> None:
    status_icon = {
        "open": "○",
        "fixed": "✓",
        "wontfix": "—",
        "false_positive": "✗",
        "auto_resolved": "◌",
    }.get(finding["status"], "?")
    zone = finding.get("zone", "production")
    zone_tag = colorize(f" [{zone}]", "dim") if zone != "production" else ""
    print(f"    {status_icon} T{finding['tier']} [{finding['confidence']}] {finding['summary']}{zone_tag}")

    detail = finding.get("detail", {})
    detail_parts = format_detail(detail)
    if detail_parts:
        print(colorize(f"      {' · '.join(detail_parts)}", "dim"))

    pattern_evidence = detail.get("pattern_evidence")
    if isinstance(pattern_evidence, dict) and pattern_evidence:
        _print_pattern_evidence(pattern_evidence)
    _print_code_snippets(finding, show_code=show_code)

    if finding.get("reopen_count", 0) >= 2:
        print(colorize(f"      ⟳ reopened {finding['reopen_count']} times — fix properly or wontfix", "red"))
    if finding.get("note"):
        print(colorize(f"      note: {finding['note']}", "dim"))
    print(colorize(f"      {finding['id']}", "dim"))


def render_show_results(
    matches: list[dict],
    *,
    pattern: str,
    status_filter: str,
    top: int,
    show_code: bool,
    noise_budget: int,
    global_noise_budget: int,
    budget_warning: str | None,
    hidden_by_detector: dict[str, int],
    format_detail,
) -> None:
    """Render grouped findings to terminal for the show command."""
    by_file: dict[str, list] = defaultdict(list)
    for finding in matches:
        by_file[finding["file"]].append(finding)

    sorted_files = sorted(by_file.items(), key=lambda item: -len(item[1]))

    hidden_total = sum(hidden_by_detector.values())
    print(colorize(f"\n  {len(matches)} {status_filter} findings matching '{pattern}'\n", "bold"))
    if budget_warning:
        print(colorize(f"  {budget_warning}\n", "yellow"))
    if hidden_total:
        global_label = f", {global_noise_budget} global" if global_noise_budget > 0 else ""
        hidden_parts = ", ".join(f"{detector}: +{count}" for detector, count in hidden_by_detector.items())
        print(
            colorize(
                f"  Noise budget: {noise_budget}/detector{global_label} "
                f"({hidden_total} hidden: {hidden_parts})\n",
                "dim",
            )
        )

    shown_files = sorted_files[:top]
    remaining_files = sorted_files[top:]
    remaining_findings = sum(len(file_findings) for _, file_findings in remaining_files)

    for filepath, findings in shown_files:
        findings.sort(key=lambda f: (f["tier"], CONFIDENCE_ORDER.get(f["confidence"], 9)))
        display_path = "Codebase-wide" if filepath == "." else filepath
        print(colorize(f"  {display_path}", "cyan") + colorize(f"  ({len(findings)} findings)", "dim"))
        for finding in findings:
            _print_single_finding(finding, show_code=show_code, format_detail=format_detail)
        print()

    if remaining_findings:
        print(
            colorize(
                f"  ... and {len(remaining_files)} more files ({remaining_findings} findings). "
                f"Use --top {top + 20} to see more.\n",
                "dim",
            )
        )

    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for finding in matches:
        by_detector[finding["detector"]] += 1
        by_tier[finding["tier"]] += 1

    print(colorize("  Summary:", "bold"))
    tier_summary = ", ".join(f"T{tier}:{count}" for tier, count in sorted(by_tier.items()))
    detector_summary = ", ".join(
        f"{detector}:{count}" for detector, count in sorted(by_detector.items(), key=lambda item: -item[1])
    )
    print(colorize(f"    By tier:     {tier_summary}", "dim"))
    print(colorize(f"    By detector: {detector_summary}", "dim"))
    if hidden_total:
        hidden_summary = ", ".join(f"{detector}:+{count}" for detector, count in hidden_by_detector.items())
        print(colorize(f"    Hidden:      {hidden_summary}", "dim"))
    print()


def show_fix_dry_run_samples(entries: list[dict], results: list[dict]) -> None:
    """Print sampled before/after context for fix --dry-run."""
    random.seed(42)
    print(colorize("\n  ── Sample changes (before → after) ──", "cyan"))
    for result in random.sample(results, min(5, len(results))):
        _print_fix_file_sample(result, entries)
    removed_count = sum(len(r["removed"]) for r in results)
    if len(entries) > removed_count:
        print(colorize(f"\n  Note: {len(entries) - removed_count} of {len(entries)} entries were skipped (complex patterns, rest elements, etc.)", "dim"))
    print()


def _print_fix_file_sample(result: dict, entries: list[dict]) -> None:
    filepath, removed_set = result["file"], set(result["removed"])
    try:
        path = Path(filepath) if Path(filepath).is_absolute() else Path(".") / filepath
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return

    file_entries = [entry for entry in entries if entry["file"] == filepath and entry.get("name", "") in removed_set]
    shown = 0
    for entry in file_entries[:2]:
        line_idx = entry.get("line", entry.get("detail", {}).get("line", 0)) - 1
        if line_idx < 0 or line_idx >= len(lines):
            continue
        if shown == 0:
            print(colorize(f"\n  {rel(filepath)}:", "cyan"))
        name = entry.get("name", entry.get("summary", "?"))
        ctx_s, ctx_e = max(0, line_idx - 1), min(len(lines), line_idx + 2)
        print(colorize(f"    {name} (line {line_idx + 1}):", "dim"))
        for idx in range(ctx_s, ctx_e):
            marker = colorize("  →", "red") if idx == line_idx else "   "
            print(f"    {marker} {idx+1:4d}  {lines[idx][:90]}")
        shown += 1
