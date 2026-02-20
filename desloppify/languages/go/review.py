"""Review guidance hooks for language plugin scaffolding."""

from __future__ import annotations

import re


REVIEW_GUIDANCE = {
    "patterns": [],
    "auth": [],
    "naming": "go naming guidance placeholder",
}

HOLISTIC_REVIEW_DIMENSIONS = ["cross_module_architecture", "test_strategy"]

MIGRATION_PATTERN_PAIRS: list[tuple[str, object, object]] = []
MIGRATION_MIXED_EXTENSIONS: set[str] = set()
LOW_VALUE_PATTERN = re.compile(r"$^")


def module_patterns(_content: str) -> list[str]:
    return []


def api_surface(_file_contents: dict[str, str]) -> dict:
    return {}
