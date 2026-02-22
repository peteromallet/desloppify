"""Centralized dimension-policy helpers for review workflows."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.intelligence.review.dimensions import (
    DIMENSION_PROMPTS,
    is_custom_dimension,
    is_known_dimension,
    normalize_dimension_name,
)


@dataclass(frozen=True)
class DimensionPolicy:
    """Resolved review-dimension policy for one command execution."""

    allow_custom: bool
    known: frozenset[str]
    allowed_custom: frozenset[str]

    # Backward-compat properties
    @property
    def known_per_file(self) -> frozenset[str]:
        return self.known

    @property
    def known_holistic(self) -> frozenset[str]:
        return self.known

    @property
    def allowed_subjective(self) -> frozenset[str]:
        return self.known | self.allowed_custom


def _normalized_custom_allowlist(raw_values: list[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in raw_values or []:
        canonical = normalize_dimension_name(str(raw))
        if canonical and is_custom_dimension(canonical):
            out.add(canonical)
    return out


def build_dimension_policy(
    *,
    state: dict | None = None,
    config: dict | None = None,
    allow_custom_dimensions: bool = False,
) -> DimensionPolicy:
    """Build a normalized dimension policy from config/state/CLI overrides."""
    cfg = config if isinstance(config, dict) else {}
    st = state if isinstance(state, dict) else {}

    known = frozenset(normalize_dimension_name(name) for name in DIMENSION_PROMPTS)

    configured_custom = _normalized_custom_allowlist(cfg.get("review_custom_dimensions"))
    discovered_custom = _normalized_custom_allowlist(st.get("custom_review_dimensions"))
    allowed_custom = frozenset(configured_custom | discovered_custom)

    allow_custom = bool(allow_custom_dimensions) or bool(cfg.get("review_allow_custom_dimensions", False))

    return DimensionPolicy(
        allow_custom=allow_custom,
        known=known,
        allowed_custom=allowed_custom,
    )


def is_allowed_dimension(name: str, *, holistic: bool | None = None, policy: DimensionPolicy) -> bool:
    """Check whether a normalized dimension is allowed under policy.

    The *holistic* parameter is accepted for backward compatibility but ignored.
    """
    key = normalize_dimension_name(name)
    if not key:
        return False

    if is_known_dimension(key):
        return True
    if not is_custom_dimension(key):
        return False
    return key in policy.allowed_custom or policy.allow_custom


def normalize_dimension_inputs(
    raw_dimensions: list[str] | None,
    *,
    holistic: bool = False,
    policy: DimensionPolicy,
) -> tuple[list[str], list[str]]:
    """Normalize + validate requested dimensions against policy.

    The *holistic* parameter is accepted for backward compatibility but ignored.
    """
    if not raw_dimensions:
        return [], []

    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw in raw_dimensions:
        canonical = normalize_dimension_name(str(raw))
        if not canonical:
            continue
        if not is_allowed_dimension(canonical, policy=policy):
            invalid.append(str(raw).strip())
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        valid.append(canonical)

    return valid, invalid


def normalize_assessment_inputs(
    raw_assessments: dict | None,
    *,
    policy: DimensionPolicy,
) -> tuple[dict, list[str], set[str]]:
    """Normalize assessment keys and enforce dimension policy.

    Returns (accepted_assessments, skipped_inputs, newly_discovered_custom_dims).
    """
    if not isinstance(raw_assessments, dict) or not raw_assessments:
        return {}, [], set()

    accepted: dict = {}
    skipped: list[str] = []
    discovered_custom: set[str] = set()

    for raw_name, value in raw_assessments.items():
        canonical = normalize_dimension_name(str(raw_name))
        if not canonical:
            skipped.append(str(raw_name))
            continue
        if not is_allowed_dimension(canonical, policy=policy):
            skipped.append(str(raw_name))
            continue
        accepted[canonical] = value
        if is_custom_dimension(canonical) and canonical not in policy.allowed_custom:
            discovered_custom.add(canonical)

    return accepted, sorted(set(skipped)), discovered_custom


def append_custom_dimensions(state: dict, custom_dimensions: set[str] | list[str]) -> None:
    """Persist newly discovered custom dimensions to state (deduplicated)."""
    if not custom_dimensions:
        return

    bucket = state.setdefault("custom_review_dimensions", [])
    if not isinstance(bucket, list):
        bucket = []
        state["custom_review_dimensions"] = bucket

    seen = _normalized_custom_allowlist(bucket)
    for raw in custom_dimensions:
        canonical = normalize_dimension_name(str(raw))
        if not canonical or not is_custom_dimension(canonical) or canonical in seen:
            continue
        bucket.append(canonical)
        seen.add(canonical)


def filter_assessments_for_scoring(
    raw_assessments: dict | None,
    *,
    policy: DimensionPolicy,
) -> dict | None:
    """Filter/normalize assessments to scoring-eligible dimensions."""
    accepted, _skipped, _new_custom = normalize_assessment_inputs(raw_assessments, policy=policy)
    return accepted or None
