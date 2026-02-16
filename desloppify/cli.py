"""CLI entry point: argparse, subcommand routing, shared helpers."""

import argparse
import sys

from .commands._helpers import state_path, resolve_lang
from .lang import available_langs, get_lang
from .utils import DEFAULT_PATH, PROJECT_ROOT


from .registry import detector_names as _detector_names

DETECTOR_NAMES = _detector_names()

USAGE_EXAMPLES = """
workflow:
  scan                          Run all detectors, update state, show diff
  status                        Score dashboard with per-tier progress
  tree                          Annotated codebase tree (zoom with --focus)
  show <pattern>                Dig into findings by file/dir/detector/ID
  resolve <pattern> <status>    Mark findings as fixed/wontfix/false_positive
  ignore <pattern>              Suppress findings matching a pattern
  zone show                     Show zone classifications for all files
  zone set <file> <zone>        Override zone for a file
  review --prepare              Prepare files for AI design review
  review --import FILE          Import review findings from JSON
  issues                        Review findings work queue
  plan                          Generate prioritized markdown plan

examples:
  desloppify scan --skip-slow
  desloppify scan --lang python --path scripts/desloppify
  desloppify tree --focus shared/components --sort findings --depth 3
  desloppify tree --detail --focus shared/components/MediaLightbox --min-loc 300
  desloppify show src/shared/components/PromptEditorModal.tsx
  desloppify show gods
  desloppify show "src/shared/components/MediaLightbox"
  desloppify resolve fixed "unused::src/foo.tsx::React" "unused::src/bar.tsx::React"
  desloppify resolve fixed "logs::src/foo.tsx::*" --note "removed debug logs"
  desloppify resolve wontfix deprecated --note "migration in progress"
  desloppify ignore "smells::*::async_no_await"
  desloppify detect logs --top 10
  desloppify detect dupes --threshold 0.9
  desloppify dev scaffold-lang go --extension .go --marker go.mod --default-src .
  desloppify move src/shared/hooks/useFoo.ts src/shared/hooks/video/useFoo.ts --dry-run
  desloppify move scripts/foo/bar.py scripts/foo/baz/bar.py
"""


def create_parser() -> argparse.ArgumentParser:
    langs = available_langs()
    lang_help = ", ".join(langs) if langs else "registered languages"

    parser = argparse.ArgumentParser(
        prog="desloppify",
        description="Desloppify — codebase health tracker",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Global flags
    parser.add_argument("--lang", type=str, default=None,
                        help=f"Language to scan ({lang_help}). Auto-detected if omitted.")
    parser.add_argument("--exclude", action="append", default=None, metavar="PATTERN",
                        help="Path substring to exclude (repeatable: --exclude foo --exclude bar)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Run all detectors, update state, show diff")
    p_scan.add_argument("--path", type=str, default=None)
    p_scan.add_argument("--state", type=str, default=None)
    p_scan.add_argument("--skip-slow", action="store_true", help="Skip slow detectors (dupes)")
    p_scan.add_argument("--force-resolve", action="store_true",
                        help="Bypass suspect-detector protection (use when a detector legitimately went to 0)")
    p_scan.add_argument("--no-badge", action="store_true",
                        help="Skip scorecard image generation (also: DESLOPPIFY_NO_BADGE=true)")
    p_scan.add_argument("--badge-path", type=str, default=None, metavar="PATH",
                        help="Output path for scorecard image (default: scorecard.png)")

    p_status = sub.add_parser("status", help="Score dashboard with per-tier progress")
    p_status.add_argument("--state", type=str, default=None)
    p_status.add_argument("--json", action="store_true")

    p_tree = sub.add_parser("tree", help="Annotated codebase tree (text)")
    p_tree.add_argument("--path", type=str, default=None)
    p_tree.add_argument("--state", type=str, default=None)
    p_tree.add_argument("--depth", type=int, default=2, help="Max depth (default: 2)")
    p_tree.add_argument("--focus", type=str, default=None,
                        help="Zoom into subdirectory (e.g. shared/components/MediaLightbox)")
    p_tree.add_argument("--min-loc", type=int, default=0, help="Hide items below this LOC")
    p_tree.add_argument("--sort", choices=["loc", "findings", "coupling"], default="loc")
    p_tree.add_argument("--detail", action="store_true", help="Show finding summaries per file")

    p_show = sub.add_parser("show", help="Dig into findings by file, directory, detector, or ID")
    p_show.add_argument("pattern", nargs="?", default=None,
                        help="File path, directory, detector name, finding ID, or glob")
    p_show.add_argument("--state", type=str, default=None)
    p_show.add_argument("--status", choices=["open", "fixed", "wontfix", "false_positive",
                                              "auto_resolved", "all"], default="open")
    p_show.add_argument("--top", type=int, default=20, help="Max files to show (default: 20)")
    p_show.add_argument("--output", type=str, metavar="FILE", help="Write JSON to file instead of terminal")
    p_show.add_argument("--chronic", action="store_true",
                        help="Show findings that have been reopened 2+ times (chronic reopeners)")
    p_show.add_argument("--code", action="store_true",
                        help="Show inline code snippets for each finding")

    p_next = sub.add_parser("next", help="Show next highest-priority open finding")
    p_next.add_argument("--state", type=str, default=None)
    p_next.add_argument("--tier", type=int, choices=[1, 2, 3, 4], default=None)
    p_next.add_argument("--count", type=int, default=1, help="Number of items to show (default: 1)")
    p_next.add_argument("--output", type=str, metavar="FILE", help="Write JSON to file instead of terminal")

    p_resolve = sub.add_parser("resolve", help="Mark finding(s) as fixed/wontfix/false_positive")
    p_resolve.add_argument("status", choices=["fixed", "wontfix", "false_positive"])
    p_resolve.add_argument("patterns", nargs="+", metavar="PATTERN",
                           help="Finding ID(s), prefix, detector name, file path, or glob")
    p_resolve.add_argument("--note", type=str, default=None, help="Explanation (required for wontfix)")
    p_resolve.add_argument("--state", type=str, default=None)

    p_ignore = sub.add_parser("ignore", help="Add pattern to ignore list, remove matching findings")
    p_ignore.add_argument("pattern", help="File path, glob, or detector::prefix")
    p_ignore.add_argument("--state", type=str, default=None)

    fixer_help_lines: list[str] = []
    for lang_name in langs:
        try:
            fixer_names = sorted(get_lang(lang_name).fixers.keys())
        except Exception:
            fixer_names = []
        fixer_list = ", ".join(fixer_names) if fixer_names else "none yet"
        fixer_help_lines.append(f"fixers ({lang_name}): {fixer_list}")
    fixer_help_lines.append("special: review — prepare structured review data")
    p_fix = sub.add_parser(
        "fix",
        help="Auto-fix mechanical issues",
        epilog="\n".join(fixer_help_lines),
    )
    p_fix.add_argument("fixer", type=str, help="What to fix")
    p_fix.add_argument("--path", type=str, default=None)
    p_fix.add_argument("--state", type=str, default=None)
    p_fix.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")

    p_plan = sub.add_parser("plan", help="Generate prioritized markdown plan from state")
    p_plan.add_argument("--state", type=str, default=None)
    p_plan.add_argument("--output", type=str, metavar="FILE", help="Write to file instead of stdout")

    p_viz = sub.add_parser("viz", help="Generate interactive HTML treemap")
    p_viz.add_argument("--path", type=str, default=None)
    p_viz.add_argument("--output", type=str, default=None)
    p_viz.add_argument("--state", type=str, default=None)

    p_detect = sub.add_parser("detect",
        help="Run a single detector directly (bypass state)",
        epilog=f"detectors: {', '.join(DETECTOR_NAMES)}")
    p_detect.add_argument("detector", type=str, help="Detector to run")
    p_detect.add_argument("--top", type=int, default=20)
    p_detect.add_argument("--path", type=str, default=None)
    p_detect.add_argument("--json", action="store_true")
    p_detect.add_argument("--fix", action="store_true", help="Auto-fix detected issues (logs detector only)")
    p_detect.add_argument("--category", choices=["imports", "vars", "params", "all"], default="all",
                          help="Filter unused by category")
    p_detect.add_argument("--threshold", type=float, default=None,
                          help="LOC threshold (large) or similarity (dupes)")
    p_detect.add_argument("--file", type=str, default=None, help="Show deps for specific file")

    p_move = sub.add_parser("move", help="Move a file or directory and update all import references")
    p_move.add_argument("source", type=str, help="File or directory to move (relative to project root)")
    p_move.add_argument("dest", type=str, help="Destination path (file or directory)")
    p_move.add_argument("--dry-run", action="store_true", help="Show changes without modifying files")

    p_review = sub.add_parser("review", help="Prepare or import subjective code review")
    p_review.add_argument("--path", type=str, default=None)
    p_review.add_argument("--state", type=str, default=None)
    p_review.add_argument("--prepare", action="store_true",
                          help="Prepare review data (output to query.json)")
    p_review.add_argument("--import", dest="import_file", type=str, metavar="FILE",
                          help="Import review findings from JSON file")
    p_review.add_argument("--max-age", type=int, default=None,
                          help="Staleness threshold in days (default: from config, or 30)")
    p_review.add_argument("--max-files", type=int, default=50,
                          help="Maximum files to evaluate (default: 50)")
    p_review.add_argument("--refresh", action="store_true",
                          help="Force re-evaluate everything (ignore cache)")
    p_review.add_argument("--dimensions", type=str, default=None,
                          help="Comma-separated dimensions to evaluate")
    p_review.add_argument("--holistic", action="store_true",
                          help="Prepare/import holistic codebase-wide review")

    p_issues = sub.add_parser("issues", help="Review findings work queue")
    p_issues.add_argument("--state", type=str, default=None)
    issues_sub = p_issues.add_subparsers(dest="issues_action")
    iss_show = issues_sub.add_parser("show", help="Show issue details")
    iss_show.add_argument("number", type=int)
    iss_update = issues_sub.add_parser("update", help="Add investigation to an issue")
    iss_update.add_argument("number", type=int)
    iss_update.add_argument("--file", type=str, required=True)

    p_zone = sub.add_parser("zone", help="Show/set/clear zone classifications")
    p_zone.add_argument("--path", type=str, default=None)
    p_zone.add_argument("--state", type=str, default=None)
    zone_sub = p_zone.add_subparsers(dest="zone_action")
    zone_sub.add_parser("show", help="Show zone classifications for all files")
    z_set = zone_sub.add_parser("set", help="Override zone for a file")
    z_set.add_argument("zone_path", type=str, help="Relative file path")
    z_set.add_argument("zone_value", type=str, help="Zone (production, test, config, generated, script, vendor)")
    z_clear = zone_sub.add_parser("clear", help="Remove zone override for a file")
    z_clear.add_argument("zone_path", type=str, help="Relative file path")

    p_config = sub.add_parser("config", help="Show/set/unset project configuration")
    config_sub = p_config.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Show all config values")
    c_set = config_sub.add_parser("set", help="Set a config value")
    c_set.add_argument("config_key", type=str, help="Config key name")
    c_set.add_argument("config_value", type=str, help="Value to set")
    c_unset = config_sub.add_parser("unset", help="Reset a config key to default")
    c_unset.add_argument("config_key", type=str, help="Config key name")

    p_dev = sub.add_parser("dev", help="Developer utilities")
    dev_sub = p_dev.add_subparsers(dest="dev_action", required=True)
    d_scaffold = dev_sub.add_parser("scaffold-lang", help="Generate a standardized language plugin scaffold")
    d_scaffold.add_argument("name", type=str, help="Language name (snake_case)")
    d_scaffold.add_argument(
        "--extension",
        action="append",
        default=None,
        metavar="EXT",
        help="Source file extension (repeatable, e.g. --extension .go --extension .gomod)",
    )
    d_scaffold.add_argument(
        "--marker",
        action="append",
        default=None,
        metavar="FILE",
        help="Project-root detection marker file (repeatable)",
    )
    d_scaffold.add_argument(
        "--default-src",
        type=str,
        default="src",
        metavar="DIR",
        help="Default source directory for scans (default: src)",
    )
    d_scaffold.add_argument("--force", action="store_true", help="Overwrite existing scaffold files")
    d_scaffold.add_argument(
        "--no-wire-pyproject",
        dest="wire_pyproject",
        action="store_false",
        help="Do not edit pyproject.toml testpaths/exclude arrays",
    )
    d_scaffold.set_defaults(wire_pyproject=True)

    return parser


def _apply_persisted_exclusions(args, config: dict):
    """Merge CLI --exclude with persisted config.exclude, set on utils global."""
    from .utils import set_exclusions, colorize

    cli_exclusions = getattr(args, "exclude", None) or []
    persisted = config.get("exclude", [])
    combined = list(cli_exclusions) + [e for e in persisted if e not in cli_exclusions]
    if combined:
        set_exclusions(combined)
        import sys
        if cli_exclusions:
            print(colorize(f"  Excluding: {', '.join(combined)}", "dim"), file=sys.stderr)
        else:
            print(colorize(f"  Excluding (from config): {', '.join(combined)}", "dim"), file=sys.stderr)


def main() -> None:
    # Ensure Unicode output works on Windows terminals (cp1252 etc.)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass

    parser = create_parser()
    args = parser.parse_args()

    # Resolve default path from language config if not explicitly provided
    if getattr(args, "path", None) is None:
        lang = resolve_lang(args)
        if lang:
            args.path = str(PROJECT_ROOT / lang.default_src)
        else:
            args.path = str(DEFAULT_PATH)

    # Load config and state, apply exclusions before any command runs
    from .config import load_config
    config = load_config()
    args._config = config

    sp = state_path(args)
    from .state import load_state
    state = load_state(sp)
    _apply_persisted_exclusions(args, config)
    args._preloaded_state = state
    args._state_path = sp

    # Lazy-load command handlers — only import the one needed
    _COMMAND_MAP = {
        "scan": (".commands.scan", "cmd_scan"),
        "status": (".commands.status", "cmd_status"),
        "show": (".commands.show", "cmd_show"),
        "next": (".commands.next", "cmd_next"),
        "resolve": (".commands.resolve", "cmd_resolve"),
        "ignore": (".commands.resolve", "cmd_ignore_pattern"),
        "fix": (".commands.fix_cmd", "cmd_fix"),
        "plan": (".commands.plan_cmd", "cmd_plan_output"),
        "detect": (".commands.detect", "cmd_detect"),
        "tree": (".output.visualize", "cmd_tree"),
        "viz": (".output.visualize", "cmd_viz"),
        "move": (".commands.move", "cmd_move"),
        "zone": (".commands.zone_cmd", "cmd_zone"),
        "review": (".commands.review_cmd", "cmd_review"),
        "issues": (".commands.issues_cmd", "cmd_issues"),
        "config": (".commands.config_cmd", "cmd_config"),
        "dev": (".commands.dev_cmd", "cmd_dev"),
    }

    module_path, func_name = _COMMAND_MAP[args.command]
    import importlib
    mod = importlib.import_module(module_path, package="desloppify")
    handler = getattr(mod, func_name)

    try:
        handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
