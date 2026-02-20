"""Prepare flow for review command."""

from __future__ import annotations

import sys
from pathlib import Path


def _redacted_review_config(config: dict | None) -> dict:
    """Return review packet config with target score removed for blind assessment."""
    if not isinstance(config, dict):
        return {}
    return {key: value for key, value in config.items() if key != "target_strict_score"}


def do_prepare(
    args,
    state,
    lang,
    _state_path,
    *,
    config: dict,
    holistic: bool,
    setup_lang_fn,
    narrative_mod,
    review_mod,
    write_query_fn,
    colorize_fn,
    log_fn,
) -> None:
    """Prepare mode: holistic-only review packet in query.json."""
    if not holistic:
        log_fn("  Per-file review mode is deprecated; preparing holistic packet.")

    path = Path(args.path)
    dims_str = getattr(args, "dimensions", None)
    dimensions = dims_str.split(",") if dims_str else None

    lang_run, found_files = setup_lang_fn(lang, path, config)

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
        ),
    )
    data["config"] = _redacted_review_config(config)
    data["narrative"] = narrative
    data["next_command"] = "desloppify review --import findings.json"
    total = data.get("total_files", 0)
    if total == 0:
        print(
            colorize_fn(
                f"\n  Error: no files found at path '{path}'. "
                "Nothing to review.",
                "red",
            ),
            file=sys.stderr,
        )
        scan_path = state.get("scan_path") if isinstance(state, dict) else None
        if scan_path:
            print(
                colorize_fn(
                    f"  Hint: your last scan used --path {scan_path}. "
                    f"Try: desloppify review --prepare --path {scan_path}",
                    "yellow",
                ),
                file=sys.stderr,
            )
        else:
            print(
                colorize_fn(
                    "  Hint: pass --path <dir> matching the path used during scan.",
                    "yellow",
                ),
                file=sys.stderr,
            )
        sys.exit(1)
    write_query_fn(data)
    batches = data.get("investigation_batches", [])
    print(colorize_fn(f"\n  Holistic review prepared: {total} files in codebase", "bold"))
    if batches:
        print(
            colorize_fn(
                "\n  Investigation batches (independent — can run in parallel):", "bold"
            )
        )
        for i, batch in enumerate(batches, 1):
            n_files = len(batch["files_to_read"])
            print(
                colorize_fn(
                    f"    {i}. {batch['name']} ({n_files} files) — {batch['why']}",
                    "dim",
                )
            )
    print(colorize_fn("\n  Workflow:", "bold"))
    for step_i, step in enumerate(data.get("workflow", []), 1):
        print(colorize_fn(f"    {step_i}. {step}", "dim"))
    print(colorize_fn("\n  AGENT PLAN:", "yellow"))
    print(
        colorize_fn(
            "  1. Run each investigation batch independently (parallel-friendly)", "dim"
        )
    )
    print(colorize_fn("  2. Capture findings in findings.json", "dim"))
    print(colorize_fn("  3. Import and rescan", "dim"))
    print(
        colorize_fn(
            "  Next command to improve subjective scores: `desloppify review --import findings.json`",
            "dim",
        )
    )
    print(
        colorize_fn(
            "\n  → query.json updated. "
            "Review codebase, then: desloppify review --import findings.json",
            "cyan",
        )
    )


__all__ = ["do_prepare"]
