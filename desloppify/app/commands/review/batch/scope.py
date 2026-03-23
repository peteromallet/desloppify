"""Scope, coverage, and packet-shape helpers for review batch execution."""

from __future__ import annotations

import shlex
import sys

from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.feedback_contract import (
    LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY,
    REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY,
    TRUSTED_IMPORT_COVERAGE_OVERRIDE_FLAG,
)


_SUPPORTED_RUNNERS = {"codex", "opencode"}
_DEFAULT_RUNNER = "codex"


def validate_runner(runner: str, *, colorize_fn) -> None:
    """Validate review batch runner."""
    if runner in _SUPPORTED_RUNNERS:
        return
    supported = ", ".join(sorted(_SUPPORTED_RUNNERS))
    raise CommandError(
        f"Error: unsupported runner '{runner}' (supported: {supported})", exit_code=2
    )


def require_batches(
    packet: dict,
    *,
    colorize_fn,
    suggested_prepare_cmd: str | None = None,
) -> list[dict]:
    """Return investigation batches or exit with a clear error."""
    batches = packet.get("investigation_batches", [])
    if isinstance(batches, list) and batches:
        return batches
    if isinstance(suggested_prepare_cmd, str) and suggested_prepare_cmd.strip():
        print(
            colorize_fn(
                f"  Regenerate review context first: `{suggested_prepare_cmd}`",
                "yellow",
            ),
            file=sys.stderr,
        )
    print(
        colorize_fn(
            "  Then follow your runner's review workflow —"
            " e.g. `desloppify review --run-batches --runner codex --parallel --scan-after-import`"
            " (swap `codex` for `opencode` if preferred).",
            "dim",
        ),
        file=sys.stderr,
    )
    raise PacketValidationError(
        "Error: packet has no investigation_batches.", exit_code=1
    )


def print_review_quality(quality: object, *, colorize_fn) -> None:
    """Render merged review quality summary when present."""
    if not isinstance(quality, dict):
        return
    coverage = quality.get("dimension_coverage")
    density = quality.get("evidence_density")
    high_missing_issue_note = quality.get(REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY)
    if not isinstance(high_missing_issue_note, int | float):
        high_missing_issue_note = quality.get(
            LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY
        )
    if not isinstance(coverage, int | float) or not isinstance(density, int | float):
        return
    print(
        colorize_fn(
            "  Review quality: "
            f"dimension coverage {float(coverage):.2f}, "
            f"evidence density {float(density):.2f}, "
            f"high-score-missing-issue-note {int(high_missing_issue_note or 0)}"
            "",
            "dim",
        )
    )


def collect_reviewed_files_from_batches(
    *,
    batches: list[dict[str, object]],
    selected_indexes: list[int],
) -> list[str]:
    """Collect normalized file paths reviewed in the selected batch set.

    Returns empty — reviewer agents explore the codebase freely rather than
    being constrained to seed files.
    """
    del batches, selected_indexes
    return []


def normalize_dimension_list(raw: object) -> list[str]:
    """Normalize dimension collections to a stable, de-duplicated list."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        dim = item.strip()
        if not dim or dim in seen:
            continue
        seen.add(dim)
        out.append(dim)
    return out


def scored_dimensions_for_lang(lang_name: str) -> list[str]:
    """Return default scored subjective dimensions for one language."""
    try:
        default_dims, _, _ = load_dimensions_for_lang(lang_name)
    except (ValueError, RuntimeError):
        return []
    return normalize_dimension_list(default_dims)


def missing_scored_dimensions(
    *,
    selected_dims: list[str],
    scored_dims: list[str],
) -> list[str]:
    selected = set(selected_dims)
    return [dim for dim in scored_dims if dim not in selected]


def missing_dimensions_command(*, missing_dims: list[str], scan_path: str) -> str:
    """Return rerun command for missing subjective dimensions."""
    base = (
        f"desloppify review --run-batches --runner {_DEFAULT_RUNNER}"
        " --parallel --scan-after-import"
    )
    if scan_path and scan_path != ".":
        base += f" --path {shlex.quote(scan_path)}"
    if missing_dims:
        base += f" --dimensions {','.join(missing_dims)}"
    return base


def print_preflight_dimension_scope_notice(
    *,
    selected_dims: list[str],
    scored_dims: list[str],
    explicit_selection: bool,
    scan_path: str,
    colorize_fn,
) -> None:
    """Print trigger-time notice when run scope is a scored-dimension subset."""
    if not scored_dims:
        return
    missing_dims = missing_scored_dimensions(
        selected_dims=selected_dims,
        scored_dims=scored_dims,
    )
    if not missing_dims:
        return

    covered_count = len([dim for dim in selected_dims if dim in set(scored_dims)])
    scope_reason = (
        "explicit --dimensions selection"
        if explicit_selection
        else "language default review dimension set"
    )
    tone = "yellow" if explicit_selection else "red"
    print(
        colorize_fn(
            "  WARNING: this run targets "
            f"{covered_count}/{len(scored_dims)} scored subjective dimensions "
            f"({scope_reason}).",
            tone,
        )
    )
    preview = ", ".join(missing_dims[:5])
    if len(missing_dims) > 5:
        preview = f"{preview}, +{len(missing_dims) - 5} more"
    print(colorize_fn(f"  Missing from this run: {preview}", "yellow"))
    print(
        colorize_fn(
            "  Rerun missing dimensions: "
            f"`{missing_dimensions_command(missing_dims=missing_dims, scan_path=scan_path)}`",
            "dim",
        )
    )


def print_import_dimension_coverage_notice(
    *,
    assessed_dims: list[str],
    scored_dims: list[str],
    scan_path: str,
    colorize_fn,
) -> list[str]:
    """Print result-time notice when merged import covers only a subset."""
    if not scored_dims:
        return []
    missing_dims = missing_scored_dimensions(
        selected_dims=assessed_dims,
        scored_dims=scored_dims,
    )
    if not missing_dims:
        return []

    covered_count = len([dim for dim in assessed_dims if dim in set(scored_dims)])
    print(
        colorize_fn(
            "  Coverage gap: imported assessments for "
            f"{covered_count}/{len(scored_dims)} scored subjective dimensions.",
            "yellow",
        )
    )
    preview = ", ".join(missing_dims[:5])
    if len(missing_dims) > 5:
        preview = f"{preview}, +{len(missing_dims) - 5} more"
    print(colorize_fn(f"  Still missing: {preview}", "yellow"))
    print(
        colorize_fn(
            "  Run to cover missing dimensions: "
            f"`{missing_dimensions_command(missing_dims=missing_dims, scan_path=scan_path)}`",
            "dim",
        )
    )
    return missing_dims


def enforce_trusted_import_coverage_gate(
    *,
    missing_dims: list[str],
    selected_dims: list[str],
    allow_partial: bool,
    scan_path: str,
    colorize_fn,
) -> None:
    """Block trusted assessment import when selected assessment dimensions are missing."""
    if not selected_dims or not missing_dims:
        return
    if allow_partial:
        print(
            colorize_fn(
                "  Coverage override: importing with missing scored dimensions "
                f"because {TRUSTED_IMPORT_COVERAGE_OVERRIDE_FLAG} is enabled.",
                "yellow",
            )
        )
        return

    preview = ", ".join(missing_dims[:5])
    if len(missing_dims) > 5:
        preview = f"{preview}, +{len(missing_dims) - 5} more"
    print(colorize_fn(f"  Missing dimensions: {preview}", "yellow"), file=sys.stderr)
    print(
        colorize_fn(
            "  Retry with full coverage or explicitly bypass with "
            f"{TRUSTED_IMPORT_COVERAGE_OVERRIDE_FLAG}.",
            "yellow",
        ),
        file=sys.stderr,
    )
    print(
        colorize_fn(
            "  Suggested rerun: "
            f"`{missing_dimensions_command(missing_dims=missing_dims, scan_path=scan_path)}`",
            "dim",
        ),
        file=sys.stderr,
    )
    raise CommandError(
        "Error: trusted assessment import blocked due to incomplete selected-dimension coverage.",
        exit_code=1,
    )


__all__ = [
    "_DEFAULT_RUNNER",
    "_SUPPORTED_RUNNERS",
    "collect_reviewed_files_from_batches",
    "enforce_trusted_import_coverage_gate",
    "missing_dimensions_command",
    "missing_scored_dimensions",
    "normalize_dimension_list",
    "print_import_dimension_coverage_notice",
    "print_preflight_dimension_scope_notice",
    "print_review_quality",
    "require_batches",
    "scored_dimensions_for_lang",
    "validate_runner",
]
