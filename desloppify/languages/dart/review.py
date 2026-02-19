"""Review guidance hooks for Dart/Flutter."""

from __future__ import annotations

import re

from desloppify.languages._shared.scaffold_defaults import (
    SCAFFOLD_HOLISTIC_REVIEW_DIMENSIONS as HOLISTIC_REVIEW_DIMENSIONS,
)

REVIEW_GUIDANCE = {
    "patterns": [
        "Prefer explicit package boundaries (`lib/` vs `test/`).",
        "Keep widget build methods small and focused.",
        "Watch for business logic leaking into UI widgets.",
    ],
    "auth": [
        "Ensure route guards and role checks are centralized.",
        "Avoid auth decisions duplicated across widgets/services.",
    ],
    "naming": "Use lower_snake_case for files and UpperCamelCase for types.",
}

MIGRATION_PATTERN_PAIRS: list[tuple[str, object, object]] = []
MIGRATION_MIXED_EXTENSIONS: set[str] = set()
LOW_VALUE_PATTERN = re.compile(r"^\s*(?:part\s+of|export)\b", re.MULTILINE)

_IMPORT_EXPORT_RE = re.compile(
    r"""(?m)^\s*(?:import|export|part)\s+['"]([^'"]+)['"]"""
)
_TYPE_RE = re.compile(
    r"(?m)^\s*(?:class|enum|mixin|extension|typedef)\s+([A-Za-z_]\w*)"
)
_FUNCTION_RE = re.compile(
    r"(?m)^\s*(?:[A-Za-z_]\w*(?:<[^>{}]+>)?\??\s+)?([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:async\s*)?(?:\{|=>)"
)


def module_patterns(content: str) -> list[str]:
    """Extract module-level dependency specs for review context."""
    return [match.group(1) for match in _IMPORT_EXPORT_RE.finditer(content)]


def api_surface(file_contents: dict[str, str]) -> dict[str, list[str]]:
    """Build minimal API-surface summary from parsed Dart files."""
    public_types: set[str] = set()
    public_functions: set[str] = set()
    for content in file_contents.values():
        for match in _TYPE_RE.finditer(content):
            name = match.group(1)
            if not name.startswith("_"):
                public_types.add(name)
        for match in _FUNCTION_RE.finditer(content):
            name = match.group(1)
            if not name.startswith("_"):
                public_functions.add(name)

    return {
        "public_types": sorted(public_types),
        "public_functions": sorted(public_functions),
    }


__all__ = [
    "HOLISTIC_REVIEW_DIMENSIONS",
    "LOW_VALUE_PATTERN",
    "MIGRATION_MIXED_EXTENSIONS",
    "MIGRATION_PATTERN_PAIRS",
    "REVIEW_GUIDANCE",
    "api_surface",
    "module_patterns",
]
