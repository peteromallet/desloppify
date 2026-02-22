"""CLI parser group builders for admin/workflow command families."""

from __future__ import annotations

import argparse
import sys

from desloppify.languages import get_lang


class _DeprecatedAction(argparse.Action):
    """Argparse action that prints a deprecation warning and stores the value."""

    def __call__(self, parser, namespace, values, option_string=None):
        print(
            f"Warning: {option_string} is deprecated and will be removed in a future version.",
            file=sys.stderr,
        )
        setattr(namespace, self.dest, values)


class _DeprecatedBoolAction(argparse.Action):
    """Argparse action for deprecated boolean flags (store_true equivalent)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("nargs", 0)
        kwargs.setdefault("const", True)
        kwargs.setdefault("default", False)
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(
            f"Warning: {option_string} is deprecated and will be removed in a future version.",
            file=sys.stderr,
        )
        setattr(namespace, self.dest, True)


def _add_detect_parser(sub, detector_names: list[str]) -> None:
    p_detect = sub.add_parser(
        "detect",
        help="Run a single detector directly (bypass state)",
        epilog=f"detectors: {', '.join(detector_names)}",
    )
    p_detect.add_argument("detector", type=str, help="Detector to run")
    p_detect.add_argument("--top", type=int, default=20)
    p_detect.add_argument("--path", type=str, default=None)
    p_detect.add_argument("--json", action="store_true")
    p_detect.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix detected issues (logs detector only)",
    )
    p_detect.add_argument(
        "--category",
        choices=["imports", "vars", "params", "all"],
        default="all",
        help="Filter unused by category",
    )
    p_detect.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="LOC threshold (large) or similarity (dupes)",
    )
    p_detect.add_argument(
        "--file", type=str, default=None, help="Show deps for specific file"
    )
    p_detect.add_argument(
        "--lang-opt",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Language runtime option override (repeatable)",
    )


def _add_move_parser(sub) -> None:
    p_move = sub.add_parser(
        "move", help="Move a file or directory and update all import references"
    )
    p_move.add_argument(
        "source", type=str, help="File or directory to move (relative to project root)"
    )
    p_move.add_argument("dest", type=str, help="Destination path (file or directory)")
    p_move.add_argument(
        "--dry-run", action="store_true", help="Show changes without modifying files"
    )


def _add_review_parser(sub) -> None:
    p_review = sub.add_parser(
        "review", help="Prepare or import holistic subjective review"
    )
    p_review.add_argument("--path", type=str, default=None)
    p_review.add_argument("--state", type=str, default=None)
    p_review.add_argument(
        "--prepare",
        action="store_true",
        help="Prepare review data (output to query.json)",
    )
    p_review.add_argument(
        "--import",
        dest="import_file",
        type=str,
        metavar="FILE",
        help="Import review findings from JSON file",
    )
    p_review.add_argument(
        "--max-age",
        type=int,
        default=None,
        action=_DeprecatedAction,
        help="Deprecated in holistic-only mode (ignored)",
    )
    p_review.add_argument(
        "--max-files",
        type=int,
        default=None,
        action=_DeprecatedAction,
        help="Deprecated in holistic-only mode (ignored)",
    )
    p_review.add_argument(
        "--refresh",
        action=_DeprecatedBoolAction,
        help="Deprecated in holistic-only mode (ignored)",
    )
    p_review.add_argument(
        "--dimensions",
        type=str,
        default=None,
        help="Comma-separated dimensions to evaluate",
    )
    p_review.add_argument(
        "--holistic",
        action=_DeprecatedBoolAction,
        help="Deprecated: holistic is now the only review mode",
    )
    p_review.add_argument(
        "--run-batches",
        action="store_true",
        help="Run holistic investigation batches with subagents and merge/import output",
    )
    p_review.add_argument(
        "--runner",
        choices=["codex"],
        default="codex",
        help="Subagent runner backend (default: codex)",
    )
    p_review.add_argument(
        "--parallel", action="store_true", help="Run selected batches in parallel"
    )
    p_review.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate packet/prompts only (skip runner/import)",
    )
    p_review.add_argument(
        "--packet",
        type=str,
        default=None,
        help="Use an existing immutable packet JSON instead of preparing a new one",
    )
    p_review.add_argument(
        "--only-batches",
        type=str,
        default=None,
        help="Comma-separated 1-based batch indexes to run (e.g. 1,3,5)",
    )
    p_review.add_argument(
        "--scan-after-import",
        action="store_true",
        help="Run `scan` after successful merged import",
    )


def _add_issues_parser(sub) -> None:
    p_issues = sub.add_parser("issues", help="Review findings work queue")
    p_issues.add_argument("--state", type=str, default=None)
    issues_sub = p_issues.add_subparsers(dest="issues_action")
    issues_sub.add_parser("list", help="List open review findings")
    iss_show = issues_sub.add_parser("show", help="Show issue details")
    iss_show.add_argument("number", type=int)
    iss_update = issues_sub.add_parser("update", help="Add investigation to an issue")
    iss_update.add_argument("number", type=int)
    iss_update.add_argument("--file", type=str, required=True)


def _add_zone_parser(sub) -> None:
    p_zone = sub.add_parser("zone", help="Show/set/clear zone classifications")
    p_zone.add_argument("--path", type=str, default=None)
    p_zone.add_argument("--state", type=str, default=None)
    zone_sub = p_zone.add_subparsers(dest="zone_action")
    zone_sub.add_parser("show", help="Show zone classifications for all files")
    z_set = zone_sub.add_parser("set", help="Override zone for a file")
    z_set.add_argument("zone_path", type=str, help="Relative file path")
    z_set.add_argument(
        "zone_value",
        type=str,
        help="Zone (production, test, config, generated, script, vendor)",
    )
    z_clear = zone_sub.add_parser("clear", help="Remove zone override for a file")
    z_clear.add_argument("zone_path", type=str, help="Relative file path")


def _add_config_parser(sub) -> None:
    p_config = sub.add_parser("config", help="Show/set/unset project configuration")
    config_sub = p_config.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Show all config values")
    c_set = config_sub.add_parser("set", help="Set a config value")
    c_set.add_argument("config_key", type=str, help="Config key name")
    c_set.add_argument("config_value", type=str, help="Value to set")
    c_unset = config_sub.add_parser("unset", help="Reset a config key to default")
    c_unset.add_argument("config_key", type=str, help="Config key name")


def _fixer_help_lines(langs: list[str]) -> list[str]:
    fixer_help_lines: list[str] = []
    for lang_name in langs:
        try:
            fixer_names = sorted(get_lang(lang_name).fixers.keys())
        except (ImportError, ValueError, TypeError, AttributeError):
            fixer_names = []
        fixer_list = ", ".join(fixer_names) if fixer_names else "none yet"
        fixer_help_lines.append(f"fixers ({lang_name}): {fixer_list}")
    fixer_help_lines.append("special: review — prepare structured review data")
    return fixer_help_lines


def _add_fix_parser(sub, langs: list[str]) -> None:
    p_fix = sub.add_parser(
        "fix",
        help="Auto-fix mechanical issues",
        epilog="\n".join(_fixer_help_lines(langs)),
    )
    p_fix.add_argument("fixer", type=str, help="What to fix")
    p_fix.add_argument("--path", type=str, default=None)
    p_fix.add_argument("--state", type=str, default=None)
    p_fix.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )


def _add_plan_parser(sub) -> None:
    p_plan = sub.add_parser(
        "plan", help="Generate prioritized markdown plan from state"
    )
    p_plan.add_argument("--state", type=str, default=None)
    p_plan.add_argument(
        "--output", type=str, metavar="FILE", help="Write to file instead of stdout"
    )


def _add_viz_parser(sub) -> None:
    p_viz = sub.add_parser("viz", help="Generate interactive HTML treemap")
    p_viz.add_argument("--path", type=str, default=None)
    p_viz.add_argument("--output", type=str, default=None)
    p_viz.add_argument("--state", type=str, default=None)


def _add_dev_parser(sub) -> None:
    p_dev = sub.add_parser("dev", help="Developer utilities")
    dev_sub = p_dev.add_subparsers(dest="dev_action", required=True)
    d_scaffold = dev_sub.add_parser(
        "scaffold-lang", help="Generate a standardized language plugin scaffold"
    )
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
    d_scaffold.add_argument(
        "--force", action="store_true", help="Overwrite existing scaffold files"
    )
    d_scaffold.add_argument(
        "--no-wire-pyproject",
        dest="wire_pyproject",
        action="store_false",
        help="Do not edit pyproject.toml testpaths array",
    )
    d_scaffold.set_defaults(wire_pyproject=True)


def _add_langs_parser(sub) -> None:
    sub.add_parser("langs", help="List all available language plugins with depth and tools")


def _add_update_skill_parser(sub) -> None:
    p = sub.add_parser(
        "update-skill",
        help="Install or update the desloppify skill/agent document",
    )
    p.add_argument(
        "interface",
        nargs="?",
        default=None,
        help="Agent interface (claude, codex, cursor, copilot, windsurf, gemini). "
        "Auto-detected on updates if omitted.",
    )


