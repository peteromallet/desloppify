"""Review guidance hooks for Go.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

import re

HOLISTIC_REVIEW_DIMENSIONS: list[str] = [
    "cross_module_architecture",
    "error_consistency",
    "abstraction_fitness",
    "test_strategy",
    "design_coherence",
]

REVIEW_GUIDANCE = {
    "patterns": [
        "Prefer explicit package boundaries with clear API surfaces.",
        "Keep exported functions focused and well-documented.",
        "Watch for error-handling inconsistencies (sentinel vs wrapped errors).",
    ],
    "auth": [
        "Ensure middleware-based auth guards are centralized.",
        "Avoid duplicating auth checks across handlers.",
    ],
    "naming": "Use camelCase for unexported and PascalCase for exported identifiers.",
}

MIGRATION_PATTERN_PAIRS: list[tuple[str, object, object]] = []
MIGRATION_MIXED_EXTENSIONS: set[str] = set()
LOW_VALUE_PATTERN = re.compile(
    r"^\s*(?:package\s+\w+\s*$|//\s*(?:go:generate|nolint))", re.MULTILINE
)

_IMPORT_RE = re.compile(r"""(?m)^\s*(?:import\s+)?"([^"]+)"\s*$""")
_TYPE_RE = re.compile(r"(?m)^\s*type\s+([A-Z]\w*)\s+(?:struct|interface)\b")
_FUNCTION_RE = re.compile(
    r"(?m)^func\s+(?:\(\s*\w+\s+\*?\w+\s*\)\s*)?([A-Z]\w*)\s*\("
)


def module_patterns(content: str) -> list[str]:
    """Extract module-level dependency specs for review context."""
    return [match.group(1) for match in _IMPORT_RE.finditer(content)]


def api_surface(file_contents: dict[str, str]) -> dict[str, list[str]]:
    """Build minimal API-surface summary from parsed Go files."""
    public_types: set[str] = set()
    public_functions: set[str] = set()
    for content in file_contents.values():
        for match in _TYPE_RE.finditer(content):
            public_types.add(match.group(1))
        for match in _FUNCTION_RE.finditer(content):
            public_functions.add(match.group(1))

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
