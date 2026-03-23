"""Prepare flow for review command."""

from __future__ import annotations

import desloppify.intelligence.narrative.core as narrative_mod
import desloppify.intelligence.review.prepare as review_mod

from desloppify.app.commands.helpers.query import write_query
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize

from .packet.build import (
    build_review_packet_payload,
    build_run_batches_next_command,
    resolve_review_packet_context,
)
from .runtime.setup import setup_lang_concrete


_ORIGINAL_COMPUTE_NARRATIVE = narrative_mod.compute_narrative
_ORIGINAL_NARRATIVE_CONTEXT = narrative_mod.NarrativeContext
_ORIGINAL_PREPARE_HOLISTIC_REVIEW = review_mod.prepare_holistic_review
_ORIGINAL_REVIEW_PREPARE_OPTIONS = review_mod.HolisticReviewPrepareOptions


def do_prepare(
    args,
    state,
    lang,
    _state_path,
    *,
    config: dict,
) -> None:
    """Prepare mode: holistic-only review packet in query.json."""
    context = resolve_review_packet_context(args)
    next_command = build_run_batches_next_command(context)

    # Keep prepare and external-start on one packet-construction contract.
    try:
        build_kwargs: dict[str, object] = {}
        if narrative_mod.compute_narrative is not _ORIGINAL_COMPUTE_NARRATIVE:
            build_kwargs["compute_narrative_fn"] = narrative_mod.compute_narrative
        if narrative_mod.NarrativeContext is not _ORIGINAL_NARRATIVE_CONTEXT:
            build_kwargs["narrative_context_cls"] = narrative_mod.NarrativeContext
        if review_mod.prepare_holistic_review is not _ORIGINAL_PREPARE_HOLISTIC_REVIEW:
            build_kwargs["prepare_holistic_review_fn"] = (
                review_mod.prepare_holistic_review
            )
        if (
            review_mod.HolisticReviewPrepareOptions
            is not _ORIGINAL_REVIEW_PREPARE_OPTIONS
        ):
            build_kwargs["review_prepare_options_cls"] = (
                review_mod.HolisticReviewPrepareOptions
            )
        data = build_review_packet_payload(
            state=state,
            lang=lang,
            config=config,
            context=context,
            next_command=next_command,
            setup_lang_fn=setup_lang_concrete,
            **build_kwargs,
        )
    except ValueError as exc:
        msg = str(exc).strip()
        if not msg:
            msg = f"no files found at path '{context.path}'. Nothing to review."
        scan_path = state.get("scan_path") if isinstance(state, dict) else None
        if scan_path:
            msg += (
                f"\nHint: your last scan used --path {scan_path}. "
                f"Try: desloppify review --prepare --path {scan_path}"
            )
        else:
            msg += "\nHint: pass --path <dir> matching the path used during scan."
        raise CommandError(msg, exit_code=1) from exc

    write_query(data)
    _print_prepare_summary(
        data,
        next_command=next_command,
        retrospective=context.retrospective,
    )


def _print_prepare_summary(
    data: dict,
    *,
    next_command: str,
    retrospective: bool,
) -> None:
    """Print the prepare summary to the terminal."""
    total = data.get("total_files", 0)
    batches = data.get("investigation_batches", [])
    print(colorize(f"\n  Holistic review prepared: {total} files in codebase", "bold"))
    if retrospective:
        print(
            colorize(
                "  Retrospective context enabled: historical review issues injected into packet.",
                "dim",
            )
        )
    if batches:
        print(
            colorize(
                "\n  Investigation batches (independent — can run in parallel):", "bold"
            )
        )
        for i, batch in enumerate(batches, 1):
            print(
                colorize(
                    f"    {i}. {batch['name']} — {batch['why']}",
                    "dim",
                )
            )
    print(colorize("\n  Workflow:", "bold"))
    for step_i, step in enumerate(data.get("workflow", []), 1):
        print(colorize(f"    {step_i}. {step}", "dim"))
    n_batches = len(data.get("investigation_batches", []))
    print(colorize("\n  AGENT PLAN — pick the path matching your runner:", "yellow"))
    print(
        colorize(
            "  1. Codex: `desloppify review --run-batches --runner codex --parallel --scan-after-import`",
            "dim",
        )
    )
    print(
        colorize(
            f"  2. Claude / other agent: `desloppify review --run-batches --dry-run`"
            f" → generates {n_batches} prompt files in .desloppify/subagent_runs/<run>/prompts/."
            f" Launch {n_batches} subagents in parallel (one per prompt),"
            " write output to the matching results/ file,"
            " then `desloppify review --import-run <run-dir> --scan-after-import`",
            "dim",
        )
    )
    print(
        colorize(
            "  3. Cloud/external: `desloppify review --external-start --external-runner claude` → follow template → `--external-submit`",
            "dim",
        )
    )
    print(
        colorize(
            "  4. Issues-only fallback: `desloppify review --import issues.json`",
            "dim",
        )
    )
    print(
        colorize(
            '  5. Emergency only: `--manual-override --attest "<why>"` (provisional; expires on next scan)',
            "dim",
        )
    )
    print(
        colorize(
            "\n  → query.json updated. Batches are pre-defined — do NOT regroup dimensions yourself.",
            "cyan",
        )
    )


__all__ = ["do_prepare"]
