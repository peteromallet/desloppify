"""CLI entry point: parse args, load shared context, dispatch command handlers."""

from __future__ import annotations

import logging
import sys

from desloppify import utils as utils_mod
from desloppify.app.cli_support.parser import create_parser as _create_parser
from desloppify.app.commands.helpers.lang import LangResolutionError, resolve_lang
from desloppify.app.commands.helpers.runtime import CommandRuntime
from desloppify.app.commands.helpers.state import state_path
from desloppify.app.commands.registry import COMMAND_HANDLERS
from desloppify.core.config import load_config
from desloppify.core.registry import detector_names as _detector_names
from desloppify.core.runtime_state import runtime_scope
from desloppify.languages import available_langs
from desloppify.state import load_state
from desloppify.utils import DEFAULT_PATH, PROJECT_ROOT

DETECTOR_NAMES = _detector_names()
logger = logging.getLogger(__name__)

def create_parser():
    """Return the top-level argparse parser."""
    return _create_parser(langs=available_langs(), detector_names=DETECTOR_NAMES)


def _apply_persisted_exclusions(args, config: dict):
    """Merge CLI --exclude with persisted config.exclude and apply globally."""
    cli_exclusions = getattr(args, "exclude", None) or []
    persisted = config.get("exclude", [])
    combined = list(cli_exclusions) + [e for e in persisted if e not in cli_exclusions]
    if not combined:
        return
    utils_mod.set_exclusions(combined)
    if cli_exclusions:
        print(
            utils_mod.colorize(f"  Excluding: {', '.join(combined)}", "dim"),
            file=sys.stderr,
        )
        return
    print(
        utils_mod.colorize(
            f"  Excluding (from config): {', '.join(combined)}", "dim"
        ),
        file=sys.stderr,
    )


def _resolve_default_path(args) -> None:
    """Fill args.path from detected language or default source path.

    For the review command, the last scan path (stored in state) is used as the
    default so that ``desloppify review --prepare`` works on the same scope as
    the preceding scan even when the project files are not under ``src/``.
    """
    if getattr(args, "path", None) is not None:
        return
    if getattr(args, "command", None) == "review":
        try:
            sp = state_path(args)
            if sp:
                saved = load_state(sp)
                saved_path = saved.get("scan_path")
                if saved_path:
                    args.path = str((PROJECT_ROOT / saved_path).resolve())
                    return
        except Exception:
            pass
    lang = resolve_lang(args)
    if lang:
        args.path = str(PROJECT_ROOT / lang.default_src)
    else:
        args.path = str(DEFAULT_PATH)


def _load_shared_runtime(args) -> None:
    """Load config/state and attach shared objects to parsed args."""
    config = load_config()

    sp = state_path(args)
    state = load_state(sp)
    _apply_persisted_exclusions(args, config)

    args.runtime = CommandRuntime(config=config, state=state, state_path=sp)


def _resolve_handler(command: str):
    return COMMAND_HANDLERS[command]


def _handle_help_command(args, parser) -> None:
    """Handle explicit help command when present in parser config."""
    topic = list(getattr(args, "topic", []) or [])
    try:
        parser.parse_args([*topic, "--help"])
    except SystemExit:
        return


def main() -> None:
    # Ensure Unicode output works on Windows terminals (cp1252 etc.)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                logger.debug(
                    "Skipping stream reconfigure for %s (not supported)",
                    getattr(stream, "name", "<stream>"),
                )

    parser = create_parser()
    args = parser.parse_args()
    if args.command == "help":
        _handle_help_command(args, parser)
        return

    try:
        with runtime_scope():
            _resolve_default_path(args)
            _load_shared_runtime(args)

            handler = _resolve_handler(args.command)
            handler(args)
    except LangResolutionError as exc:
        from desloppify.utils import colorize

        print(colorize(f"  {exc.message}", "red"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
