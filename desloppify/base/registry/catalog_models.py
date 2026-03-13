"""Detector catalog model types and ordering constants."""

from __future__ import annotations

from dataclasses import dataclass

DISPLAY_ORDER = [
    "logs",
    "unused",
    "exports",
    "deprecated",
    "structural",
    "props",
    "single_use",
    "coupling",
    "cycles",
    "orphaned",
    "uncalled_functions",
    "unused_enums",
    "facade",
    "patterns",
    "naming",
    "smells",
    "react",
    "nextjs",
    "next_lint",
    "dupes",
    "stale_exclude",
    "dict_keys",
    "flat_dirs",
    "signature",
    "clippy_warning",
    "cargo_error",
    "rustdoc_warning",
    "rust_import_hygiene",
    "rust_feature_hygiene",
    "rust_doctest",
    "rust_api_convention",
    "rust_error_boundary",
    "rust_future_proofing",
    "rust_thread_safety",
    "rust_async_locking",
    "rust_drop_safety",
    "rust_unsafe_api",
    "global_mutable_config",
    "private_imports",
    "layer_violation",
    "test_coverage",
    "security",
    "concerns",
    "review",
    "subjective_review",
]


@dataclass(frozen=True)
class DetectorMeta:
    name: str
    display: str  # Human-readable for terminal display
    dimension: str  # Scoring dimension name
    action_type: str  # "auto_fix" | "refactor" | "reorganize" | "manual_fix"
    guidance: str  # Narrative coaching text
    fixers: tuple[str, ...] = ()
    tool: str = ""  # "move" or empty
    structural: bool = False  # Merges under "structural" in display
    needs_judgment: bool = False  # Issues need LLM design judgment (vs clear-cut fixes)
    standalone_threshold: str | None = None  # Min confidence for standalone queue item
    tier: int = 2  # T1-T4 scoring weight
    marks_dims_stale: bool = False  # Mechanical changes should stale subjective dimensions
    subjective_dimensions: tuple[str, ...] = ()  # Review dimensions this detector provides evidence for


__all__ = ["DISPLAY_ORDER", "DetectorMeta"]
