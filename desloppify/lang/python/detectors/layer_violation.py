"""Detect architectural layer violations in import graphs.

Enforces configurable import direction rules between packages.
When no explicit config is provided, applies a sensible default:
  - detectors/ may not import from lang/ (shared detectors must be language-agnostic)
"""

from __future__ import annotations

import ast
from typing import Sequence

from ....layer_violation_core import (
    detect_layer_violations as _detect_layer_violations_core,
    forbidden_matches_module as _forbidden_matches_module_core,
    resolve_import_modules as _resolve_import_modules_core,
)


# Default layer rules: (source_package_pattern, forbidden_import_pattern, description)
# These apply when no explicit config is provided.
_DEFAULT_RULES: list[tuple[str, str, str]] = [
    (
        "desloppify/detectors/",
        "lang/",
        "Shared detector imports from language plugin — breaks language-agnosticity",
    ),
    (
        "desloppify/detectors/",
        "review/",
        "Shared detector imports from review layer — breaks layer separation",
    ),
    (
        "desloppify/narrative/",
        "commands/",
        "Narrative module imports from command layer — breaks separation of concerns",
    ),
]


def _forbidden_matches_module(module_path: str, forbidden: str) -> bool:
    """Component-aware forbidden import match."""
    return _forbidden_matches_module_core(module_path, forbidden)


def _resolve_import_modules(node: ast.AST, filepath: str) -> list[str]:
    """Return imported module paths (dotted) for ast.Import/ast.ImportFrom nodes."""
    return _resolve_import_modules_core(node, filepath)


def detect_layer_violations(
    path,
    file_finder,
    *,
    rules: Sequence[tuple[str, str, str]] | None = None,
) -> tuple[list[dict], int]:
    """Detect imports that violate architectural layer boundaries."""
    active_rules = rules if rules is not None else _DEFAULT_RULES
    return _detect_layer_violations_core(
        path,
        file_finder,
        rules=active_rules,
        resolve_modules=_resolve_import_modules,
        forbidden_matcher=_forbidden_matches_module,
    )
