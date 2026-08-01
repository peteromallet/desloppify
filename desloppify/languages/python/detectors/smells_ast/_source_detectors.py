"""Detectors that operate on raw source content or import targets."""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ConstantLocations = dict[tuple[str, str], list[tuple[str, int]]]
SmellCounts = dict[str, list[dict[str, object]]]
_VERSIONED_MIGRATION_DIRECTORY_PAIRS = frozenset(
    {
        ("alembic", "versions"),
        ("migrations", "versions"),
    }
)


def _is_within(root: Path, candidate: Path) -> bool:
    """Return whether candidate is within root after path resolution."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_versioned_migration_path(filepath: str) -> bool:
    """Return whether a file is an immutable versioned schema migration."""
    path_parts = tuple(
        part.casefold() for part in re.split(r"[\\/]+", filepath) if part
    )
    return any(
        path_parts[index : index + 2] in _VERSIONED_MIGRATION_DIRECTORY_PAIRS
        for index in range(len(path_parts) - 1)
    )


def collect_module_constants(
    filepath: str,
    content: str,
    constants_by_key: ConstantLocations,
) -> None:
    """Collect module-level constant assignments for cross-file duplicate detection.

    Only collects UPPER_CASE or _UPPER_CASE names assigned to simple literals
    (dicts, lists, sets, tuples, numbers, strings).
    """
    if _is_versioned_migration_path(filepath):
        return

    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as exc:
        logger.debug(
            "Skipping unparseable python file %s while collecting constants: %s",
            filepath,
            exc,
        )
        return

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and re.match(
                    r"^_?[A-Z][A-Z0-9_]+$", target.id
                ):
                    try:
                        value_repr = ast.dump(node.value)
                    except (RecursionError, ValueError) as exc:
                        logger.debug(
                            "Skipping unserializable constant in %s:%s: %s",
                            filepath,
                            node.lineno,
                            exc,
                        )
                        continue
                    if len(value_repr) > 500:
                        continue  # Skip very large constants
                    key = (target.id, value_repr)
                    constants_by_key.setdefault(key, []).append((filepath, node.lineno))


def detect_duplicate_constants(
    constants_by_key: ConstantLocations,
    smell_counts: SmellCounts,
) -> None:
    """Flag constants defined identically in multiple files."""
    for (name, _value_repr), locations in constants_by_key.items():
        if len(locations) < 2:
            continue
        # Check that locations are in distinct files
        files = set(fp for fp, _ in locations)
        if len(files) < 2:
            continue
        for filepath, lineno in locations:
            other_files = [fp for fp, _ in locations if fp != filepath]
            smell_counts["duplicate_constant"].append(
                {
                    "file": filepath,
                    "line": lineno,
                    "content": f"{name} also defined in {', '.join(Path(f).name for f in other_files[:3])}",
                }
            )


def detect_star_import_no_all(
    filepath: str,
    content: str,
    scan_root: Path,
    smell_counts: SmellCounts,
) -> None:
    """Flag `from X import *` where the target module has no __all__.

    Resolves relative and absolute imports within the scan root and checks
    whether the target .py file defines __all__. Only flags targets that
    are part of the scanned project (not stdlib/third-party).
    """
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as exc:
        logger.debug(
            "Skipping unparseable python file %s for star-import analysis: %s",
            filepath,
            exc,
        )
        return

    file_path = Path(filepath)
    file_dir = file_path.parent

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        # Only care about star imports
        if not any(alias.name == "*" for alias in node.names):
            continue

        module = node.module or ""
        level = node.level  # 0 = absolute, 1+ = relative

        # Resolve to a file path
        target = _resolve_import_target(module, level, file_dir, scan_root)
        if target is None:
            continue

        # Check if target defines __all__
        try:
            target_content = target.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(
                "Skipping unreadable import target %s referenced by %s: %s",
                target,
                filepath,
                exc,
            )
            continue

        if re.search(r"^__all__\s*=", target_content, re.MULTILINE):
            continue  # Has __all__, controlled export — skip

        smell_counts["star_import_no_all"].append(
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"from {('.' * level) + module} import * (target has no __all__)",
            }
        )


def _resolve_import_target(
    module: str, level: int, file_dir: Path, scan_root: Path
) -> Path | None:
    """Resolve a Python import to a file path within the scan root.

    Returns the target .py file, or None if unresolvable or outside the project.
    """
    scan_root = scan_root.resolve()
    if level > 0:
        # Relative import — go up (level - 1) directories from file_dir
        base = file_dir
        for _ in range(level - 1):
            base = base.parent

        # Relative imports should not resolve outside the current scan root.
        if not _is_within(scan_root, base):
            return None
        bases = (base,)
    else:
        # Absolute imports may be rooted at the scanned directory (repo/src scan)
        # or its parent (single-package scan).
        bases = tuple(dict.fromkeys((scan_root, scan_root.parent)))

    # Convert module dotted path to filesystem path
    parts = module.split(".") if module else []

    for base in bases:
        target_dir = base / Path(*parts) if parts else base

        # Check for package (__init__.py) or module (.py)
        init_path = target_dir / "__init__.py"
        if init_path.is_file() and _is_within(scan_root, init_path):
            return init_path

        module_path = target_dir.with_suffix(".py")
        if module_path.is_file() and _is_within(scan_root, module_path):
            return module_path

    return None


_VESTIGIAL_KEYWORDS = re.compile(
    r"\b(?:unused|legacy|backward|compat|deprecated|no longer|kept for)\b",
    re.IGNORECASE,
)


def detect_vestigial_parameter(
    filepath: str,
    content: str,
    lines: list[str],
    smell_counts: SmellCounts,
) -> None:
    """Flag function parameters annotated as unused/deprecated in nearby comments.

    Scans comments within the line range of each function signature for keywords
    like 'unused', 'legacy', 'deprecated', 'backward compat', etc.
    """
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as exc:
        logger.debug(
            "Skipping unparseable python file %s for vestigial-param analysis: %s",
            filepath,
            exc,
        )
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        # Determine the line range of the signature (def line through first body line)
        sig_start = node.lineno - 1  # 0-indexed
        if node.body:
            sig_end = node.body[0].lineno - 1  # exclusive
        else:
            sig_end = sig_start + 1

        # Scan comments in the signature range
        for i in range(sig_start, min(sig_end, len(lines))):
            line = lines[i]
            comment_idx = line.find("#")
            if comment_idx == -1:
                continue
            comment = line[comment_idx:]
            if _VESTIGIAL_KEYWORDS.search(comment):
                smell_counts["vestigial_parameter"].append(
                    {
                        "file": filepath,
                        "line": i + 1,
                        "content": f"{node.name}(): {comment.strip()[:80]}",
                    }
                )
                break  # One issue per function
