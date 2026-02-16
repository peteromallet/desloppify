"""Python move helpers for import replacement computation."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ...utils import PROJECT_ROOT

VERIFY_HINT = ""


def _dedup(replacements: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Deduplicate replacement tuples while preserving order."""
    seen: set[tuple[str, str]] = set()
    result = []
    for pair in replacements:
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return result


def _path_to_py_module(filepath: str, root: Path) -> str | None:
    """Convert a Python file path to a dotted module name relative to root."""
    try:
        rel_path = Path(filepath).relative_to(root)
    except ValueError:
        return None
    parts = list(rel_path.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _has_exact_module(line: str, module: str) -> bool:
    """Check whether an import line references this exact module."""
    return bool(re.search(rf"(?<!\w){re.escape(module)}(?![\w.])", line))


def _replace_exact_module(line: str, old_module: str, new_module: str) -> str:
    """Replace an exact module reference in a Python import line."""
    return re.sub(rf"(?<!\w){re.escape(old_module)}(?![\w.])", new_module, line)


def _resolve_py_relative(source_dir: Path, dots: str, remainder: str) -> str | None:
    """Resolve a relative Python import to an absolute file path."""
    dot_count = len(dots)
    base = source_dir
    for _ in range(dot_count - 1):
        base = base.parent

    if remainder:
        parts = remainder.split(".")
        target_base = base
        for part in parts:
            target_base = target_base / part
    else:
        target_base = base

    candidate = Path(str(target_base) + ".py")
    if candidate.is_file():
        return str(candidate.resolve())
    candidate = target_base / "__init__.py"
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _compute_py_relative_import(from_file: str, to_file: str) -> str | None:
    """Compute a relative Python import string from from_file to to_file."""
    from_dir = Path(from_file).parent
    try:
        rel_path = os.path.relpath(to_file, from_dir)
    except ValueError:
        return None

    parts = Path(rel_path).parts
    ups = 0
    for p in parts:
        if p == "..":
            ups += 1
        else:
            break

    dot_count = ups + 1
    remainder_parts = list(parts[ups:])

    if remainder_parts and remainder_parts[-1].endswith(".py"):
        remainder_parts[-1] = remainder_parts[-1][:-3]
    if remainder_parts and remainder_parts[-1] == "__init__":
        remainder_parts = remainder_parts[:-1]

    dots = "." * dot_count
    remainder = ".".join(remainder_parts)
    return f"{dots}{remainder}"


def find_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """Compute all import string replacements needed for a Python file move."""
    changes: dict[str, list[tuple[str, str]]] = {}
    entry = graph.get(source_abs)
    if not entry:
        return changes

    old_module = _path_to_py_module(source_abs, PROJECT_ROOT)
    new_module = _path_to_py_module(dest_abs, PROJECT_ROOT)
    if not old_module or not new_module:
        return changes

    importers = entry.get("importers", set())

    for importer in importers:
        if importer == source_abs:
            continue

        try:
            content = Path(importer).read_text()
        except (OSError, UnicodeDecodeError):
            continue

        replacements = []
        importer_dir = Path(importer).parent

        for line in content.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue

            if _has_exact_module(stripped, old_module):
                new_line = _replace_exact_module(stripped, old_module, new_module)
                if new_line != stripped:
                    replacements.append((stripped, new_line))
                    continue

            m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)\s+import", stripped)
            if m:
                dots = m.group(1)
                remainder = m.group(2)
                resolved = _resolve_py_relative(importer_dir, dots, remainder)
                if resolved and str(Path(resolved).resolve()) == source_abs:
                    new_rel = _compute_py_relative_import(importer, dest_abs)
                    if new_rel:
                        old_from = f"from {dots}{remainder}"
                        new_from = f"from {new_rel}"
                        replacements.append((old_from, new_from))

        if replacements:
            changes[importer] = _dedup(replacements)

    return changes


def find_self_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> list[tuple[str, str]]:
    """Compute replacements for the moved file's own relative imports."""
    replacements = []
    entry = graph.get(source_abs)
    if not entry:
        return replacements

    try:
        content = Path(source_abs).read_text()
    except (OSError, UnicodeDecodeError):
        return replacements

    source_dir = Path(source_abs).parent

    for line in content.splitlines():
        stripped = line.strip()
        m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)\s+import", stripped)
        if not m:
            continue

        dots = m.group(1)
        remainder = m.group(2)
        resolved = _resolve_py_relative(source_dir, dots, remainder)
        if not resolved:
            continue

        new_rel = _compute_py_relative_import(dest_abs, resolved)
        if not new_rel:
            continue

        old_from = f"from {dots}{remainder}"
        new_from = f"from {new_rel}"
        if old_from != new_from:
            replacements.append((old_from, new_from))

    return _dedup(replacements)


def filter_intra_package_importer_changes(
    _source_file: str, replacements: list[tuple[str, str]], _moving_files: set[str],
) -> list[tuple[str, str]]:
    """For Python package moves, keep only absolute import replacements."""
    return [(old, new) for old, new in replacements if not re.match(r"from\s+\.", old)]


def filter_directory_self_changes(
    source_file: str, self_changes: list[tuple[str, str]], moving_files: set[str],
) -> list[tuple[str, str]]:
    """Drop self-import updates that remain valid inside a co-moving package."""
    filtered_self = []
    src_dir = Path(source_file).parent
    for old_str, new_str in self_changes:
        m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)", old_str)
        if m:
            dots, remainder = m.group(1), m.group(2)
            resolved = _resolve_py_relative(src_dir, dots, remainder)
            if resolved and resolved in moving_files:
                continue
        filtered_self.append((old_str, new_str))
    return filtered_self


# Backward-compat aliases
find_py_replacements = find_replacements
find_py_self_replacements = find_self_replacements

