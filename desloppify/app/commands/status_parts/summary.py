"""Summary-line rendering helpers for the status command."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.core.output_api import LOC_COMPACT_THRESHOLD, colorize


def score_summary_lines(
    *,
    overall_score: float | None,
    objective_score: float | None,
    strict_score: float | None,
    verified_strict_score: float | None,
    target_strict: float | None = None,
) -> list[tuple[str, str]]:
    """Return formatted top-line score summary rows."""
    if (
        overall_score is not None
        and objective_score is not None
        and strict_score is not None
        and verified_strict_score is not None
    ):
        lines: list[tuple[str, str]] = [
            (
                f"\n  Scores: overall {overall_score:.1f}/100 · "
                f"objective {objective_score:.1f}/100 · "
                f"strict {strict_score:.1f}/100 · "
                f"verified {verified_strict_score:.1f}/100",
                "bold",
            ),
            (
                "  Score guide: overall (lenient) · objective (mechanical only) · "
                "strict (penalizes wontfix) · verified (scan-confirmed only)",
                "dim",
            ),
        ]
        if target_strict is not None:
            gap = round(target_strict - strict_score, 1)
            if gap > 0:
                lines.append((
                    f"  Strict {strict_score:.1f} (target: {target_strict:.1f})"
                    " — run `desloppify next` to find the next improvement",
                    "dim",
                ))
            else:
                lines.append((
                    f"  Strict {strict_score:.1f} — target {target_strict:.1f} reached!",
                    "green",
                ))
        else:
            lines.append(("  Focus on strict — it's your north star.", "dim"))
        return lines
    return [
        ("\n  Scores unavailable", "bold"),
        ("  Run a full scan to compute overall/objective/strict scores.", "yellow"),
    ]


def print_scan_metrics(state: dict) -> None:
    """Print aggregate codebase metrics from the last scan."""
    metrics = state.get("codebase_metrics", {})
    total_files = sum(m.get("total_files", 0) for m in metrics.values())
    total_loc = sum(m.get("total_loc", 0) for m in metrics.values())
    total_dirs = sum(m.get("total_directories", 0) for m in metrics.values())
    if total_files:
        loc_str = f"{total_loc:,}" if total_loc < LOC_COMPACT_THRESHOLD else f"{total_loc // 1000}K"
        print(
            colorize(
                f"  {total_files} files · {loc_str} LOC · {total_dirs} dirs · "
                f"Last scan: {state.get('last_scan', 'never')}",
                "dim",
            )
        )
        return
    print(
        colorize(
            f"  Scans: {state.get('scan_count', 0)} | Last: {state.get('last_scan', 'never')}",
            "dim",
        )
    )


def print_scan_completeness(state: dict) -> None:
    """Warn when one or more language scans were partial."""
    completeness = state.get("scan_completeness", {})
    incomplete = [lang for lang, status in completeness.items() if status != "full"]
    if incomplete:
        print(
            colorize(
                f"  * Incomplete scan ({', '.join(incomplete)} — slow phases skipped)",
                "yellow",
            )
        )


def print_open_scope_breakdown(state: dict) -> None:
    """Print open counts with explicit in-scope/out-of-scope semantics."""
    findings = state.get("findings", {})
    if not isinstance(findings, dict):
        return

    counts = state_mod.open_scope_breakdown(findings, state.get("scan_path"))
    print(
        colorize(
            "  "
            f"open (in-scope): {counts['in_scope']} · "
            f"open (out-of-scope carried): {counts['out_of_scope']} · "
            f"open (global): {counts['global']}",
            "dim",
        )
    )


__all__ = [
    "print_open_scope_breakdown",
    "print_scan_completeness",
    "print_scan_metrics",
    "score_summary_lines",
]
