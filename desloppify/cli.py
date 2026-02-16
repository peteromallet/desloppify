"""CLI entry point: parser wiring, subcommand routing, shared helpers."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from .cli_parser import build_parser
from .commands._helpers import resolve_lang, state_path
from .lang import available_langs, get_lang
from .registry import detector_names as _detector_names
from .utils import DEFAULT_PATH, PROJECT_ROOT

LOGGER = logging.getLogger(__name__)

DETECTOR_NAMES = _detector_names()

_COMMAND_MAP: dict[str, tuple[str, str]] = {
    "scan": (".commands.scan", "cmd_scan"),
    "status": (".commands.status", "cmd_status"),
    "explain": (".commands.scan", "cmd_explain"),
    "help-me-improve": (".commands.scan", "cmd_explain"),
    "show": (".commands.show", "cmd_show"),
    "next": (".commands.next", "cmd_next"),
    "resolve": (".commands.resolve", "cmd_resolve"),
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


def create_parser() -> argparse.ArgumentParser:
    """Build the top-level parser and all command-specific parsers."""
    langs = available_langs()
    fixer_help_lines = _build_fixer_help_lines(langs)
    return build_parser(
        langs=langs,
        detector_names=DETECTOR_NAMES,
        fixer_help_lines=fixer_help_lines,
    )


def _build_fixer_help_lines(langs: list[str]) -> list[str]:
    lines: list[str] = []
    for lang_name in langs:
        try:
            fixer_names = sorted(get_lang(lang_name).fixers.keys())
        except Exception:
            fixer_names = []
        fixer_list = ", ".join(fixer_names) if fixer_names else "none yet"
        lines.append(f"fixers ({lang_name}): {fixer_list}")
    return lines


def _subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _handle_help_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    topic = list(getattr(args, "topic", []) or [])
    if not topic:
        parser.print_help()
        return

    current: argparse.ArgumentParser = parser
    consumed: list[str] = []
    for token in topic:
        sub_action = _subparsers_action(current)
        if sub_action is None:
            joined = " ".join(topic)
            scope = " ".join(consumed) or "desloppify"
            raise SystemExit(f"No nested commands under '{scope}' (requested: '{joined}').")
        if token not in sub_action.choices:
            joined = " ".join(topic)
            scope = " ".join(consumed) or "desloppify"
            options = ", ".join(sorted(sub_action.choices))
            raise SystemExit(f"Unknown help topic '{joined}'. Available under '{scope}': {options}")
        current = sub_action.choices[token]
        consumed.append(token)
    current.print_help()


def _apply_persisted_exclusions(args, config: dict):
    """Merge CLI --exclude with persisted config.exclude, set on utils global."""
    from .utils import colorize, set_exclusions

    cli_exclusions = getattr(args, "exclude", None) or []
    persisted = config.get("exclude", [])
    combined = list(cli_exclusions) + [e for e in persisted if e not in cli_exclusions]
    if combined:
        set_exclusions(combined)
        if cli_exclusions:
            print(colorize(f"  Excluding: {', '.join(combined)}", "dim"), file=sys.stderr)
        else:
            print(colorize(f"  Excluding (from config): {', '.join(combined)}", "dim"), file=sys.stderr)


def main() -> None:
    """Parse args, preload config/state, and dispatch the selected command."""
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError) as exc:
            LOGGER.debug("Unable to reconfigure output stream", exc_info=exc)

    parser = create_parser()
    args = parser.parse_args()
    if args.command == "help":
        _handle_help_command(args, parser)
        return

    if getattr(args, "path", None) is None:
        lang = resolve_lang(args)
        args.path = str(PROJECT_ROOT / lang.default_src) if lang else str(DEFAULT_PATH)

    from .config import load_config

    config = load_config()
    args._config = config

    sp = state_path(args)
    from .state import load_state

    state = load_state(sp)
    _apply_persisted_exclusions(args, config)
    args._preloaded_state = state
    args._state_path = sp

    module_path, func_name = _COMMAND_MAP[args.command]
    mod = importlib.import_module(module_path, package="desloppify")
    handler = getattr(mod, func_name)

    try:
        handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
