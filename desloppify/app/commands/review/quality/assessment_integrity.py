"""Shared subjective-assessment integrity helpers for review import flows."""

from __future__ import annotations

from collections.abc import Callable


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


def bind_scorecard_subjective_at_target(
    *,
    scorecard_subjective_entries_fn=None,
    reporting_dimensions_mod=None,
    subjective_integrity_mod,
) -> Callable[..., list[dict]]:
    """Bind scorecard-specific dependencies once for import/output call sites.

    ``reporting_dimensions_mod`` is kept for compatibility; new callers should
    pass ``scorecard_subjective_entries_fn`` explicitly.
    """
    if scorecard_subjective_entries_fn is None and reporting_dimensions_mod is not None:
        scorecard_subjective_entries_fn = (
            reporting_dimensions_mod.scorecard_subjective_entries
        )
    if not callable(scorecard_subjective_entries_fn):
        raise ValueError("scorecard_subjective_entries_fn must be callable")

    def bound(
        state_or_dim_scores: dict[str, object],
        dim_scores: dict[str, object] | None = None,
        *,
        target: float,
    ) -> list[dict]:
        return subjective_at_target_dimensions(
            state_or_dim_scores,
            dim_scores,
            target=target,
            scorecard_subjective_entries_fn=scorecard_subjective_entries_fn,
            matches_target_score_fn=subjective_integrity_mod.matches_target_score,
        )

    return bound


__all__ = [
    "bind_scorecard_subjective_at_target",
    "subjective_at_target_dimensions",
]
