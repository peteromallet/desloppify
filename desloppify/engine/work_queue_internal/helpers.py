"""Helper utilities for work queue item construction."""

from __future__ import annotations

import importlib
import re
from fnmatch import fnmatch

ALL_STATUSES = {"open", "fixed", "wontfix", "false_positive", "auto_resolved", "all"}
ATTEST_EXAMPLE = (
    "I have actually improved [WHAT YOU IMPROVED EXPLICITLY] enough "
    "to honestly justify a score of [SCORE], and I am not gaming the score."
)


def status_matches(item_status: str, status_filter: str) -> bool:
    return status_filter == "all" or item_status == status_filter


def is_subjective_finding(item: dict) -> bool:
    detector = item.get("detector")
    if detector in {"subjective_assessment"}:
        return True
    if detector == "holistic_review":
        return True
    return False


def is_review_finding(item: dict) -> bool:
    return item.get("detector") == "review"


def review_finding_weight(item: dict) -> float:
    """Return review issue weight aligned with issues list ordering."""
    confidence = str(item.get("confidence", "low")).lower()
    weight_by_confidence = {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.3,
    }
    weight = weight_by_confidence.get(confidence, 0.3)
    if item.get("detail", {}).get("holistic"):
        weight *= 10.0
    return float(weight)


def scope_matches(item: dict, scope: str | None) -> bool:
    """Apply show-style pattern matching against a queue item."""
    if not scope:
        return True

    item_id = item.get("id", "")
    detector = item.get("detector", "")
    filepath = item.get("file", "")
    summary = item.get("summary", "")
    dimension = item.get("detail", {}).get("dimension_name", "")
    kind = item.get("kind", "")

    if "*" in scope:
        return any(
            fnmatch(candidate, scope)
            for candidate in (item_id, filepath, detector, dimension, summary)
        )

    if "::" in scope:
        return item_id.startswith(scope)

    lowered = scope.lower()
    if kind == "subjective_dimension":
        return (
            lowered in item_id.lower()
            or lowered in dimension.lower()
            or lowered in summary.lower()
        )

    return (
        detector == scope
        or filepath == scope
        or filepath.startswith(scope.rstrip("/") + "/")
    )


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


def _canonical_subjective_dimension_key(display_name: str) -> str:
    """Map a display label (e.g. 'Mid Elegance') to its canonical dimension key."""
    cleaned = display_name.replace(" (subjective)", "").strip()
    target = cleaned.lower()
    scoring_mod = importlib.import_module("desloppify.scoring")

    for dim_key, label in scoring_mod.DISPLAY_NAMES.items():
        if str(label).lower() == target:
            return str(dim_key)
    return slugify(cleaned)


def _subjective_dimension_aliases(display_name: str) -> set[str]:
    """Return normalized aliases used to match display labels with finding dimension keys."""
    cleaned = display_name.replace(" (subjective)", "").strip()
    canonical = _canonical_subjective_dimension_key(cleaned)
    return {
        cleaned.lower(),
        cleaned.replace(" ", "_").lower(),
        slugify(cleaned),
        canonical.lower(),
        slugify(canonical),
    }


def supported_fixers_for_item(state: dict, item: dict) -> set[str] | None:
    """Return supported fixers for an item's language when known."""
    lang = str(item.get("lang", "") or "").strip()
    if not lang:
        return None

    caps = state.get("lang_capabilities", {})
    if not isinstance(caps, dict):
        return None

    lang_caps = caps.get(lang, {})
    if not isinstance(lang_caps, dict):
        return None

    fixers = lang_caps.get("fixers")
    if not isinstance(fixers, list):
        return None
    return {fixer for fixer in fixers if isinstance(fixer, str)}


def primary_command_for_finding(
    item: dict, *, supported_fixers: set[str] | None = None
) -> str:
    registry_mod = importlib.import_module("desloppify.core.registry")
    subjective_integrity_mod = importlib.import_module(
        "desloppify.intelligence.integrity.review"
    )

    detector = item.get("detector", "")
    meta = registry_mod.DETECTORS.get(detector)
    if meta and meta.action_type == "auto_fix" and meta.fixers:
        available_fixers = [
            fixer
            for fixer in meta.fixers
            if supported_fixers is None or fixer in supported_fixers
        ]
        if available_fixers:
            return f"desloppify fix {available_fixers[0]} --dry-run"
    if detector == "review":
        return "desloppify issues"
    if detector == "subjective_review":
        if subjective_integrity_mod.is_holistic_subjective_finding(item):
            return "desloppify review --prepare --holistic --refresh"
        return "desloppify show subjective_review --status open"
    return f'desloppify resolve fixed "{item.get("id", "")}" --note "<what you did>" --attest "{ATTEST_EXAMPLE}"'


def subjective_strict_scores(state: dict) -> dict[str, float]:
    dim_scores = state.get("dimension_scores", {}) or {}
    if not dim_scores:
        return {}

    scorecard_projection_mod = importlib.import_module(
        "desloppify.app.output.scorecard_parts.projection"
    )
    entries = scorecard_projection_mod.scorecard_subjective_entries(
        state, dim_scores=dim_scores
    )
    scores: dict[str, float] = {}
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        strict_val = float(entry.get("strict", entry.get("score", 100.0)))
        dim_key = _canonical_subjective_dimension_key(name)
        aliases = _subjective_dimension_aliases(name)
        for cli_key in entry.get("cli_keys", []):
            key = str(cli_key).strip().lower()
            if not key:
                continue
            aliases.add(key)
            aliases.add(slugify(key))
        aliases.add(dim_key.lower())
        aliases.add(slugify(dim_key))
        for alias in aliases:
            scores[alias] = strict_val
    return scores


def build_subjective_items(
    state: dict, findings: dict, *, threshold: float = 100.0
) -> list[dict]:
    """Create synthetic subjective work items (always tier 4)."""
    dim_scores = state.get("dimension_scores", {}) or {}
    if not dim_scores:
        return []
    threshold = max(0.0, min(100.0, float(threshold)))

    scorecard_projection_mod = importlib.import_module(
        "desloppify.app.output.scorecard_parts.projection"
    )
    subjective_integrity_mod = importlib.import_module(
        "desloppify.intelligence.integrity.review"
    )

    subjective_entries = scorecard_projection_mod.scorecard_subjective_entries(
        state, dim_scores=dim_scores
    )
    if not subjective_entries:
        return []
    unassessed_dims = {
        str(name).strip()
        for name in subjective_integrity_mod.unassessed_subjective_dimensions(
            dim_scores
        )
    }

    # Review findings are keyed by raw dimension name (snake_case).
    review_open_by_dim: dict[str, int] = {}
    for finding in findings.values():
        if finding.get("status") != "open" or finding.get("detector") != "review":
            continue
        dim_key = str(finding.get("detail", {}).get("dimension", "")).strip().lower()
        if not dim_key:
            continue
        review_open_by_dim[dim_key] = review_open_by_dim.get(dim_key, 0) + 1

    items: list[dict] = []
    for entry in subjective_entries:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        strict_val = float(entry.get("strict", entry.get("score", 100.0)))
        if strict_val >= threshold:
            continue

        dim_key = _canonical_subjective_dimension_key(name)
        aliases = set(_subjective_dimension_aliases(name))
        cli_keys = [
            str(key).strip().lower()
            for key in entry.get("cli_keys", [])
            if str(key).strip()
        ]
        aliases.update(cli_keys)
        aliases.update(slugify(key) for key in cli_keys)
        open_review = sum(review_open_by_dim.get(alias, 0) for alias in aliases)
        is_unassessed = bool(entry.get("placeholder")) or (
            name in unassessed_dims
            or (strict_val <= 0.0 and int(entry.get("issues", 0)) == 0)
        )
        if is_unassessed:
            primary_command = "desloppify review --prepare --holistic --refresh"
        else:
            if open_review > 0:
                primary_command = "desloppify issues"
            elif cli_keys:
                primary_command = (
                    "desloppify review --prepare --dimensions " + ",".join(cli_keys)
                )
            else:
                primary_command = "desloppify review --prepare"
        summary = f"Subjective dimension below target: {name} ({strict_val:.1f}%)"
        items.append(
            {
                "id": f"subjective::{slugify(dim_key)}",
                "detector": "subjective_assessment",
                "file": ".",
                "tier": 4,
                "effective_tier": 4,
                "confidence": "medium",
                "summary": summary,
                "detail": {
                    "dimension_name": name,
                    "dimension": dim_key,
                    "issues": int(entry.get("issues", 0)),
                    "strict_score": strict_val,
                    "open_review_findings": open_review,
                    "cli_keys": cli_keys,
                },
                "status": "open",
                "kind": "subjective_dimension",
                "primary_command": primary_command,
            }
        )
    return items


__all__ = [
    "ALL_STATUSES",
    "ATTEST_EXAMPLE",
    "build_subjective_items",
    "is_review_finding",
    "is_subjective_finding",
    "primary_command_for_finding",
    "review_finding_weight",
    "scope_matches",
    "slugify",
    "status_matches",
    "subjective_strict_scores",
    "supported_fixers_for_item",
]
