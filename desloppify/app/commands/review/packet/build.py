"""Shared holistic review packet construction and next-command helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.base.coercions import coerce_positive_int
from desloppify.engine._state.schema import StateModel
import desloppify.intelligence.narrative.core as narrative_mod
from desloppify.intelligence import review as review_mod

from ..helpers import parse_dimensions
from .policy import coerce_review_batch_file_limit


@dataclass(frozen=True)
class ReviewPacketContext:
    """Normalized review-packet CLI options shared across entrypoints."""

    path: Path
    dimensions: list[str] | None
    retrospective: bool
    retrospective_max_issues: int
    retrospective_max_batch_items: int


def resolve_review_packet_context(args: Any) -> ReviewPacketContext:
    """Parse shared packet options from CLI args."""
    dims = parse_dimensions(args)
    dimensions = list(dims) if dims else None
    retrospective = bool(getattr(args, "retrospective", False))
    retrospective_max_issues = coerce_positive_int(
        getattr(args, "retrospective_max_issues", None),
        default=30,
        minimum=1,
    )
    retrospective_max_batch_items = coerce_positive_int(
        getattr(args, "retrospective_max_batch_items", None),
        default=20,
        minimum=1,
    )
    return ReviewPacketContext(
        path=Path(getattr(args, "path", ".") or "."),
        dimensions=dimensions,
        retrospective=retrospective,
        retrospective_max_issues=retrospective_max_issues,
        retrospective_max_batch_items=retrospective_max_batch_items,
    )


def build_holistic_packet(
    *,
    state: StateModel,
    lang: Any,
    config: dict[str, Any],
    context: ReviewPacketContext,
    setup_lang_fn,
    prepare_holistic_review_fn=None,
) -> tuple[dict[str, Any], str]:
    """Build the canonical holistic review packet payload and lang name."""
    lang_run, found_files = setup_lang_fn(lang, context.path, config)
    lang_name = lang_run.name
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_name, command="review"),
    )
    prepare_fn = prepare_holistic_review_fn or review_mod.prepare_holistic_review
    packet = prepare_fn(
        context.path,
        lang_run,
        state,
        options=review_mod.HolisticReviewPrepareOptions(
            dimensions=context.dimensions,
            files=found_files or None,
            max_files_per_batch=coerce_review_batch_file_limit(config),
            include_issue_history=context.retrospective,
            issue_history_max_issues=context.retrospective_max_issues,
            issue_history_max_batch_items=context.retrospective_max_batch_items,
        ),
    )
    packet["narrative"] = narrative
    return packet, lang_name


def build_run_batches_next_command(context: ReviewPacketContext) -> str:
    """Return the canonical next command for local batch-based review."""
    parts: list[str] = [
        "desloppify",
        "review",
        "--run-batches",
        "--runner",
        "codex",
        "--parallel",
        "--scan-after-import",
    ]
    if context.dimensions:
        parts.extend(["--dimensions", ",".join(context.dimensions)])
    if context.retrospective:
        parts.extend(
            [
                "--retrospective",
                "--retrospective-max-issues",
                str(context.retrospective_max_issues),
                "--retrospective-max-batch-items",
                str(context.retrospective_max_batch_items),
            ]
        )
    return " ".join(parts)


def build_prepare_next_command(context: ReviewPacketContext) -> str:
    """Return the canonical next command for prepare-mode packet output."""
    parts: list[str] = ["desloppify", "review", "--prepare"]
    if context.retrospective:
        parts.extend(
            [
                "--retrospective",
                "--retrospective-max-issues",
                str(context.retrospective_max_issues),
                "--retrospective-max-batch-items",
                str(context.retrospective_max_batch_items),
            ]
        )
    return " ".join(parts)


def build_external_submit_next_command(context: ReviewPacketContext) -> str:
    """Return the canonical next command for external-session submit."""
    parts: list[str] = [
        "desloppify",
        "review",
        "--external-submit",
        "--session-id",
        "<id>",
        "--import",
        "<file>",
    ]
    if context.retrospective:
        parts.extend(
            [
                "--retrospective",
                "--retrospective-max-issues",
                str(context.retrospective_max_issues),
                "--retrospective-max-batch-items",
                str(context.retrospective_max_batch_items),
            ]
        )
    return " ".join(parts)


def require_non_empty_packet(packet: dict[str, Any], *, path: Path) -> int:
    """Return packet total_files, raising ValueError when no reviewable files exist."""
    total = packet.get("total_files", 0)
    if isinstance(total, bool) or not isinstance(total, int):
        raise ValueError(
            f"invalid review packet shape for path '{path}': total_files must be an integer"
        )
    if total <= 0:
        raise ValueError(f"no files found at path '{path}'. Nothing to review.")
    return total


__all__ = [
    "ReviewPacketContext",
    "build_external_submit_next_command",
    "build_holistic_packet",
    "build_prepare_next_command",
    "build_run_batches_next_command",
    "require_non_empty_packet",
    "resolve_review_packet_context",
]
