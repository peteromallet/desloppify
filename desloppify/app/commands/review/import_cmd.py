"""Import flow helpers for review command."""

from __future__ import annotations

from desloppify.intelligence.narrative.core import NarrativeContext


def subjective_at_target_dimensions(
    state_or_dim_scores: dict,
    dim_scores: dict | None = None,
    *,
    target: float,
    scorecard_subjective_entries_fn,
    matches_target_score_fn,
) -> list[dict]:
    """Return scorecard-aligned subjective rows that sit on the target threshold."""
    state = state_or_dim_scores
    if dim_scores is None:
        dim_scores = state_or_dim_scores
        state = {"dimension_scores": dim_scores}

    rows: list[dict] = []
    for entry in scorecard_subjective_entries_fn(state, dim_scores=dim_scores):
        if entry.get("placeholder"):
            continue
        strict_val = float(entry.get("strict", entry.get("score", 100.0)))
        if matches_target_score_fn(strict_val, target):
            rows.append(
                {
                    "name": str(entry.get("name", "Subjective")),
                    "score": strict_val,
                    "cli_keys": list(entry.get("cli_keys", [])),
                }
            )
    rows.sort(key=lambda item: item["name"].lower())
    return rows


def do_import(
    import_file,
    state,
    lang,
    sp,
    *,
    holistic: bool,
    config: dict | None,
    load_import_findings_data_fn,
    import_holistic_findings_fn,
    save_state_fn,
    compute_narrative_fn,
    print_skipped_validation_details_fn,
    print_assessments_summary_fn,
    print_open_review_summary_fn,
    print_review_import_scores_and_integrity_fn,
    write_query_fn,
    colorize_fn,
    log_fn,
) -> None:
    """Import mode: ingest agent-produced findings."""
    findings_data = load_import_findings_data_fn(import_file)

    if not holistic:
        log_fn("  Per-file review mode is deprecated; importing as holistic review data.")
    diff = import_holistic_findings_fn(findings_data, state, lang.name)
    label = "Holistic review"

    save_state_fn(state, sp)

    lang_name = lang.name
    narrative = compute_narrative_fn(state, NarrativeContext(lang=lang_name, command="review"))

    print(colorize_fn(f"\n  {label} imported:", "bold"))
    print(
        colorize_fn(
            f"  +{diff['new']} new findings, "
            f"{diff['auto_resolved']} resolved, "
            f"{diff['reopened']} reopened",
            "dim",
        )
    )
    print_skipped_validation_details_fn(diff)
    print_assessments_summary_fn(state)
    next_command = print_open_review_summary_fn(state)
    at_target = print_review_import_scores_and_integrity_fn(state, config or {})

    print(
        colorize_fn(
            f"  Next command to improve subjective scores: `{next_command}`", "dim"
        )
    )
    write_query_fn(
        {
            "command": "review",
            "action": "import",
            "mode": "holistic",
            "diff": diff,
            "next_command": next_command,
            "subjective_at_target": [
                {"dimension": entry["name"], "score": entry["score"]}
                for entry in at_target
            ],
            "narrative": narrative,
        }
    )


__all__ = ["do_import", "subjective_at_target_dimensions"]
