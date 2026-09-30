"""CLI entrypoint for review command."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.state import require_scan_metrics
from desloppify.base.exception_sets import CommandError

from .batch.orchestrator import do_import_run, do_run_batches
from .external import do_external_start, do_external_submit
from .importing.cmd import do_import, do_validate_import
from .importing.flags import ReviewImportConfig
from .merge import do_merge
from .preflight import review_rerun_preflight
from .prepare import do_prepare


@dataclass(frozen=True)
class ReviewOptions:
    """All user-facing review command options extracted once from argparse."""

    merge: bool = False
    run_batches: bool = False
    import_run_dir: str | None = None
    external_start: bool = False
    external_submit: bool = False
    import_file: str | None = None
    validate_import_file: str | None = None
    session_id: str | None = None
    allow_partial: bool = False
    scan_after_import: bool = False
    path: str = "."
    dry_run: bool = False
    manual_override: bool = False
    attested_external: bool = False
    attest: str | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> ReviewOptions:
        return cls(
            merge=bool(getattr(args, "merge", False)),
            run_batches=bool(getattr(args, "run_batches", False)),
            import_run_dir=getattr(args, "import_run_dir", None),
            external_start=bool(getattr(args, "external_start", False)),
            external_submit=bool(getattr(args, "external_submit", False)),
            import_file=getattr(args, "import_file", None),
            validate_import_file=getattr(args, "validate_import_file", None),
            session_id=getattr(args, "session_id", None),
            allow_partial=bool(getattr(args, "allow_partial", False)),
            scan_after_import=bool(getattr(args, "scan_after_import", False)),
            path=str(getattr(args, "path", ".") or "."),
            dry_run=bool(getattr(args, "dry_run", False)),
            manual_override=bool(getattr(args, "manual_override", False)),
            attested_external=bool(getattr(args, "attested_external", False)),
            attest=getattr(args, "attest", None),
        )


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


def _require_lang(lang) -> None:
    if lang:
        return
    raise CommandError("Error: could not detect language. Use --lang.", exit_code=1)


def _mode_flags(opts: ReviewOptions) -> list[bool]:
    import_mode = bool(opts.import_file) and not opts.external_submit
    return [
        opts.merge,
        opts.run_batches,
        bool(opts.import_run_dir),
        opts.external_start,
        opts.external_submit,
        import_mode,
        bool(opts.validate_import_file),
    ]


def _validate_mode_selection(
    opts: ReviewOptions,
    *,
    mode_flags: list[bool],
) -> None:
    if sum(1 for enabled in mode_flags if enabled) > 1:
        raise CommandError(
            "Error: choose one review mode per command "
            "(--merge | --run-batches | --import-run | --external-start | --external-submit | --import | --validate-import).",
            exit_code=1,
        )

    if opts.external_submit and not opts.import_file:
        raise CommandError(
            "Error: --external-submit requires --import FILE.",
            exit_code=2,
        )
    if opts.external_submit and not opts.session_id:
        raise CommandError(
            "Error: --external-submit requires --session-id.",
            exit_code=2,
        )


def _is_default_prepare_mode(opts: ReviewOptions, mode_flags: list[bool]) -> bool:
    """True when the command will run the default prepare flow (no explicit mode)."""
    return not any(mode_flags) and not opts.import_file


def _run_review_mode(
    args: argparse.Namespace,
    *,
    opts: ReviewOptions,
    runtime,
    state,
    lang,
    state_file,
) -> None:
    if opts.merge:
        do_merge(args)
        return
    if opts.run_batches:
        review_rerun_preflight(state, args, state_file=state_file)
        do_run_batches(
            args,
            state,
            lang,
            state_file,
            config=runtime.config,
        )
        return
    if opts.import_run_dir:
        do_import_run(
            opts.import_run_dir,
            state,
            lang,
            state_file,
            config=runtime.config,
            allow_partial=opts.allow_partial,
            scan_after_import=opts.scan_after_import,
            scan_path=opts.path,
            dry_run=opts.dry_run,
            only_batches=getattr(args, "only_batches", None),
        )
        return
    if opts.external_start:
        review_rerun_preflight(state, args, state_file=state_file)
        do_external_start(
            args,
            state,
            lang,
            config=runtime.config,
        )
        return
    if opts.external_submit:
        do_external_submit(
            import_file=str(opts.import_file),
            session_id=str(opts.session_id),
            state=state,
            lang=lang,
            state_file=state_file,
            config=runtime.config,
            allow_partial=opts.allow_partial,
            scan_after_import=opts.scan_after_import,
            scan_path=opts.path,
            dry_run=opts.dry_run,
        )
        return
    if opts.validate_import_file:
        do_validate_import(
            opts.validate_import_file,
            lang,
            import_config=ReviewImportConfig(
                allow_partial=opts.allow_partial,
                manual_override=opts.manual_override,
                attested_external=opts.attested_external,
                manual_attest=opts.attest,
            ),
        )
        return

    if opts.import_file:
        do_import(
            opts.import_file,
            state,
            lang,
            state_file,
            import_config=ReviewImportConfig(
                config=runtime.config,
                allow_partial=opts.allow_partial,
                manual_override=opts.manual_override,
                attested_external=opts.attested_external,
                manual_attest=opts.attest,
            ),
            dry_run=opts.dry_run,
        )
        return
    review_rerun_preflight(state, args, state_file=state_file)
    do_prepare(args, state, lang, state_file, config=runtime.config)


def cmd_review(args: argparse.Namespace) -> None:
    """Prepare or import subjective code review issues."""
    _enable_live_review_output()
    runtime = command_runtime(args)
    state_file = runtime.state_path
    state = runtime.state
    lang = resolve_lang(args)
    _require_lang(lang)

    opts = ReviewOptions.from_args(args)
    mode_flags = _mode_flags(opts)
    _validate_mode_selection(
        opts,
        mode_flags=mode_flags,
    )

    # Default prepare and --run-batches need real scan-backed context rather
    # than reconstructed plan inventory.
    if _is_default_prepare_mode(opts, mode_flags) or opts.run_batches:
        if not require_scan_metrics(state):
            return

    _run_review_mode(
        args,
        opts=opts,
        runtime=runtime,
        state=state,
        lang=lang,
        state_file=state_file,
    )
