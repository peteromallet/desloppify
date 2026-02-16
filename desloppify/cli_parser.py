"""Parser construction helpers for the CLI entrypoint."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .cli_parser_extras import (
    USAGE_EXAMPLES,
    add_config_parser,
    add_detect_parser,
    add_dev_parser,
    add_help_parser,
    add_issues_parser,
    add_move_parser,
    add_review_parser,
    add_zone_parser,
)


def build_parser(*,
                 langs: Sequence[str],
                 detector_names: Sequence[str],
                 fixer_help_lines: Sequence[str]) -> argparse.ArgumentParser:
    """Build the top-level CLI parser with all subcommands."""
    lang_help = ", ".join(langs) if langs else "registered languages"
    parser = argparse.ArgumentParser(
        prog="desloppify",
        description="Desloppify — codebase health tracker",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help=f"Language to scan ({lang_help}). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="PATTERN",
        help="Path substring to exclude (repeatable: --exclude foo --exclude bar)",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    _add_scan_parser(sub)
    _add_status_parser(sub)
    _add_explain_parser(sub)
    _add_tree_parser(sub)
    _add_show_parser(sub)
    _add_next_parser(sub)
    _add_resolve_parser(sub)
    _add_fix_parser(sub, fixer_help_lines)
    _add_plan_parser(sub)
    _add_viz_parser(sub)
    add_detect_parser(sub, detector_names)
    add_move_parser(sub)
    add_review_parser(sub)
    add_issues_parser(sub)
    add_zone_parser(sub)
    add_config_parser(sub)
    add_dev_parser(sub)
    add_help_parser(sub)
    return parser


def _add_scan_parser(sub) -> None:
    parser = sub.add_parser("scan", help="Run all detectors, update state, show diff")
    parser.add_argument("--path", type=str, default=None, help="Path to scan (default: language source root)")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--skip-slow", action="store_true", help="Skip slow detectors (dupes)")
    parser.add_argument(
        "--profile",
        choices=["objective", "full", "ci"],
        default=None,
        help="Scan profile: objective, full, or ci",
    )
    parser.add_argument(
        "--force-resolve",
        action="store_true",
        help="Bypass suspect-detector protection (use when a detector legitimately went to 0)",
    )
    parser.add_argument(
        "--no-badge",
        action="store_true",
        help="Skip scorecard image generation (also: DESLOPPIFY_NO_BADGE=true)",
    )
    parser.add_argument(
        "--badge-path",
        type=str,
        default=None,
        metavar="PATH",
        help="Output path for scorecard image (default: scorecard.png)",
    )
    parser.add_argument(
        "--lang-opt",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Language runtime option override (repeatable, e.g. --lang-opt roslyn_cmd='dotnet run ...')",
    )


def _add_status_parser(sub) -> None:
    parser = sub.add_parser("status", help="Score dashboard with per-tier progress")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    parser.add_argument(
        "--include-suppressed",
        action="store_true",
        help="Show ignore-suppressed counts in status output",
    )


def _add_explain_parser(sub) -> None:
    parser = sub.add_parser(
        "explain",
        aliases=["help-me-improve"],
        help="Explain score-loss hotspots and fix priorities",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--top", type=int, default=12, help="Rows to show for hotspot/open summaries")
    parser.add_argument(
        "--subjective-threshold",
        type=float,
        default=89.0,
        help="Show subjective dimensions below this score (default: 89)",
    )
    parser.add_argument("--json", action="store_true", help="Output explanation as JSON")


def _add_tree_parser(sub) -> None:
    parser = sub.add_parser("tree", help="Annotated codebase tree (text)")
    parser.add_argument("--path", type=str, default=None, help="Path to analyze (default: language source root)")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--depth", type=int, default=2, help="Max depth (default: 2)")
    parser.add_argument(
        "--focus",
        type=str,
        default=None,
        help="Zoom into subdirectory (e.g. shared/components/MediaLightbox)",
    )
    parser.add_argument("--min-loc", type=int, default=0, help="Hide items below this LOC")
    parser.add_argument(
        "--sort",
        choices=["loc", "findings", "coupling"],
        default="loc",
        help="Sort directories by loc, findings, or coupling",
    )
    parser.add_argument("--detail", action="store_true", help="Show finding summaries per file")


def _add_show_parser(sub) -> None:
    parser = sub.add_parser("show", help="Dig into findings by file, directory, detector, or ID")
    parser.add_argument(
        "pattern",
        nargs="?",
        default=None,
        help="File path, directory, detector name, finding ID, or glob",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument(
        "--status",
        choices=["open", "fixed", "wontfix", "false_positive", "auto_resolved", "all"],
        default="open",
        help="Filter findings by status",
    )
    parser.add_argument("--top", type=int, default=20, help="Max files to show (default: 20)")
    parser.add_argument("--output", type=str, metavar="FILE", help="Write JSON to file instead of terminal")
    parser.add_argument(
        "--chronic",
        action="store_true",
        help="Show findings that have been reopened 2+ times (chronic reopeners)",
    )
    parser.add_argument("--code", action="store_true", help="Show inline code snippets for each finding")
    parser.add_argument(
        "--include-suppressed",
        action="store_true",
        help="Show suppression hints when ignored findings match your query",
    )


def _add_next_parser(sub) -> None:
    parser = sub.add_parser("next", help="Show next highest-priority open finding")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], default=None,
                        help="Restrict results to a single tier")
    parser.add_argument("--count", type=int, default=1, help="Number of items to show (default: 1)")
    parser.add_argument("--output", type=str, metavar="FILE", help="Write JSON to file instead of terminal")


def _add_resolve_parser(sub) -> None:
    parser = sub.add_parser("resolve", help="Resolve findings or suppress them via ignore")
    parser.add_argument("status", choices=["fixed", "wontfix", "false_positive", "ignore"],
                        help="Resolution status to apply")
    parser.add_argument(
        "patterns",
        nargs="+",
        metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )
    parser.add_argument(
        "--note",
        type=str,
        default=None,
        help="Explanation (required for wontfix and ignore)",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )


def _add_fix_parser(sub, fixer_help_lines: Sequence[str]) -> None:
    parser = sub.add_parser(
        "fix",
        help="Auto-fix mechanical issues",
        epilog="\n".join(fixer_help_lines),
    )
    parser.add_argument("fixer", type=str, help="What to fix")
    parser.add_argument("--path", type=str, default=None, help="Path to fix (default: language source root)")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")


def _add_plan_parser(sub) -> None:
    parser = sub.add_parser("plan", help="Generate prioritized markdown plan from state")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--output", type=str, metavar="FILE", help="Write to file instead of stdout")


def _add_viz_parser(sub) -> None:
    parser = sub.add_parser("viz", help="Generate interactive HTML treemap")
    parser.add_argument("--path", type=str, default=None, help="Path to analyze (default: language source root)")
    parser.add_argument("--output", type=str, default=None, help="HTML output path (default: treemap.html)")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
