"""Prepare flow for review command."""

from __future__ import annotations

import sys
from pathlib import Path

from desloppify.app.commands.helpers.query import write_query
from . import runtime as review_runtime_mod
from desloppify.core._internal.coercions import coerce_positive_int
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.core.output_api import colorize

from .helpers import parse_dimensions
from .packet_policy import coerce_review_batch_file_limit, redacted_review_config


def do_prepare(
    args,
    state,
    lang,
    _state_path,
    *,
    config: dict,
) -> None:
    """Prepare mode: holistic-only review packet in query.json."""
    path = Path(args.path)
    dims = parse_dimensions(args)
    dimensions = list(dims) if dims else None
    retrospective = bool(getattr(args, "retrospective", False))
    retrospective_max_issues = coerce_positive_int(
        getattr(args, "retrospective_max_issues", None),
        default=30,
    )
    retrospective_max_batch_items = coerce_positive_int(
        getattr(args, "retrospective_max_batch_items", None),
        default=20,
    )

    lang_run, found_files = review_runtime_mod.setup_lang_concrete(lang, path, config)

    lang_name = lang_run.name
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_name, command="review"),
    )
    data = review_mod.prepare_holistic_review(
        path,
        lang_run,
        state,
        options=review_mod.HolisticReviewPrepareOptions(
            dimensions=dimensions,
            files=found_files or None,
            max_files_per_batch=coerce_review_batch_file_limit(config),
            include_issue_history=retrospective,
            issue_history_max_issues=retrospective_max_issues,
            issue_history_max_batch_items=retrospective_max_batch_items,
        ),
    )
    next_command = (
        "desloppify review --run-batches --runner codex --parallel --scan-after-import"
    )
    if retrospective:
        next_command += (
            " --retrospective"
            f" --retrospective-max-issues {retrospective_max_issues}"
            f" --retrospective-max-batch-items {retrospective_max_batch_items}"
        )
    data["config"] = redacted_review_config(config)
    data["narrative"] = narrative
    data["next_command"] = next_command
    total = data.get("total_files", 0)
    if total == 0:
        print(
            colorize(
                f"\n  Error: no files found at path '{path}'. "
                "Nothing to review.",
                "red",
            ),
            file=sys.stderr,
        )
        scan_path = state.get("scan_path") if isinstance(state, dict) else None
        if scan_path:
            print(
                colorize(
                    f"  Hint: your last scan used --path {scan_path}. "
                    f"Try: desloppify review --prepare --path {scan_path}",
                    "yellow",
                ),
                file=sys.stderr,
            )
        else:
            print(
                colorize(
                    "  Hint: pass --path <dir> matching the path used during scan.",
                    "yellow",
                ),
                file=sys.stderr,
            )
        sys.exit(1)
    write_query(data)
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
            n_files = len(batch["files_to_read"])
            print(
                colorize(
                    f"    {i}. {batch['name']} ({n_files} files) — {batch['why']}",
                    "dim",
                )
            )
    print(colorize("\n  Workflow:", "bold"))
    for step_i, step in enumerate(data.get("workflow", []), 1):
        print(colorize(f"    {step_i}. {step}", "dim"))
    print(colorize("\n  AGENT PLAN:", "yellow"))
    print(
        colorize(
            f"  1. Preferred: `{next_command}`",
            "dim",
        )
    )
    print(
        colorize(
            "  2. Cloud/manual fallback: run external reviewers, merge to findings.json, then import",
            "dim",
        )
    )
    print(
        colorize(
            "  3. Claude cloud durable path: `desloppify review --external-start --external-runner claude` then run the printed `--external-submit` command",
            "dim",
        )
    )
    print(
        colorize(
            "  4. Findings-only fallback: `desloppify review --import findings.json`",
            "dim",
        )
    )
    print(
        colorize(
            "  5. Emergency only: `--manual-override --attest \"<why>\"` (provisional; expires on next scan)",
            "dim",
        )
    )
    print(
        colorize(
            "  Next command to improve subjective scores: "
            f"`{next_command}`",
            "dim",
        )
    )
    print(
        colorize(
            "\n  → query.json updated. "
            f"Preferred next step: {next_command}",
            "cyan",
        )
    )


__all__ = ["do_prepare"]
