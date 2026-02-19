"""CLI entrypoint for review command."""

from __future__ import annotations

import sys

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.utils import colorize

from .batch import _do_run_batches
from .single import _do_import, _do_prepare


def cmd_review(args) -> None:
    """Prepare or import subjective code review findings."""
    runtime = command_runtime(args)
    sp = runtime.state_path
    state = runtime.state
    lang = resolve_lang(args)

    if not lang:
        print(
            colorize("  Error: could not detect language. Use --lang.", "red"),
            file=sys.stderr,
        )
        sys.exit(1)

    if getattr(args, "run_batches", False):
        _do_run_batches(
            args,
            state,
            lang,
            sp,
            config=runtime.config,
        )
        return

    import_file = getattr(args, "import_file", None)
    holistic = True

    if import_file:
        _do_import(
            import_file,
            state,
            lang,
            sp,
            holistic=holistic,
            config=runtime.config,
        )
    else:
        _do_prepare(args, state, lang, sp, config=runtime.config, holistic=holistic)
