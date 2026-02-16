"""Detect architectural layer violations in import graphs.

Enforces configurable import direction rules between packages.
When no explicit config is provided, applies a sensible default:
  - detectors/ may not import from lang/ (shared detectors must be language-agnostic)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Sequence


# Default layer rules: (source_package_pattern, forbidden_import_pattern, description)
# These apply when no explicit config is provided.
_DEFAULT_RULES: list[tuple[str, str, str]] = [
    (
        "detectors/",
        "lang/",
        "Shared detector imports from language plugin — breaks language-agnosticity",
    ),
    (
        "detectors/",
        "review/",
        "Shared detector imports from review layer — breaks layer separation",
    ),
    (
        "narrative/",
        "commands/",
        "Narrative module imports from command layer — breaks separation of concerns",
    ),
]


def _forbidden_matches_module(module_path: str, forbidden: str) -> bool:
    """Component-aware forbidden import match."""
    parts = [p for p in module_path.split("/") if p]
    forbidden_parts = [p for p in forbidden.strip("/").split("/") if p]
    if not parts or not forbidden_parts:
        return False
    width = len(forbidden_parts)
    for idx in range(len(parts) - width + 1):
        if parts[idx:idx + width] == forbidden_parts:
            return True
    return False


def _resolve_import_modules(node: ast.AST, filepath: str) -> list[str]:
    """Return imported module paths (dotted) for ast.Import/ast.ImportFrom nodes."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names if alias.name]

    if not isinstance(node, ast.ImportFrom):
        return []

    # Absolute import
    if node.level == 0:
        return [node.module] if node.module else [alias.name for alias in node.names if alias.name]

    rel_parts = list(Path(filepath).with_suffix("").parts[:-1])
    # level=1 stays in current package; level=2 goes up 1 package; etc.
    up = max(0, node.level - 1)
    if up:
        rel_parts = rel_parts[:-up] if up <= len(rel_parts) else []

    if node.module:
        return [".".join(rel_parts + node.module.split("."))]

    # from .. import review, foo
    return [".".join(rel_parts + [alias.name]) for alias in node.names if alias.name]


def detect_layer_violations(
    path: Path,
    file_finder,
    *,
    rules: Sequence[tuple[str, str, str]] | None = None,
) -> tuple[list[dict], int]:
    """Detect imports that violate architectural layer boundaries.

    Args:
        path: Root path to scan.
        file_finder: Callable that returns list of source files.
        rules: Optional list of (source_pattern, forbidden_pattern, description).
               Falls back to _DEFAULT_RULES if not provided.

    Returns:
        (entries, total_files_checked) where each entry has:
        file, line, source_pkg, target_pkg, description, confidence, summary.
    """
    active_rules = rules if rules is not None else _DEFAULT_RULES
    files = file_finder(path)
    entries: list[dict] = []

    for filepath in files:
        # Check if this file is in a source package that has rules
        matching_rules = [
            (forbidden, desc)
            for source, forbidden, desc in active_rules
            if source in filepath
        ]
        if not matching_rules:
            continue

        try:
            p = Path(filepath) if filepath and Path(filepath).is_absolute() else path / filepath
            content = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            modules = _resolve_import_modules(node, filepath)
            if not modules:
                continue

            for module in modules:
                module_path = module.replace(".", "/")
                for forbidden, desc in matching_rules:
                    if not _forbidden_matches_module(module_path, forbidden):
                        continue

                    # Extract the source package for the finding
                    source_pkg = ""
                    for source, _, _ in active_rules:
                        if source in filepath:
                            source_pkg = source.rstrip("/")
                            break

                    entries.append({
                        "file": filepath,
                        "line": node.lineno,
                        "source_pkg": source_pkg,
                        "target_pkg": module,
                        "description": desc,
                        "confidence": "high",
                        "summary": (
                            f"Layer violation: {source_pkg}/ imports from "
                            f"{forbidden.rstrip('/')}/ ({desc})"
                        ),
                    })

    return entries, len(files)
