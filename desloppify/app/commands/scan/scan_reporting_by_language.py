"""Per-language score reporting for mixed-language repositories."""

from __future__ import annotations

from desloppify.core.output_api import colorize


def _dimension_bar(score: float, *, bar_len: int = 15) -> str:
    """Render a compact fill bar for a score."""
    filled = round(score / 100 * bar_len)
    filled = max(0, min(bar_len, filled))
    if score >= 80:
        colour = "green"
    elif score >= 60:
        colour = "yellow"
    else:
        colour = "red"
    return colorize("█" * filled, colour) + colorize("░" * (bar_len - filled), "dim")


def _overall_from_dim_scores(dim_scores: dict) -> float | None:
    """Derive a simple unweighted average from dimension scores (fallback)."""
    values = [
        float(v.get("score", 0))
        for v in dim_scores.values()
        if isinstance(v, dict) and "score" in v
    ]
    return round(sum(values) / len(values), 1) if values else None


def show_per_language_score_blocks(
    state: dict,
    *,
    show_aggregate: bool = True,
) -> None:
    """Print per-language score blocks from ``state["dimension_scores_by_language"]``.

    Each language gets its own clearly-labelled block showing
    overall/objective/strict/verified scores and mechanical + subjective
    dimension breakdown.  The aggregate block is printed last when
    *show_aggregate* is True.
    """
    by_lang: dict[str, dict] = state.get("dimension_scores_by_language") or {}
    if not by_lang:
        print(
            colorize(
                "  No per-language scores found. Run `desloppify scan --by-language` first.",
                "yellow",
            )
        )
        return

    for lang_name, lang_dim_scores in sorted(by_lang.items()):
        if not isinstance(lang_dim_scores, dict):
            continue

        lang_scores = _compute_aggregate_scores_from_dims(lang_dim_scores)
        overall = lang_scores.get("overall", _overall_from_dim_scores(lang_dim_scores))
        objective = lang_scores.get("objective")
        strict = lang_scores.get("strict")
        verified = lang_scores.get("verified")

        _print_lang_block_header(lang_name)
        _print_lang_score_summary(overall, objective, strict, verified)
        _print_lang_dimension_rows(lang_dim_scores)
        print()

    if show_aggregate:
        _print_aggregate_reference(state)


def _compute_aggregate_scores_from_dims(dim_scores: dict) -> dict[str, float | None]:
    """Extract aggregate scores stored alongside dimension data (if present)."""
    agg = dim_scores.get("_aggregate_scores", {})
    if isinstance(agg, dict):
        return {
            "overall": agg.get("overall_score"),
            "objective": agg.get("objective_score"),
            "strict": agg.get("strict_score"),
            "verified": agg.get("verified_strict_score"),
        }
    return {}


def _print_lang_block_header(lang_name: str) -> None:
    header = f"  ── {lang_name.title()} ──"
    pad = 60 - len(header)
    print(colorize(header + "─" * max(0, pad), "bold"))


def _print_lang_score_summary(
    overall: float | None,
    objective: float | None,
    strict: float | None,
    verified: float | None,
) -> None:
    parts = []
    if overall is not None:
        parts.append(f"overall {overall:.1f}%")
    if objective is not None:
        parts.append(f"objective {objective:.1f}%")
    if strict is not None:
        parts.append(f"strict {strict:.1f}%")
    if verified is not None:
        parts.append(f"verified {verified:.1f}%")
    if parts:
        print(colorize("  " + "  |  ".join(parts), "cyan"))


def _print_lang_dimension_rows(dim_scores: dict) -> None:
    """Print one row per dimension for this language."""
    mech_rows = []
    subj_rows = []
    for name, data in dim_scores.items():
        if name.startswith("_"):
            continue
        if not isinstance(data, dict):
            continue
        score = float(data.get("score", 0.0))
        strict = float(data.get("strict", data.get("strict_score", score)))
        is_subj = "subjective_assessment" in data.get("detectors", {})
        row = (name, score, strict, is_subj)
        if is_subj:
            subj_rows.append(row)
        else:
            mech_rows.append(row)

    bar_len = 15
    for name, score, strict, _ in sorted(mech_rows, key=lambda r: r[1]):
        bar = _dimension_bar(score, bar_len=bar_len)
        print(
            f"  {name:<22} {bar} {score:5.1f}%  "
            + colorize(f"(strict {strict:5.1f}%)", "dim")
        )
    if subj_rows:
        print(colorize("  ── subjective ──", "dim"))
        for name, score, strict, _ in sorted(subj_rows, key=lambda r: r[1]):
            bar = _dimension_bar(score, bar_len=bar_len)
            print(
                f"  {name:<22} {bar} {score:5.1f}%  "
                + colorize(f"(strict {strict:5.1f}%)", "dim")
            )


def _print_aggregate_reference(state: dict) -> None:
    """Print the aggregate score as the final summary block."""
    overall = state.get("overall_score")
    strict = state.get("strict_score")
    objective = state.get("objective_score")
    verified = state.get("verified_strict_score")
    print(colorize("  ── Aggregate (all languages) ─────────────────────────────", "dim"))
    parts = []
    if overall is not None:
        parts.append(f"overall {float(overall):.1f}%")
    if objective is not None:
        parts.append(f"objective {float(objective):.1f}%")
    if strict is not None:
        parts.append(f"strict {float(strict):.1f}%")
    if verified is not None:
        parts.append(f"verified {float(verified):.1f}%")
    if parts:
        print(colorize("  " + "  |  ".join(parts), "cyan"))
    print()


__all__ = [
    "show_per_language_score_blocks",
]
