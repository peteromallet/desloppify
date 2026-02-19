"""Review guidance hooks for GDScript/Godot."""

from __future__ import annotations

import re

from desloppify.languages._shared.scaffold_defaults import (
    SCAFFOLD_HOLISTIC_REVIEW_DIMENSIONS as HOLISTIC_REVIEW_DIMENSIONS,
)

REVIEW_GUIDANCE = {
    "patterns": [
        "Keep scene-node orchestration separate from business logic.",
        "Prefer signal-based decoupling over direct node path coupling.",
        "Watch for autoload singletons becoming god objects.",
    ],
    "auth": [],
    "naming": "Use snake_case for functions/variables and PascalCase for class_name declarations.",
}

MIGRATION_PATTERN_PAIRS: list[tuple[str, object, object]] = []
MIGRATION_MIXED_EXTENSIONS: set[str] = set()
LOW_VALUE_PATTERN = re.compile(r"(?m)^\s*(?:signal|@tool)\b")

_PATH_REF_RE = re.compile(
    r"""(?:preload|load)\(\s*['"](?P<path>res://[^'"]+)['"]\s*\)|^\s*extends\s+['"](?P<extends>res://[^'"]+)['"]""",
    re.MULTILINE,
)
_CLASS_RE = re.compile(r"(?m)^\s*class_name\s+([A-Za-z_]\w*)")
_FUNC_RE = re.compile(r"(?m)^\s*func\s+([A-Za-z_]\w*)\s*\(")


def module_patterns(content: str) -> list[str]:
    """Extract module-level script references for review context."""
    out: list[str] = []
    for match in _PATH_REF_RE.finditer(content):
        ref = match.group("path") or match.group("extends")
        if ref:
            out.append(ref)
    return out


def api_surface(file_contents: dict[str, str]) -> dict[str, list[str]]:
    """Build minimal API-surface summary from parsed GDScript files."""
    classes: set[str] = set()
    functions: set[str] = set()
    for content in file_contents.values():
        classes.update(match.group(1) for match in _CLASS_RE.finditer(content))
        for match in _FUNC_RE.finditer(content):
            name = match.group(1)
            if not name.startswith("_"):
                functions.add(name)
    return {"classes": sorted(classes), "public_functions": sorted(functions)}


__all__ = [
    "HOLISTIC_REVIEW_DIMENSIONS",
    "LOW_VALUE_PATTERN",
    "MIGRATION_MIXED_EXTENSIONS",
    "MIGRATION_PATTERN_PAIRS",
    "REVIEW_GUIDANCE",
    "api_surface",
    "module_patterns",
]
