"""Shared engine for layer-violation import analysis."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable, Sequence

LayerRule = tuple[str, str, str]


def forbidden_matches_module(module_path: str, forbidden: str) -> bool:
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


def resolve_import_modules(node: ast.AST, filepath: str) -> list[str]:
    """Return imported module paths (dotted) for ast.Import/ast.ImportFrom nodes."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names if alias.name]
    if not isinstance(node, ast.ImportFrom):
        return []

    if node.level == 0:
        return [node.module] if node.module else [alias.name for alias in node.names if alias.name]

    rel_parts = list(Path(filepath).with_suffix("").parts[:-1])
    up = max(0, node.level - 1)
    if up:
        rel_parts = rel_parts[:-up] if up <= len(rel_parts) else []

    if node.module:
        return [".".join(rel_parts + node.module.split("."))]
    return [".".join(rel_parts + [alias.name]) for alias in node.names if alias.name]


def _matching_rules(filepath: str, rules: Sequence[LayerRule]) -> list[tuple[str, str]]:
    return [(forbidden, desc) for source, forbidden, desc in rules if source in filepath]


def _source_package(filepath: str, rules: Sequence[LayerRule]) -> str:
    for source, _, _ in rules:
        if source in filepath:
            parts = [p for p in source.strip("/").split("/") if p]
            if parts:
                return parts[-1]
            return source.rstrip("/")
    return ""


def _load_ast(path: Path, filepath: str) -> ast.AST | None:
    try:
        p = Path(filepath) if filepath and Path(filepath).is_absolute() else path / filepath
        content = p.read_text()
    except (OSError, UnicodeDecodeError):
        return None

    try:
        return ast.parse(content)
    except SyntaxError:
        return None


def _collect_tree_violations(
    tree: ast.AST,
    filepath: str,
    source_pkg: str,
    matching_rules: Sequence[tuple[str, str]],
    *,
    resolve_modules: Callable[[ast.AST, str], list[str]],
    forbidden_matcher: Callable[[str, str], bool],
) -> list[dict]:
    entries: list[dict] = []
    for node in ast.walk(tree):
        modules = resolve_modules(node, filepath)
        if not modules:
            continue
        line = getattr(node, "lineno", 1)
        for module in modules:
            module_path = module.replace(".", "/")
            for forbidden, desc in matching_rules:
                if not forbidden_matcher(module_path, forbidden):
                    continue
                entries.append(
                    {
                        "file": filepath,
                        "line": line,
                        "source_pkg": source_pkg,
                        "target_pkg": module,
                        "description": desc,
                        "confidence": "high",
                        "summary": (
                            f"Layer violation: {source_pkg}/ imports from "
                            f"{forbidden.rstrip('/')}/ ({desc})"
                        ),
                    }
                )
    return entries


def detect_layer_violations(
    path: Path,
    file_finder,
    *,
    rules: Sequence[LayerRule],
    resolve_modules: Callable[[ast.AST, str], list[str]] = resolve_import_modules,
    forbidden_matcher: Callable[[str, str], bool] = forbidden_matches_module,
) -> tuple[list[dict], int]:
    """Detect imports that violate architectural layer boundaries."""
    files = file_finder(path)
    entries: list[dict] = []

    for filepath in files:
        active_matches = _matching_rules(filepath, rules)
        if not active_matches:
            continue

        tree = _load_ast(path, filepath)
        if tree is None:
            continue

        entries.extend(
            _collect_tree_violations(
                tree,
                filepath,
                _source_package(filepath, rules),
                active_matches,
                resolve_modules=resolve_modules,
                forbidden_matcher=forbidden_matcher,
            )
        )

    return entries, len(files)
