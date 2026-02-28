"""CLI parser subcommand group builders."""

from __future__ import annotations

import argparse

from desloppify.app.cli_support.parser_groups_admin import (  # noqa: F401 (re-exports)
    _add_config_parser,
    _add_detect_parser,
    _add_dev_parser,
    _add_fix_parser,
    _add_langs_parser,
    _add_move_parser,
    _add_plan_parser,
    _add_review_parser,
    _add_update_skill_parser,
    _add_viz_parser,
    _add_zone_parser,
)

__all__ = [
    "_add_config_parser",
    "_add_detect_parser",
    "_add_dev_parser",
    "_add_exclude_parser",
    "_add_fix_parser",
    "_add_ignore_parser",
    "_add_langs_parser",
    "_add_move_parser",
    "_add_next_parser",
    "_add_plan_parser",
    "_add_review_parser",
    "_add_scan_parser",
    "_add_show_parser",
    "_add_status_parser",
    "_add_tree_parser",
    "_add_update_skill_parser",
    "_add_viz_parser",
    "_add_zone_parser",
]


def _add_scan_parser(sub) -> None:
    p_scan = sub.add_parser(
        "scan",
        help="Run all detectors, update state, show diff",
        epilog="""\
examples:
  desloppify scan
  desloppify scan --skip-slow
  desloppify scan --profile ci
  desloppify scan --force-resolve""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_scan.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_scan.add_argument("--state", type=str, default=None, help="Path to state file")
    p_scan.add_argument(
        "--reset-subjective",
        action="store_true",
        help="Reset subjective measures to 0 before running scan",
    )
    p_scan.add_argument(
        "--skip-slow", action="store_true", help="Skip slow detectors (dupes)"
    )
    p_scan.add_argument(
        "--profile",
        choices=["objective", "full", "ci"],
        default=None,
        help="Scan profile: objective, full, or ci",
    )
    p_scan.add_argument(
        "--force-resolve",
        action="store_true",
        help="Bypass suspect-detector protection (use when a detector legitimately went to 0)",
    )
    p_scan.add_argument(
        "--no-badge",
        action="store_true",
        help="Skip scorecard image generation (also: DESLOPPIFY_NO_BADGE=true)",
    )
    p_scan.add_argument(
        "--badge-path",
        type=str,
        default=None,
        metavar="PATH",
        help="Output path for scorecard image (default: scorecard.png)",
    )
    p_scan.add_argument(
        "--lang-opt",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Language runtime option override (repeatable, e.g. --lang-opt roslyn_cmd='dotnet run ...')",
    )
    p_scan.add_argument(
        "--by-language",
        action="store_true",
        default=False,
        help=(
            "Generate per-language score sections and scorecard images "
            "(e.g. scorecard-go.png, scorecard-python.png). "
            "Requires >=2 detected languages."
        ),
    )


def _add_status_parser(sub) -> None:
    p_status = sub.add_parser("status", help="Score dashboard with per-tier progress")
    p_status.add_argument("--state", type=str, default=None, help="Path to state file")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")
    p_status.add_argument(
        "--by-language",
        action="store_true",
        default=False,
        help="Show per-language score breakdown (requires a prior --by-language scan).",
    )


def _add_tree_parser(sub) -> None:
    p_tree = sub.add_parser("tree", help="Annotated codebase tree (text)")
    p_tree.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_tree.add_argument("--state", type=str, default=None, help="Path to state file")
    p_tree.add_argument("--depth", type=int, default=2, help="Max depth (default: 2)")
    p_tree.add_argument(
        "--focus",
        type=str,
        default=None,
        help="Zoom into subdirectory (e.g. shared/components/MediaLightbox)",
    )
    p_tree.add_argument(
        "--min-loc", type=int, default=0, help="Hide items below this LOC"
    )
    p_tree.add_argument(
        "--sort", choices=["loc", "findings", "coupling"], default="loc",
        help="Sort order (default: loc)",
    )
    p_tree.add_argument(
        "--detail", action="store_true", help="Show finding summaries per file"
    )


def _add_show_parser(sub) -> None:
    p_show = sub.add_parser(
        "show",
        help="Dig into findings by file, directory, detector, or ID",
        epilog="""\
examples:
  desloppify show src/components/Modal.tsx
  desloppify show unused --top 50
  desloppify show --chronic
  desloppify show --status all""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_show.add_argument(
        "pattern",
        nargs="?",
        default=None,
        help="File path, directory, detector name, finding ID, or glob",
    )
    p_show.add_argument("--state", type=str, default=None, help="Path to state file")
    p_show.add_argument(
        "--status",
        choices=["open", "fixed", "wontfix", "false_positive", "auto_resolved", "all"],
        default="open",
        help="Filter by status (default: open)",
    )
    p_show.add_argument(
        "--top", type=int, default=20, help="Max files to show (default: 20)"
    )
    p_show.add_argument(
        "--output",
        type=str,
        metavar="FILE",
        help="Write JSON to file instead of terminal",
    )
    p_show.add_argument(
        "--chronic",
        action="store_true",
        help="Show findings that have been reopened 2+ times (chronic reopeners)",
    )
    p_show.add_argument(
        "--code", action="store_true", help="Show inline code snippets for each finding"
    )
    p_show.add_argument(
        "--notes",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to investigation notes file to attach to a finding",
    )


def _add_next_parser(sub) -> None:
    p_next = sub.add_parser(
        "next",
        help="Show next highest-priority open finding",
        epilog="""\
tiers (highest to lowest priority):
  T1  critical    security issues, data loss risks
  T2  important   bugs, correctness, major smells
  T3  moderate    code quality, duplication, dead code
  T4  cosmetic    style, subjective review dimensions

examples:
  desloppify next                       # single highest-priority item
  desloppify next --count 10            # top 10 items
  desloppify next --tier 1              # only tier 1
  desloppify next --group file          # group by file
  desloppify next --cluster my-cluster  # items in a cluster""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_next.add_argument("--state", type=str, default=None, help="Path to state file")
    p_next.add_argument("--tier", type=int, choices=[1, 2, 3, 4], default=None, help="Show only this tier")
    p_next.add_argument(
        "--count", type=int, default=1, help="Number of items to show (default: 1)"
    )
    p_next.add_argument(
        "--scope",
        type=str,
        default=None,
        help="Optional scope filter (path, detector, ID prefix, or glob)",
    )
    p_next.add_argument(
        "--status",
        choices=["open", "fixed", "wontfix", "false_positive", "auto_resolved", "all"],
        default="open",
        help="Status filter for queue items (default: open)",
    )
    p_next.add_argument(
        "--group",
        choices=["item", "file", "detector", "tier"],
        default="item",
        help="Group output by item, file, detector, or tier",
    )
    p_next.add_argument(
        "--format",
        choices=["terminal", "json", "md"],
        default="terminal",
        help="Output format (default: terminal)",
    )
    p_next.add_argument(
        "--explain",
        action="store_true",
        help="Show ranking and tier-fallback rationale",
    )
    p_next.add_argument(
        "--no-tier-fallback",
        action="store_true",
        help="Do not auto-fallback to another tier when --tier has no items",
    )
    p_next.add_argument(
        "--cluster",
        type=str,
        default=None,
        metavar="NAME",
        help="Filter to a specific plan cluster",
    )
    p_next.add_argument(
        "--include-skipped",
        action="store_true",
        help="Include skipped items in the queue",
    )
    p_next.add_argument(
        "--output",
        type=str,
        metavar="FILE",
        help="Write JSON/Markdown to file (with --format json|md)",
    )


def _add_ignore_parser(sub) -> None:
    p_ignore = sub.add_parser(
        "ignore", help="Add pattern to ignore list, remove matching findings"
    )
    p_ignore.add_argument("pattern", help="File path, glob, or detector::prefix")
    p_ignore.add_argument(
        "--attest",
        type=str,
        default=None,
        help=(
            "Required anti-gaming attestation. Must include BOTH keywords "
            "'I have actually' and 'not gaming'. Example: "
            '--attest "I have actually [DESCRIBE THE CONCRETE CHANGE YOU MADE] and I am not gaming the score by resolving without fixing."'
        ),
    )
    p_ignore.add_argument("--state", type=str, default=None, help="Path to state file")


def _add_exclude_parser(sub) -> None:
    p_exclude = sub.add_parser(
        "exclude", help="Add path pattern to exclude list"
    )
    p_exclude.add_argument("pattern", help="Path pattern to exclude from scanning")
