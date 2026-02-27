"""CLI parser construction helpers."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version as get_version

from desloppify.app.cli_support.parser_groups import (
    _add_config_parser,
    _add_detect_parser,
    _add_dev_parser,
    _add_exclude_parser,
    _add_fix_parser,
    _add_ignore_parser,
    _add_langs_parser,
    _add_move_parser,
    _add_next_parser,
    _add_plan_parser,
    _add_review_parser,
    _add_scan_parser,
    _add_show_parser,
    _add_status_parser,
    _add_tree_parser,
    _add_update_skill_parser,
    _add_viz_parser,
    _add_zone_parser,
)

USAGE_EXAMPLES = """
core workflow:
  scan       Run detectors, update state, show diff
  status     Score dashboard with dimension health
  next       Show next highest-priority item to work on
  plan       Living plan: prioritize, cluster, skip, done, annotate

investigation:
  show       Dig into findings by file/dir/detector/ID
  tree       Annotated codebase tree (zoom with --focus)
  detect     Run a single detector directly (bypass state)

maintenance:
  fix        Auto-fix mechanical issues
  ignore     Suppress findings matching a pattern
  exclude    Exclude path pattern from scanning
  move       Move file/dir and update import references
  review     Holistic subjective review (LLM-based)

setup & admin:
  zone       Show/set zone classifications
  config     Project configuration
  viz        Interactive HTML treemap
  langs      List language plugins
  dev        Developer utilities
  update-skill  Install/update agent skill document

examples:
  desloppify scan
  desloppify scan --skip-slow --profile ci
  desloppify plan                        # full prioritized markdown
  desloppify plan queue                  # compact table of all items
  desloppify next --count 10             # top 10 queue items
  desloppify show src/components/Modal.tsx
  desloppify plan done "unused::src/foo.tsx::React" \\
    --note "removed import" --attest "I have actually ..."
  desloppify review --run-batches --parallel --scan-after-import
"""


class _NoAbbrevArgumentParser(argparse.ArgumentParser):
    """Argparse parser variant that disables long-option abbreviation."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)


def _cli_version_string() -> str:
    """Return the best available CLI version label."""
    try:
        return f"desloppify {get_version('desloppify')}"
    except PackageNotFoundError:
        return "desloppify (version unknown)"


def create_parser(*, langs: list[str], detector_names: list[str]) -> argparse.ArgumentParser:
    """Build top-level CLI parser with all subcommands."""
    lang_help = ", ".join(langs) if langs else "registered languages"

    parser = _NoAbbrevArgumentParser(
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
        help="Path pattern to exclude (component/prefix match; repeatable)",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=_cli_version_string(),
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_NoAbbrevArgumentParser,
    )
    _add_scan_parser(sub)
    _add_status_parser(sub)
    _add_tree_parser(sub)
    _add_show_parser(sub)
    _add_next_parser(sub)
    _add_ignore_parser(sub)
    _add_exclude_parser(sub)
    _add_fix_parser(sub, langs)
    _add_plan_parser(sub)
    _add_viz_parser(sub)
    _add_detect_parser(sub, detector_names)
    _add_move_parser(sub)
    _add_review_parser(sub)
    _add_zone_parser(sub)
    _add_config_parser(sub)
    _add_dev_parser(sub)
    _add_langs_parser(sub)
    _add_update_skill_parser(sub)
    return parser


__all__ = ["USAGE_EXAMPLES", "create_parser"]
