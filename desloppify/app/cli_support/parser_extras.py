"""Secondary parser helpers for less frequently used CLI commands."""

from __future__ import annotations

from collections.abc import Sequence


def add_detect_parser(sub, detector_names: Sequence[str]) -> None:
    parser = sub.add_parser(
        "detect",
        help="Run a single detector directly (bypass state)",
        epilog=f"detectors: {', '.join(detector_names)}",
    )
    parser.add_argument("detector", type=str, help="Detector to run")
    parser.add_argument("--top", type=int, default=20, help="Max findings to display (default: 20)")
    parser.add_argument("--path", type=str, default=None, help="Path to scan (default: language source root)")
    parser.add_argument("--json", action="store_true", help="Output detector results as JSON")
    parser.add_argument("--fix", action="store_true", help="Auto-fix detected issues (logs detector only)")
    parser.add_argument(
        "--category",
        choices=["imports", "vars", "params", "all"],
        default="all",
        help="Filter unused detector results by category",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="LOC threshold (large) or similarity (dupes)",
    )
    parser.add_argument("--file", type=str, default=None, help="Show deps for specific file")
    parser.add_argument(
        "--lang-opt",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Language runtime option override (repeatable)",
    )


def add_move_parser(sub) -> None:
    parser = sub.add_parser("move", help="Move a file or directory and update all import references")
    parser.add_argument("source", type=str, help="File or directory to move (relative to project root)")
    parser.add_argument("dest", type=str, help="Destination path (file or directory)")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying files")


def add_review_parser(sub) -> None:
    parser = sub.add_parser("review", help="Prepare or import subjective code review")
    parser.add_argument("--path", type=str, default=None, help="Path to review (default: language source root)")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    parser.add_argument("--prepare", action="store_true", help="Prepare review data (output to query.json)")
    parser.add_argument(
        "--import",
        dest="import_file",
        type=str,
        metavar="FILE",
        help="Import review findings from JSON file",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=None,
        help="Staleness threshold in days (default: from config, or 30)",
    )
    parser.add_argument("--max-files", type=int, default=50, help="Maximum files to evaluate (default: 50)")
    parser.add_argument("--refresh", action="store_true", help="Force re-evaluate everything (ignore cache)")
    parser.add_argument("--dimensions", type=str, default=None, help="Comma-separated dimensions to evaluate")
    parser.add_argument(
        "--allow-custom-dimensions",
        action="store_true",
        help="Allow custom dimension names when prefixed with custom_",
    )
    parser.add_argument(
        "--holistic",
        action="store_true",
        help="Prepare/import holistic codebase-wide review",
    )
    parser.add_argument(
        "--assessment-override",
        action="store_true",
        help="Allow large assessment-only score swings without findings (requires --assessment-note)",
    )
    parser.add_argument(
        "--assessment-note",
        type=str,
        default=None,
        help="Rationale recorded when using --assessment-override",
    )


def add_issues_parser(sub) -> None:
    parser = sub.add_parser("issues", help="Review findings work queue")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    issues_sub = parser.add_subparsers(dest="issues_action")

    show_parser = issues_sub.add_parser("show", help="Show issue details")
    show_parser.add_argument("number", type=int, help="Issue number from `desloppify issues` output")

    update_parser = issues_sub.add_parser("update", help="Add investigation to an issue")
    update_parser.add_argument("number", type=int, help="Issue number from `desloppify issues` output")
    update_parser.add_argument("--file", type=str, required=True, help="Path to investigation notes file")


def add_zone_parser(sub) -> None:
    parser = sub.add_parser("zone", help="Show/set/clear zone classifications")
    parser.add_argument("--path", type=str, default=None, help="Path to classify (default: language source root)")
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="State file path override (default: .desloppify/state-<lang>.json)",
    )
    zone_sub = parser.add_subparsers(dest="zone_action")
    parser.set_defaults(zone_action="show")
    zone_sub.add_parser("show", help="Show zone classifications for all files")

    set_parser = zone_sub.add_parser("set", help="Override zone for a file")
    set_parser.add_argument("zone_path", type=str, help="Relative file path")
    set_parser.add_argument(
        "zone_value",
        type=str,
        help="Zone (production, test, config, generated, script, vendor)",
    )

    clear_parser = zone_sub.add_parser("clear", help="Remove zone override for a file")
    clear_parser.add_argument("zone_path", type=str, help="Relative file path")


def add_config_parser(sub) -> None:
    parser = sub.add_parser("config", help="Show/set/unset project configuration")
    config_sub = parser.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Show all config values")

    set_parser = config_sub.add_parser("set", help="Set a config value")
    set_parser.add_argument("config_key", type=str, help="Config key name")
    set_parser.add_argument("config_value", type=str, help="Value to set")

    unset_parser = config_sub.add_parser("unset", help="Reset a config key to default")
    unset_parser.add_argument("config_key", type=str, help="Config key name")


def add_help_parser(sub) -> None:
    """Add explicit help command parser with optional command topic path."""
    parser = sub.add_parser("help", help="Show top-level help or help for a specific command")
    parser.add_argument(
        "topic",
        nargs="*",
        metavar="COMMAND",
        help="Optional command path, e.g. `help scan` or `help issues update`",
    )


def add_dev_parser(sub) -> None:
    parser = sub.add_parser("dev", help="Developer utilities")
    dev_sub = parser.add_subparsers(dest="dev_action", required=True)
    scaffold = dev_sub.add_parser("scaffold-lang", help="Generate a standardized language plugin scaffold")
    scaffold.add_argument("name", type=str, help="Language name (snake_case)")
    scaffold.add_argument(
        "--extension",
        action="append",
        default=None,
        metavar="EXT",
        help="Source file extension (repeatable, e.g. --extension .go --extension .gomod)",
    )
    scaffold.add_argument(
        "--marker",
        action="append",
        default=None,
        metavar="FILE",
        help="Project-root detection marker file (repeatable)",
    )
    scaffold.add_argument(
        "--default-src",
        type=str,
        default="src",
        metavar="DIR",
        help="Default source directory for scans (default: src)",
    )
    scaffold.add_argument("--force", action="store_true", help="Overwrite existing scaffold files")
    scaffold.add_argument(
        "--no-wire-pyproject",
        dest="wire_pyproject",
        action="store_false",
        help="Do not edit pyproject.toml testpaths/exclude arrays",
    )
    scaffold.set_defaults(wire_pyproject=True)
