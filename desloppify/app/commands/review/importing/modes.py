"""Stable review import mode normalization for command entrypoints."""

from __future__ import annotations

from typing import Literal

ReviewImportMode = Literal[
    "auto",
    "trusted_internal",
    "attested_external",
    "manual_override",
]

_ALLOWED_MODES: set[str] = {
    "auto",
    "trusted_internal",
    "attested_external",
    "manual_override",
}


def normalize_review_import_mode(raw: str | None) -> ReviewImportMode:
    """Normalize user/caller import mode text to one stable mode token."""
    mode = (raw or "auto").strip().lower().replace("-", "_")
    if mode not in _ALLOWED_MODES:
        allowed = ", ".join(sorted(_ALLOWED_MODES))
        raise ValueError(f"invalid review import mode '{raw}'; expected one of: {allowed}")
    return mode  # type: ignore[return-value]


def _validate_mode_compatibility(
    *,
    mode: ReviewImportMode,
    attested: bool,
    manual: bool,
) -> None:
    if mode == "trusted_internal" and (attested or manual):
        raise ValueError(
            "import_mode=trusted_internal cannot be combined with attested/manual flags"
        )
    if mode == "attested_external" and manual:
        raise ValueError(
            "import_mode=attested_external cannot be combined with manual override flags"
        )
    if mode == "manual_override" and attested:
        raise ValueError(
            "import_mode=manual_override cannot be combined with attested external flags"
        )


def _apply_trusted_internal_defaults(
    trusted_source: bool,
    trusted_label: str | None,
) -> tuple[bool, str, bool, bool]:
    if not trusted_source:
        trusted_source = True
    if not isinstance(trusted_label, str) or not trusted_label.strip():
        trusted_label = "trusted internal run-batches import"
    return trusted_source, trusted_label, False, False


def apply_review_import_mode(
    *,
    import_mode: str | None,
    trusted_assessment_source: bool,
    trusted_assessment_label: str | None,
    attested_external: bool,
    manual_override: bool,
) -> tuple[bool, str | None, bool, bool]:
    """Apply a canonical import mode over legacy booleans without dropping compatibility."""
    mode = normalize_review_import_mode(import_mode)
    trusted_source = bool(trusted_assessment_source)
    trusted_label = trusted_assessment_label
    attested = bool(attested_external)
    manual = bool(manual_override)

    _validate_mode_compatibility(mode=mode, attested=attested, manual=manual)

    if mode == "trusted_internal":
        return _apply_trusted_internal_defaults(trusted_source, trusted_label)
    if mode == "attested_external":
        return trusted_source, trusted_label, True, False
    if mode == "manual_override":
        return trusted_source, trusted_label, False, True

    return trusted_source, trusted_label, attested, manual


__all__ = [
    "ReviewImportMode",
    "apply_review_import_mode",
    "normalize_review_import_mode",
]
