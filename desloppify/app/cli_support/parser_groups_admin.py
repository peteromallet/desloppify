"""CLI parser group builders for admin/workflow command families."""

from __future__ import annotations

import logging

from desloppify.app.commands.helpers.lang import load_lang_config
from .parser_groups_admin_review import _add_review_parser  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)


def _add_detect_parser(sub, detector_names: list[str]) -> None:
    p_detect = sub.add_parser(
        "detect",
        help="Run a single detector directly (bypass state)",
        epilog=f"detectors: {', '.join(detector_names)}",
    )
    p_detect.add_argument("detector", type=str, help="Detector to run")
    p_detect.add_argument("--top", type=int, default=20, help="Max items to show (default: 20)")
    p_detect.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_detect.add_argument("--json", action="store_true", help="Output as JSON")
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


def _add_zone_parser(sub) -> None:
    p_zone = sub.add_parser("zone", help="Show/set/clear zone classifications")
    p_zone.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_zone.add_argument("--state", type=str, default=None, help="Path to state file")
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


def _add_directives_parser(sub) -> None:
    p = sub.add_parser("directives", help="View/set agent directives for phase transitions")
    d_sub = p.add_subparsers(dest="directives_action")
    d_sub.add_parser("show", help="Show all configured directives")
    d_set = d_sub.add_parser("set", help="Set a directive for a lifecycle phase")
    d_set.add_argument("phase", type=str, help="Lifecycle phase name")
    d_set.add_argument("message", type=str, help="Message to show at this transition")
    d_unset = d_sub.add_parser("unset", help="Remove a directive for a lifecycle phase")
    d_unset.add_argument("phase", type=str, help="Lifecycle phase name")


def _fixer_help_lines(langs: list[str]) -> list[str]:
    fixer_help_lines: list[str] = []
    for lang_name in langs:
        try:
            fixer_names = sorted(load_lang_config(lang_name).fixers.keys())
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("Failed to load fixer metadata for %s: %s", lang_name, exc)
            fixer_help_lines.append(
                f"fixers ({lang_name}): language plugin failed to load ({exc})"
            )
            continue
        fixer_list = ", ".join(fixer_names) if fixer_names else "none yet"
        fixer_help_lines.append(f"fixers ({lang_name}): {fixer_list}")
    return fixer_help_lines


def _add_autofix_parser(sub, langs: list[str]) -> None:
    p_autofix = sub.add_parser(
        "autofix",
        help="Auto-fix mechanical issues",
        epilog="\n".join(_fixer_help_lines(langs)),
    )
    p_autofix.add_argument("fixer", type=str, help="What to fix")
    p_autofix.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_autofix.add_argument("--state", type=str, default=None, help="Path to state file")
    p_autofix.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )


def _add_viz_parser(sub) -> None:
    p_viz = sub.add_parser("viz", help="Generate interactive HTML treemap")
    p_viz.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_viz.add_argument("--output", type=str, default=None, help="Output file path")
    p_viz.add_argument("--state", type=str, default=None, help="Path to state file")


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

    dev_sub.add_parser("test-hermes", help="Test Hermes model switching (switch and switch back)")


def _add_langs_parser(sub) -> None:
    sub.add_parser("langs", help="List all available language plugins with depth and tools")


def _add_persona_qa_parser(sub) -> None:
    p = sub.add_parser(
        "persona-qa",
        help="Persona-based browser QA testing",
        epilog="""\
examples:
  desloppify persona-qa --url http://localhost:3000
  desloppify persona-qa --prepare --url http://localhost:3000 --persona new-visitor
  desloppify persona-qa --import findings.json
  desloppify persona-qa --status
  desloppify persona-qa --clear""",
    )
    p.add_argument("--url", type=str, default=None, help="Base URL to test against")
    p.add_argument("--persona", type=str, default=None, help="Run only a specific persona (by name or filename)")
    p.add_argument("--prepare", action="store_true", help="Print structured agent instructions (default when --url given)")
    p.add_argument("--import", dest="import_file", type=str, default=None, help="Import findings JSON into state")
    p.add_argument("--status", action="store_true", help="Show per-persona pass/fail summary")
    p.add_argument("--clear", action="store_true", help="Remove all persona QA findings from state")


def _add_update_skill_parser(sub) -> None:
    p = sub.add_parser(
        "update-skill",
        help="Install or update the desloppify skill/agent document",
    )
    p.add_argument(
        "interface",
        nargs="?",
        default=None,
        help="Agent interface (amp, claude, codex, cursor, copilot, windsurf, gemini, hermes, droid, opencode). "
        "Auto-detected on updates if omitted.",
    )
