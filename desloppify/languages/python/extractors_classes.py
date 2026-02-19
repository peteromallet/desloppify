"""Class extraction helpers for Python structural analysis."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.engine.detectors.base import ClassInfo, FunctionInfo
from desloppify.languages.python.extractors_shared import find_block_end, read_file
from desloppify.utils import find_py_files


def extract_py_classes(path: Path) -> list[ClassInfo]:
    """Extract Python classes with method/attribute/base-class metrics (>=50 LOC)."""
    results = []
    for filepath in find_py_files(path):
        content = read_file(filepath)
        if content is None:
            continue
        results.extend(_extract_classes_from_file(filepath, content.splitlines()))
    return results


def _extract_classes_from_file(filepath: str, lines: list[str]) -> list[ClassInfo]:
    """Extract ClassInfo objects from a single Python file."""
    results = []
    class_re = re.compile(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:")

    index = 0
    while index < len(lines):
        match = class_re.match(lines[index])
        if not match:
            index += 1
            continue

        class_name = match.group(1)
        bases = match.group(2) or ""
        class_start = index
        class_indent = len(lines[index]) - len(lines[index].lstrip())
        class_end = find_block_end(lines, index + 1, class_indent)
        class_loc = class_end - class_start

        if class_loc < 50:
            index = class_end
            continue

        methods = _extract_methods(lines, class_start + 1, class_end)
        attributes = _extract_init_attributes(lines, class_start, class_end)
        base_list = (
            [base.strip() for base in bases.split(",") if base.strip()] if bases else []
        )
        non_mixin_bases = [
            base
            for base in base_list
            if not base.endswith("Mixin") and base not in ("object", "ABC")
        ]

        results.append(
            ClassInfo(
                name=class_name,
                file=filepath,
                line=class_start + 1,
                loc=class_loc,
                methods=methods,
                attributes=attributes,
                base_classes=non_mixin_bases,
            )
        )
        index = class_end

    return results


def _extract_methods(lines: list[str], start: int, end: int) -> list[FunctionInfo]:
    """Extract methods from a class body as FunctionInfo objects."""
    methods = []
    method_re = re.compile(r"^\s+(?:async\s+)?def\s+(\w+)")

    index = start
    while index < end:
        match = method_re.match(lines[index])
        if not match:
            index += 1
            continue

        method_indent = len(lines[index]) - len(lines[index].lstrip())
        method_start = index
        block_end = find_block_end(lines, index + 1, method_indent, limit=end)
        methods.append(
            FunctionInfo(
                name=match.group(1),
                file="",
                line=method_start + 1,
                end_line=block_end,
                loc=block_end - method_start,
                body="",
            )
        )
        index = block_end

    return methods


def _extract_init_attributes(
    lines: list[str], class_start: int, class_end: int
) -> list[str]:
    """Extract self.x = ... attribute names from __init__."""
    attrs = set()
    in_init = False
    init_indent = 0

    for idx in range(class_start, class_end):
        stripped = lines[idx].strip()
        if re.match(r"def\s+__init__\s*\(", stripped):
            in_init = True
            init_indent = len(lines[idx]) - len(lines[idx].lstrip())
            continue
        if in_init:
            if (
                lines[idx].strip()
                and len(lines[idx]) - len(lines[idx].lstrip()) <= init_indent
            ):
                in_init = False
                continue
            for attr_match in re.finditer(r"self\.(\w+)\s*=", lines[idx]):
                attrs.add(attr_match.group(1))

    return sorted(attrs)


__all__ = ["extract_py_classes"]
