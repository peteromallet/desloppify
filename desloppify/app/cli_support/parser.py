"""CLI parser construction helpers."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version as get_version

from desloppify.app.cli_support.parser_groups import (
    _add_config_parser,
    _add_detect_parser,
    _add_dev_parser,
    _add_fix_parser,
    _add_ignore_parser,
    _add_issues_parser,
    _add_langs_parser,
    _add_move_parser,
    _add_next_parser,
    _add_plan_parser,
    _add_resolve_parser,
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
workflow:
  scan                          Run all detectors, update state, show diff
  status                        Score dashboard with per-tier progress
  tree                          Annotated codebase tree (zoom with --focus)
  show <pattern>                Dig into findings by file/dir/detector/ID
  resolve <pattern> <status>    Mark findings as open/fixed/wontfix/false_positive
  ignore <pattern>              Suppress findings matching a pattern
  zone show                     Show zone classifications for all files
  zone set <file> <zone>        Override zone for a file
  review --prepare              Prepare holistic codebase review data
  review --import FILE          Import review findings from JSON
  review --validate-import FILE Validate import payload/trust mode without mutating state
  review --external-start       Start external blind review session (Claude cloud)
  review --external-submit      Submit external session results with canonical provenance
  issues                        Review findings work queue
  plan                          Generate prioritized markdown plan

examples:
  desloppify scan --skip-slow
  desloppify --lang python scan --path scripts/desloppify
  desloppify tree --focus shared/components --sort findings --depth 3
  desloppify tree --detail --focus shared/components/MediaLightbox --min-loc 300
  desloppify show src/shared/components/PromptEditorModal.tsx
  desloppify show gods
  desloppify show "src/shared/components/MediaLightbox"
  desloppify resolve fixed "unused::src/foo.tsx::React" --note "removed unused React import" --attest "I have actually removed the unused React import from foo.tsx and I am not gaming the score by resolving without fixing."
  desloppify resolve fixed "logs::src/foo.tsx::*" --note "removed debug logs" --attest "I have actually removed all console.log calls from foo.tsx and I am not gaming the score by resolving without fixing."
  desloppify resolve wontfix deprecated --note "migration in progress" --attest "I have actually verified these are tracked in the migration plan and I am not gaming the score by resolving without fixing."
  desloppify ignore "smells::*::async_no_await" --attest "I have actually verified these are intentional fire-and-forget patterns and I am not gaming the score by resolving without fixing."
  desloppify detect logs --top 10
  desloppify detect dupes --threshold 0.9
  desloppify review --validate-import findings.json --attested-external --attest "I validated this review was completed without awareness of overall score and is unbiased."
  desloppify review --external-start --external-runner claude
  desloppify review --external-submit --session-id <session_id> --import findings.json
  desloppify review --run-batches --runner codex --parallel --scan-after-import --retrospective
  desloppify dev scaffold-lang go --extension .go --marker go.mod --default-src .
  desloppify move src/shared/hooks/useFoo.ts src/shared/hooks/video/useFoo.ts --dry-run
  desloppify move scripts/foo/bar.py scripts/foo/baz/bar.py
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
    _add_resolve_parser(sub)
    _add_ignore_parser(sub)
    _add_fix_parser(sub, langs)
    _add_plan_parser(sub)
    _add_viz_parser(sub)
    _add_detect_parser(sub, detector_names)
    _add_move_parser(sub)
    _add_review_parser(sub)
    _add_issues_parser(sub)
    _add_zone_parser(sub)
    _add_config_parser(sub)
    _add_dev_parser(sub)
    _add_langs_parser(sub)
    _add_update_skill_parser(sub)
    return parser


__all__ = ["USAGE_EXAMPLES", "create_parser"]
