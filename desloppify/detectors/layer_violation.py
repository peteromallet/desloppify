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
        "narrative/",
        "commands/",
        "Narrative module imports from command layer — breaks separation of concerns",
    ),
]


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
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name if node.names else None

            if module is None:
                continue

            # Convert dotted module path to slash path for pattern matching
            module_path = module.replace(".", "/")

            for forbidden, desc in matching_rules:
                if forbidden in module_path:
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
