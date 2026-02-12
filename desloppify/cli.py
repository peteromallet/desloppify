"""CLI entry point: argparse, subcommand routing, shared helpers."""

import argparse
import json
import sys
from pathlib import Path

from .utils import DEFAULT_PATH, PROJECT_ROOT


QUERY_FILE = Path(".desloppify/query.json")


def _write_query(data: dict):
    """Write structured query output to .desloppify/query.json.

    Every query command calls this so the LLM can always Read the file
    instead of parsing terminal output.
    """
    QUERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUERY_FILE.write_text(json.dumps(data, indent=2, default=str) + "\n")


def _state_path(args) -> Path | None:
    """Get state file path from args, or None for default."""
    p = getattr(args, "state", None)
    if p:
        return Path(p)
    # Per-language state files when --lang is explicit
    lang_name = getattr(args, "lang", None)
    if lang_name:
        return PROJECT_ROOT / ".desloppify" / f"state-{lang_name}.json"
    return None


def _resolve_lang(args):
    """Resolve the language config from args, with auto-detection fallback."""
    lang_name = getattr(args, "lang", None)
    if lang_name is None:
        from .lang import auto_detect_lang
        from .utils import PROJECT_ROOT
        lang_name = auto_detect_lang(PROJECT_ROOT)
    if lang_name is None:
        return None
    from .lang import get_lang
    return get_lang(lang_name)


DETECTOR_NAMES = [
    "logs", "unused", "exports", "deprecated", "large", "complexity",
    "gods", "single-use", "props", "passthrough", "concerns", "deps", "dupes", "smells",
    "coupling", "patterns", "naming", "cycles", "orphaned", "react",
]

USAGE_EXAMPLES = """
workflow:
  scan                          Run all detectors, update state, show diff
  status                        Score dashboard with per-tier progress
  tree                          Annotated codebase tree (zoom with --focus)
  show <pattern>                Dig into findings by file/dir/detector/ID
  resolve <pattern> <status>    Mark findings as fixed/wontfix/false_positive
  ignore <pattern>              Suppress findings matching a pattern
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
  desloppify move src/shared/hooks/useFoo.ts src/shared/hooks/video/useFoo.ts --dry-run
  desloppify move scripts/foo/bar.py scripts/foo/baz/bar.py
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="desloppify",
        description="Desloppify — codebase health tracker",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Global flags
    parser.add_argument("--lang", type=str, default=None,
                        help="Language to scan (typescript, python). Auto-detected if omitted.")
    parser.add_argument("--exclude", action="append", default=None, metavar="PATTERN",
                        help="Path substring to exclude (repeatable: --exclude foo --exclude bar)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Run all detectors, update state, show diff")
    p_scan.add_argument("--path", type=str, default=None)
    p_scan.add_argument("--state", type=str, default=None)
    p_scan.add_argument("--skip-slow", action="store_true", help="Skip slow detectors (dupes)")
    p_scan.add_argument("--force-resolve", action="store_true",
                        help="Bypass suspect-detector protection (use when a detector legitimately went to 0)")

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

    p_fix = sub.add_parser("fix", help="Auto-fix mechanical issues")
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
    p_detect.add_argument("--fix", action="store_true", help="Auto-fix (logs only)")
    p_detect.add_argument("--category", choices=["imports", "vars", "params", "all"], default="all",
                          help="Filter unused by category")
    p_detect.add_argument("--threshold", type=float, default=None,
                          help="LOC threshold (large) or similarity (dupes)")
    p_detect.add_argument("--file", type=str, default=None, help="Show deps for specific file")

    p_move = sub.add_parser("move", help="Move a file and update all import references")
    p_move.add_argument("source", type=str, help="File to move (relative to project root)")
    p_move.add_argument("dest", type=str, help="Destination path (file or directory)")
    p_move.add_argument("--dry-run", action="store_true", help="Show changes without modifying files")

    return parser


def _apply_persisted_exclusions(args, state: dict):
    """Merge CLI --exclude with persisted config.exclude, set on utils global."""
    from .utils import set_exclusions, c

    cli_exclusions = getattr(args, "exclude", None) or []
    persisted = state.get("config", {}).get("exclude", [])
    combined = list(cli_exclusions) + [e for e in persisted if e not in cli_exclusions]
    if combined:
        set_exclusions(combined)
        import sys
        if cli_exclusions:
            print(c(f"  Excluding: {', '.join(combined)}", "dim"), file=sys.stderr)
        else:
            print(c(f"  Excluding (from state): {', '.join(combined)}", "dim"), file=sys.stderr)


def main():
    parser = create_parser()
    args = parser.parse_args()

    # Resolve default path from language config if not explicitly provided
    if getattr(args, "path", None) is None:
        lang = _resolve_lang(args)
        if lang:
            args.path = str(PROJECT_ROOT / lang.default_src)
        else:
            args.path = str(DEFAULT_PATH)

    # Load state once and apply exclusions before any command runs
    sp = _state_path(args)
    from .state import load_state
    state = load_state(sp)
    _apply_persisted_exclusions(args, state)
    args._preloaded_state = state
    args._state_path = sp

    # Lazy-load command handlers from commands/
    from .commands.scan import cmd_scan
    from .commands.status import cmd_status
    from .commands.show import cmd_show
    from .commands.next import cmd_next
    from .commands.resolve import cmd_resolve, cmd_ignore_pattern
    from .commands.fix_cmd import cmd_fix
    from .commands.plan_cmd import cmd_plan_output
    from .commands.detect import cmd_detect

    commands = {
        "scan": cmd_scan,
        "status": cmd_status,
        "show": cmd_show,
        "next": cmd_next,
        "resolve": cmd_resolve,
        "ignore": cmd_ignore_pattern,
        "fix": cmd_fix,
        "plan": cmd_plan_output,
        "detect": cmd_detect,
    }

    # Lazy-loaded commands
    if args.command == "tree":
        from .visualize import cmd_tree
        commands["tree"] = cmd_tree
    elif args.command == "viz":
        from .visualize import cmd_viz
        commands["viz"] = cmd_viz
    elif args.command == "move":
        from .commands.move import cmd_move
        commands["move"] = cmd_move

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
