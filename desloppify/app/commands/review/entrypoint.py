"""CLI entrypoint for review command."""

from __future__ import annotations

import argparse
import sys

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.core.output_api import colorize

from .batch import _do_run_batches, do_import_run
from .external import do_external_start, do_external_submit
from .import_cmd import do_import, do_validate_import
from .merge import do_merge
from .preflight import review_rerun_preflight
from .prepare import do_prepare


def _enable_live_review_output() -> None:
    """Best-effort: force line-buffered review output for non-TTY runners."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(line_buffering=True, write_through=True)
        except (OSError, ValueError, TypeError) as exc:
            _ = exc


def _require_lang_or_exit(lang) -> None:
    if lang:
        return
    print(
        colorize("  Error: could not detect language. Use --lang.", "red"),
        file=sys.stderr,
    )
    sys.exit(1)


def _mode_flags(args: argparse.Namespace) -> tuple[list[bool], object, object]:
    merge = bool(getattr(args, "merge", False))
    run_batches = bool(getattr(args, "run_batches", False))
    import_run_dir = bool(getattr(args, "import_run_dir", None))
    external_start = bool(getattr(args, "external_start", False))
    external_submit = bool(getattr(args, "external_submit", False))
    import_file = getattr(args, "import_file", None)
    validate_import_file = getattr(args, "validate_import_file", None)
    import_mode = bool(import_file) and not external_submit
    flags = [
        merge,
        run_batches,
        import_run_dir,
        external_start,
        external_submit,
        import_mode,
        bool(validate_import_file),
    ]
    return flags, import_file, validate_import_file


def _validate_mode_selection_or_exit(
    args: argparse.Namespace,
    *,
    mode_flags: list[bool],
    import_file: object,
) -> None:
    if sum(1 for enabled in mode_flags if enabled) > 1:
        print(
            colorize(
                "  Error: choose one review mode per command "
                "(--merge | --run-batches | --import-run | --external-start | --external-submit | --import | --validate-import).",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    external_submit = bool(getattr(args, "external_submit", False))
    if external_submit and not import_file:
        print(
            colorize(
                "  Error: --external-submit requires --import FILE.",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    if external_submit and not getattr(args, "session_id", None):
        print(
            colorize(
                "  Error: --external-submit requires --session-id.",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(2)


def _run_review_mode(
    args: argparse.Namespace,
    *,
    runtime,
    state,
    lang,
    state_file,
    import_file,
    validate_import_file,
) -> None:
    if bool(getattr(args, "merge", False)):
        do_merge(args)
        return
    if bool(getattr(args, "run_batches", False)):
        review_rerun_preflight(state, args, state_file=state_file)
        _do_run_batches(
            args,
            state,
            lang,
            state_file,
            config=runtime.config,
        )
        return
    import_run_dir = getattr(args, "import_run_dir", None)
    if import_run_dir:
        do_import_run(
            import_run_dir,
            state,
            lang,
            state_file,
            config=runtime.config,
            allow_partial=bool(getattr(args, "allow_partial", False)),
            scan_after_import=bool(getattr(args, "scan_after_import", False)),
            scan_path=str(getattr(args, "path", ".") or "."),
        )
        return
    if bool(getattr(args, "external_start", False)):
        review_rerun_preflight(state, args, state_file=state_file)
        do_external_start(
            args,
            state,
            lang,
            config=runtime.config,
        )
        return
    if bool(getattr(args, "external_submit", False)):
        do_external_submit(
            import_file=str(import_file),
            session_id=str(getattr(args, "session_id")),
            state=state,
            lang=lang,
            state_file=state_file,
            config=runtime.config,
            allow_partial=bool(getattr(args, "allow_partial", False)),
            scan_after_import=bool(getattr(args, "scan_after_import", False)),
            scan_path=str(getattr(args, "path", ".") or "."),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        return
    if validate_import_file:
        do_validate_import(
            validate_import_file,
            lang,
            allow_partial=bool(getattr(args, "allow_partial", False)),
            manual_override=bool(getattr(args, "manual_override", False)),
            attested_external=bool(getattr(args, "attested_external", False)),
            manual_attest=getattr(args, "attest", None),
        )
        return

    if import_file:
        do_import(
            import_file,
            state,
            lang,
            state_file,
            config=runtime.config,
            allow_partial=bool(getattr(args, "allow_partial", False)),
            manual_override=bool(getattr(args, "manual_override", False)),
            attested_external=bool(getattr(args, "attested_external", False)),
            manual_attest=getattr(args, "attest", None),
        )
        return
    review_rerun_preflight(state, args, state_file=state_file)
    do_prepare(args, state, lang, state_file, config=runtime.config)


def cmd_review(args: argparse.Namespace) -> None:
    """Prepare or import subjective code review findings."""
    _enable_live_review_output()
    runtime = command_runtime(args)
    state_file = runtime.state_path
    state = runtime.state
    lang = resolve_lang(args)
    _require_lang_or_exit(lang)

    mode_flags, import_file, validate_import_file = _mode_flags(args)
    _validate_mode_selection_or_exit(
        args,
        mode_flags=mode_flags,
        import_file=import_file,
    )
    _run_review_mode(
        args,
        runtime=runtime,
        state=state,
        lang=lang,
        state_file=state_file,
        import_file=import_file,
        validate_import_file=validate_import_file,
    )
