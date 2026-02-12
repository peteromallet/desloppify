"""Python import specifier computation and replacement finding for move command."""

import os
import re
from pathlib import Path

from ..utils import PROJECT_ROOT
from .move import _dedup


# ── Python import specifier computation ───────────────────


def _path_to_py_module(filepath: str, root: Path) -> str | None:
    """Convert a Python file path to a dotted module name relative to root.

    E.g. scripts/foo/commands/move.py -> scripts.foo.commands.move
    """
    try:
        rel_path = Path(filepath).relative_to(root)
    except ValueError:
        return None
    parts = list(rel_path.parts)
    # Strip .py extension from last part
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    # Strip __init__ (package itself)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _has_exact_module(line: str, module: str) -> bool:
    """Check if a Python import line references this exact module (not a child)."""
    return bool(re.search(rf'\b{re.escape(module)}\b', line))


def _replace_exact_module(line: str, old_module: str, new_module: str) -> str:
    """Replace an exact module reference in a Python import line."""
    return re.sub(rf'\b{re.escape(old_module)}\b', new_module, line)


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

    # Try foo.py, foo/__init__.py
    candidate = Path(str(target_base) + ".py")
    if candidate.is_file():
        return str(candidate.resolve())
    candidate = target_base / "__init__.py"
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _compute_py_relative_import(from_file: str, to_file: str) -> str | None:
    """Compute a relative Python import string from from_file to to_file.

    Returns the 'from' part, e.g. '.foo' or '..bar.baz'.
    """
    from_dir = Path(from_file).parent

    # Find common ancestor
    try:
        rel_path = os.path.relpath(to_file, from_dir)
    except ValueError:
        return None

    parts = Path(rel_path).parts
    # Count leading '..' to determine dot count
    ups = 0
    for p in parts:
        if p == "..":
            ups += 1
        else:
            break

    # dots = ups + 1 (one dot = same package)
    dot_count = ups + 1
    remainder_parts = list(parts[ups:])

    # Strip .py extension from last part
    if remainder_parts and remainder_parts[-1].endswith(".py"):
        remainder_parts[-1] = remainder_parts[-1][:-3]
    # Strip __init__ (importing from package)
    if remainder_parts and remainder_parts[-1] == "__init__":
        remainder_parts = remainder_parts[:-1]

    dots = "." * dot_count
    remainder = ".".join(remainder_parts)
    return f"{dots}{remainder}"


# ── Finding import lines and computing replacements ───────


def find_py_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """Compute all import string replacements needed for a Python file move.

    Returns {filepath: [(old_str, new_str), ...]}
    """
    changes: dict[str, list[tuple[str, str]]] = {}
    entry = graph.get(source_abs)
    if not entry:
        return changes

    # Compute old and new dotted module names
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

            # Handle absolute imports: from old.module import X / import old.module
            # Use word-boundary check to avoid matching old.module.child
            if _has_exact_module(stripped, old_module):
                new_line = _replace_exact_module(stripped, old_module, new_module)
                if new_line != stripped:
                    replacements.append((stripped, new_line))
                    continue

            # Handle relative imports
            m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)\s+import", stripped)
            if m:
                dots = m.group(1)
                remainder = m.group(2)
                resolved = _resolve_py_relative(importer_dir, dots, remainder)
                if resolved and str(Path(resolved).resolve()) == source_abs:
                    # Recompute relative import from importer to new location
                    new_rel = _compute_py_relative_import(importer, dest_abs)
                    if new_rel:
                        old_from = f"from {dots}{remainder}"
                        new_from = f"from {new_rel}"
                        replacements.append((old_from, new_from))

        if replacements:
            changes[importer] = _dedup(replacements)

    return changes


def find_py_self_replacements(
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

        # Resolve what this relative import points to from the source location
        resolved = _resolve_py_relative(source_dir, dots, remainder)
        if not resolved:
            continue

        # Compute new relative import from dest location to the same target
        new_rel = _compute_py_relative_import(dest_abs, resolved)
        if not new_rel:
            continue

        old_from = f"from {dots}{remainder}"
        new_from = f"from {new_rel}"
        if old_from != new_from:
            replacements.append((old_from, new_from))

    return _dedup(replacements)
