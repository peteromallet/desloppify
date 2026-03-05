"""CLI entry point: parse args, load shared context, dispatch command handlers."""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
import argparse
from desloppify.app.cli_support.parser import create_parser as _create_parser
from desloppify.app.commands.helpers.lang import LangResolutionError, resolve_lang
from desloppify.app.commands.helpers.runtime import CommandRuntime
from desloppify.app.commands.helpers.state import state_path
from desloppify.app.commands.registry import get_command_handlers
from desloppify.base.config import load_config
from desloppify.base.discovery.source import set_exclusions
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.output.terminal import colorize
from desloppify.base.discovery.paths import get_default_path, get_project_root
from desloppify.base.registry import detector_names, on_detector_registered
from desloppify.base.runtime_state import runtime_scope
from desloppify.base.runtime_state import current_runtime_context
from desloppify.languages import available_langs
from desloppify.state import load_state

logger = logging.getLogger(__name__)


class _DetectorNamesCacheCompat:
    """Compat shim for tests that poke the legacy detector-name cache."""

    def __init__(self) -> None:
        self._store: dict[str, list[str]] = {}

    def __contains__(self, key: object) -> bool:
        return key in self._store

    def __getitem__(self, key: str) -> list[str]:
        return self._store[key]

    def __setitem__(self, key: str, value: list[str]) -> None:
        self._store[key] = value

    def pop(self, key: str, default=None):
        return self._store.pop(key, default)


_DETECTOR_NAMES_CACHE = _DetectorNamesCacheCompat()


@lru_cache(maxsize=1)
def _get_detector_names_cached() -> tuple[str, ...]:
    """Compute detector names once until cache invalidation."""
    return tuple(detector_names())


def _get_detector_names() -> list[str]:
    """Return cached detector names, computing on first access."""
    return list(_get_detector_names_cached())


def _invalidate_detector_names_cache() -> None:
    """Invalidate detector-name cache when runtime registrations change."""
    _get_detector_names_cached.cache_clear()
    _DETECTOR_NAMES_CACHE.pop("names", None)


on_detector_registered(_invalidate_detector_names_cache)


def create_parser():
    """Return the top-level argparse parser."""
    return _create_parser(langs=available_langs(), detector_names=_get_detector_names())


def _apply_persisted_exclusions(args, config: dict):
    """Merge CLI --exclude with persisted config.exclude and apply globally."""
    cli_exclusions = getattr(args, "exclude", None) or []
    persisted = config.get("exclude", [])
    combined = list(cli_exclusions) + [e for e in persisted if e not in cli_exclusions]
    if not combined:
        return
    set_exclusions(combined)
    if cli_exclusions:
        print(
            colorize(f"  Excluding: {', '.join(combined)}", "dim"),
            file=sys.stderr,
        )
        return
    print(
        colorize(
            f"  Excluding (from config): {', '.join(combined)}", "dim"
        ),
        file=sys.stderr,
    )


def _resolve_default_path(args: argparse.Namespace) -> None:
    """Fill args.path from detected language or default source path.

    For the review command, the last scan path (stored in state) is used as the
    default so that ``desloppify review --prepare`` works on the same scope as
    the preceding scan even when the project files are not under ``src/``.
    """
    if getattr(args, "path", None) is not None:
        return
    runtime_root = get_project_root()
    if getattr(args, "command", None) == "review":
        try:
            state_file = state_path(args)
            if state_file:
                saved = load_state(state_file)
                saved_path = saved.get("scan_path")
                if saved_path:
                    args.path = str((runtime_root / saved_path).resolve())
                    return
        except (OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
            log_best_effort_failure(logger, "resolve default review path from saved state", exc)
    lang = resolve_lang(args)
    if lang:
        args.path = str(runtime_root / lang.default_src)
    else:
        args.path = str(get_default_path())


def _load_shared_runtime(args: argparse.Namespace) -> None:
    """Load config/state and attach shared objects to parsed args."""
    config = load_config()

    state_file = state_path(args)
    state = load_state(state_file)
    _apply_persisted_exclusions(args, config)

    args.runtime = CommandRuntime(config=config, state=state, state_path=state_file)


def _resolve_handler(command: str):
    return get_command_handlers()[command]


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
    if not args.command:
        parser.print_help()
        return
    if args.command == "help":
        _handle_help_command(args, parser)
        return

    try:
        with runtime_scope():
            current_runtime_context().allow_unsafe_coerce = bool(
                getattr(args, "allow_unsafe_coerce", False)
            )
            _resolve_default_path(args)
            _load_shared_runtime(args)

            handler = _resolve_handler(args.command)
            handler(args)
    except CommandError as exc:
        print(colorize(f"  {exc.message}", "red"), file=sys.stderr)
        sys.exit(exc.exit_code)
    except LangResolutionError as exc:
        print(colorize(f"  {exc.message}", "red"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
