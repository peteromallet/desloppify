"""Implicit mixin self-contract coupling detector."""

from __future__ import annotations

import ast
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import find_py_files

_IGNORED_SELF_ATTRS = {"logger"}


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _is_mixin_candidate(filepath: str, class_name: str) -> bool:
    if class_name.endswith("Mixin"):
        return True
    normalized = filepath.replace("\\", "/")
    return "/phases/" in normalized


def _class_declared_contract_attrs(node: ast.ClassDef) -> set[str]:
    declared: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            declared.add(stmt.target.id)
    return declared


def _class_has_explicit_protocol(node: ast.ClassDef) -> bool:
    return any(_base_name(base).endswith("Protocol") for base in node.bases)


def _collect_self_attrs(node: ast.ClassDef) -> tuple[set[str], set[str]]:
    reads: set[str] = set()
    writes: set[str] = set()
    for stmt in node.body:
        if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for child in ast.walk(stmt):
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name) and child.value.id == "self":
                    if isinstance(child.ctx, ast.Load):
                        reads.add(child.attr)
                    elif isinstance(child.ctx, ast.Store | ast.Del):
                        writes.add(child.attr)
            elif isinstance(child, ast.Call):
                # setattr(self, "name", value) defines contract attributes too.
                if (
                    isinstance(child.func, ast.Name)
                    and child.func.id == "setattr"
                    and len(child.args) >= 2
                    and isinstance(child.args[0], ast.Name)
                    and child.args[0].id == "self"
                    and isinstance(child.args[1], ast.Constant)
                    and isinstance(child.args[1].value, str)
                ):
                    writes.add(child.args[1].value)
    return reads, writes


def detect_implicit_mixin_contracts(
    path: Path, *, min_required_attrs: int = 3
) -> tuple[list[dict], int]:
    """Detect mixin-like classes that rely on undeclared host self-attributes."""
    entries: list[dict] = []
    candidates = 0

    for filepath in find_py_files(path):
        full = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        try:
            content = full.read_text()
            tree = ast.parse(content)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            # Preserve parse/read context while intentionally skipping broken files.
            _ = (full, exc)
            continue

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_mixin_candidate(filepath, node.name):
                continue
            candidates += 1

            declared = _class_declared_contract_attrs(node)
            reads, writes = _collect_self_attrs(node)
            required = {
                name
                for name in (reads - writes - declared)
                if name and not name.startswith("__") and name not in _IGNORED_SELF_ATTRS
            }
            if len(required) < min_required_attrs:
                continue

            if _class_has_explicit_protocol(node):
                continue

            entries.append(
                {
                    "file": filepath,
                    "class": node.name,
                    "line": node.lineno,
                    "required_attrs": sorted(required),
                    "required_count": len(required),
                }
            )

    entries.sort(key=lambda item: (-item["required_count"], item["file"], item["class"]))
    return entries, candidates


__all__ = ["detect_implicit_mixin_contracts"]
