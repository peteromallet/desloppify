"""Dimension projection policy for scorecard rendering."""

from __future__ import annotations

from desloppify.app.output.scorecard_parts.dimension_policy import (
    _DEFAULT_ELEGANCE_COMPONENTS,
    _ELEGANCE_COMPONENTS_BY_LANG,
    _SUBJECTIVE_SCORECARD_ORDER_BY_LANG,
    _SUBJECTIVE_SCORECARD_ORDER_DEFAULT,
)
from desloppify.app.output.scorecard_parts.dimension_policy import (
    _SCORECARD_MAX_DIMENSIONS as SCORECARD_MAX_DIMENSIONS,
)


def resolve_scorecard_lang(state: dict) -> str | None:
    """Best-effort current scan language key for scorecard display policy."""
    history = state.get("scan_history")
    if isinstance(history, list):
        for entry in reversed(history):
            if not isinstance(entry, dict):
                continue
            lang = entry.get("lang")
            if isinstance(lang, str) and lang.strip():
                return lang.strip().lower()

    capabilities = state.get("lang_capabilities")
    if isinstance(capabilities, dict) and len(capabilities) == 1:
        only_lang = next(iter(capabilities.keys()))
        if isinstance(only_lang, str) and only_lang.strip():
            return only_lang.strip().lower()

    findings = state.get("findings")
    if isinstance(findings, dict):
        counts: dict[str, int] = {}
        for finding in findings.values():
            if not isinstance(finding, dict):
                continue
            lang = finding.get("lang")
            if isinstance(lang, str) and lang.strip():
                key = lang.strip().lower()
                counts[key] = counts.get(key, 0) + 1
        if counts:
            return max(counts, key=counts.get)
    return None


def is_unassessed_subjective_placeholder(data: dict) -> bool:
    return (
        "subjective_assessment" in data.get("detectors", {})
        and data.get("score", 0) == 0
        and data.get("issues", 0) == 0
    )


def collapse_elegance_dimensions(
    active_dims: list[tuple[str, dict]],
    *,
    lang_key: str | None,
) -> list[tuple[str, dict]]:
    """Collapse High/Mid/Low elegance rows into one aggregate display row."""
    component_names = set(
        _ELEGANCE_COMPONENTS_BY_LANG.get(lang_key or "", _DEFAULT_ELEGANCE_COMPONENTS)
    )
    elegance_rows = [
        (name, data) for name, data in active_dims if name in component_names
    ]
    if not elegance_rows:
        return active_dims

    remaining_rows = [
        (name, data) for name, data in active_dims if name not in component_names
    ]
    count = len(elegance_rows)
    score_avg = round(
        sum(float(data.get("score", 100.0)) for _, data in elegance_rows) / count, 1
    )
    strict_avg = round(
        sum(
            float(data.get("strict", data.get("score", 100.0)))
            for _, data in elegance_rows
        )
        / count,
        1,
    )
    checks_total = sum(int(data.get("checks", 0)) for _, data in elegance_rows)
    issues_total = sum(int(data.get("issues", 0)) for _, data in elegance_rows)
    tier = max(int(data.get("tier", 4)) for _, data in elegance_rows)
    placeholder_flags = [
        bool(
            data.get("detectors", {})
            .get("subjective_assessment", {})
            .get("placeholder")
        )
        for _, data in elegance_rows
    ]

    label = "Elegance"
    if any(name.lower() == label.lower() for name, _ in remaining_rows):
        label = "Elegance (combined)"

    pass_rate = round(score_avg / 100.0, 4)
    return [
        *remaining_rows,
        (
            label,
            {
                "score": score_avg,
                "strict": strict_avg,
                "checks": checks_total,
                "issues": issues_total,
                "tier": tier,
                "detectors": {
                    "subjective_assessment": {
                        "potential": checks_total,
                        "pass_rate": pass_rate,
                        "issues": issues_total,
                        "weighted_failures": round(checks_total * (1 - pass_rate), 4),
                        "components": [name for name, _ in elegance_rows],
                        "placeholder": any(placeholder_flags),
                    }
                },
            },
        ),
    ]


def limit_scorecard_dimensions(
    active_dims: list[tuple[str, dict]],
    *,
    lang_key: str | None,
    max_rows: int = SCORECARD_MAX_DIMENSIONS,
) -> list[tuple[str, dict]]:
    """Limit scorecard rows with language-specific subjective priority."""
    if len(active_dims) <= max_rows:
        return active_dims

    mechanical = [
        (name, data)
        for name, data in active_dims
        if "subjective_assessment" not in data.get("detectors", {})
    ]
    subjective = [
        (name, data)
        for name, data in active_dims
        if "subjective_assessment" in data.get("detectors", {})
    ]
    if len(mechanical) >= max_rows:
        return mechanical[:max_rows]

    budget = max_rows - len(mechanical)
    preferred_order = _SUBJECTIVE_SCORECARD_ORDER_BY_LANG.get(
        lang_key or "",
        _SUBJECTIVE_SCORECARD_ORDER_DEFAULT,
    )

    remaining = {name: (name, data) for name, data in subjective}
    selected: list[tuple[str, dict]] = []
    for name in preferred_order:
        row = remaining.pop(name, None)
        if row is None:
            continue
        selected.append(row)
        if len(selected) >= budget:
            break

    if len(selected) < budget and remaining:
        extras = sorted(
            remaining.values(),
            key=lambda item: (
                float(item[1].get("strict", item[1].get("score", 100.0))),
                item[0],
            ),
        )
        selected.extend(extras[: budget - len(selected)])

    return [*mechanical, *selected]


def prepare_scorecard_dimensions(state: dict) -> list[tuple[str, dict]]:
    """Prepare scorecard rows (active, elegance-collapsed, capped).

    Dimensions are derived dynamically from what the scoring engine produced
    in ``dimension_scores`` — no per-language hard-coded dimension list.
    Unassessed subjective placeholders (score 0, no issues) are excluded so
    the scorecard only shows dimensions that have real data.
    """
    dim_scores = state.get("dimension_scores", {})
    if not isinstance(dim_scores, dict):
        return []

    all_dims = [
        (name, data) for name, data in dim_scores.items() if isinstance(data, dict)
    ]

    lang_key = resolve_scorecard_lang(state)
    all_dims = collapse_elegance_dimensions(all_dims, lang_key=lang_key)

    # Show dimensions with real data; skip unassessed subjective placeholders.
    active_dims = [
        (name, data)
        for name, data in all_dims
        if data.get("checks", 0) > 0 and not is_unassessed_subjective_placeholder(data)
    ]
    active_dims = limit_scorecard_dimensions(active_dims, lang_key=lang_key)
    active_dims.sort(key=lambda x: (0 if x[0] == "File health" else 1, x[0]))
    return active_dims


__all__ = [
    "SCORECARD_MAX_DIMENSIONS",
    "collapse_elegance_dimensions",
    "prepare_scorecard_dimensions",
    "limit_scorecard_dimensions",
    "resolve_scorecard_lang",
]
