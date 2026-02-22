"""Output and import-format helpers for review command flows."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.review import import_cmd as review_import_mod
from desloppify.app.commands.review import import_helpers as import_helpers_mod
from desloppify.app.commands.scan import (
    scan_reporting_dimensions as reporting_dimensions_mod,
)
from desloppify.intelligence import integrity as subjective_integrity_mod
from desloppify.utils import colorize


def _subjective_at_target_dimensions(
    state_or_dim_scores: dict,
    dim_scores: dict | None = None,
    *,
    target: float,
) -> list[dict]:
    """Return scorecard-aligned subjective rows that sit on the target threshold."""
    return review_import_mod.subjective_at_target_dimensions(
        state_or_dim_scores,
        dim_scores,
        target=target,
        scorecard_subjective_entries_fn=reporting_dimensions_mod.scorecard_subjective_entries,
        matches_target_score_fn=subjective_integrity_mod.matches_target_score,
    )


def _load_import_findings_data(
    import_file: str,
    *,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> dict:
    """Load and normalize review import payload to object format."""
    return import_helpers_mod.load_import_findings_data(
        import_file,
        colorize_fn=colorize,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )


def _print_skipped_validation_details(diff: dict) -> None:
    """Print validation warnings for skipped imported findings."""
    import_helpers_mod.print_skipped_validation_details(diff, colorize_fn=colorize)


def _print_assessments_summary(state: dict) -> None:
    """Print holistic subjective assessment summary when present."""
    import_helpers_mod.print_assessments_summary(state, colorize_fn=colorize)


def _print_open_review_summary(state: dict) -> str:
    """Print current open review finding count and return next suggested command."""
    return import_helpers_mod.print_open_review_summary(state, colorize_fn=colorize)


def _print_review_import_scores_and_integrity(state: dict, config: dict) -> list[dict]:
    """Print score snapshot plus subjective integrity warnings."""
    return import_helpers_mod.print_review_import_scores_and_integrity(
        state,
        config,
        state_mod=state_mod,
        target_strict_score_from_config_fn=target_strict_score_from_config,
        subjective_at_target_fn=_subjective_at_target_dimensions,
        subjective_rerun_command_fn=reporting_dimensions_mod.subjective_rerun_command,
        colorize_fn=colorize,
    )
