"""Detect architectural layer violations in import graphs.

Enforces configurable import direction rules between packages.
When no explicit config is provided, applies a sensible default:
  - engine/detectors/ may not import from languages/ (shared detectors must be language-agnostic)
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)


# Default layer rules: (source_package_pattern, forbidden_import_pattern, description)
# These apply when no explicit config is provided.
_DEFAULT_RULES: list[tuple[str, str, str]] = [
    (
        "desloppify/engine/detectors/",
        "languages/",
        "Shared detector imports from language plugin — breaks language-agnosticity",
    ),
    (
        "desloppify/engine/detectors/",
        "intelligence/review/",
        "Shared detector imports from review layer — breaks layer separation",
    ),
    (
        "desloppify/intelligence/narrative/",
        "app/commands/",
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
        if parts[idx : idx + width] == forbidden_parts:
            return True
    return False


def _source_matches_file(filepath: str, source: str) -> bool:
    """Component-aware source path match."""
    file_parts = [p for p in filepath.replace("\\", "/").split("/") if p]
    source_parts = [p for p in source.strip("/").split("/") if p]
    if not file_parts or not source_parts:
        return False
    width = len(source_parts)
    for idx in range(len(file_parts) - width + 1):
        if file_parts[idx : idx + width] == source_parts:
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
        return (
            [node.module]
            if node.module
            else [alias.name for alias in node.names if alias.name]
        )

    rel_parts = list(Path(filepath).with_suffix("").parts[:-1])
    # level=1 stays in current package; level=2 goes up 1 package; etc.
    up = max(0, node.level - 1)
    if up:
        rel_parts = rel_parts[:-up] if up <= len(rel_parts) else []

    if node.module:
        return [".".join(rel_parts + node.module.split("."))]

    # from .. import review, foo
    return [".".join(rel_parts + [alias.name]) for alias in node.names if alias.name]


def _matching_rules_for_file(
    filepath: str,
    rules: Sequence[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    return [
        (forbidden, desc)
        for source, forbidden, desc in rules
        if _source_matches_file(filepath, source)
    ]


def _source_package_for_file(
    filepath: str,
    rules: Sequence[tuple[str, str, str]],
) -> str:
    for source, _, _ in rules:
        if _source_matches_file(filepath, source):
            return source.rstrip("/").split("/")[-1]
    return ""


def _read_python_source(path: Path, filepath: str) -> str | None:
    try:
        p = (
            Path(filepath)
            if filepath and Path(filepath).is_absolute()
            else path / filepath
        )
        return p.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            "Skipping unreadable python file %s in layer-violation detector: %s",
            filepath,
            exc,
        )
        return None


def _parse_python_source(source: str, *, filepath: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.debug(
            "Skipping unparseable python file %s in layer-violation detector: %s",
            filepath,
            exc,
        )
        return None


def _collect_layer_violations_for_file(
    filepath: str,
    tree: ast.AST,
    matching_rules: list[tuple[str, str]],
    *,
    source_pkg: str,
) -> list[dict]:
    entries: list[dict] = []
    for node in ast.walk(tree):
        modules = _resolve_import_modules(node, filepath)
        if not modules:
            continue
        for module in modules:
            module_path = module.replace(".", "/")
            for forbidden, desc in matching_rules:
                if not _forbidden_matches_module(module_path, forbidden):
                    continue
                entries.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "source_pkg": source_pkg,
                        "target_pkg": module,
                        "description": desc,
                        "confidence": "high",
                        "summary": (
                            f"Layer violation: {source_pkg}/ imports from {forbidden.rstrip('/')}/ ({desc})"
                        ),
                    }
                )
    return entries


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
        matching_rules = _matching_rules_for_file(filepath, active_rules)
        if not matching_rules:
            continue

        content = _read_python_source(path, filepath)
        if content is None:
            continue

        tree = _parse_python_source(content, filepath=filepath)
        if tree is None:
            continue

        source_pkg = _source_package_for_file(filepath, active_rules)
        entries.extend(
            _collect_layer_violations_for_file(
                filepath,
                tree,
                matching_rules,
                source_pkg=source_pkg,
            )
        )

    return entries, len(files)
