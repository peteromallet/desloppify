"""Single-use abstraction detection (imported by exactly 1 file = inline candidate)."""

import logging
from pathlib import Path

from ..utils import rel

LOGGER = logging.getLogger(__name__)


def _is_test_path(filepath: str) -> bool:
    """Heuristic: whether a path points to test code."""
    p = Path(filepath)
    name = p.name.lower()
    parts = {part.lower() for part in p.parts}
    if "tests" in parts or "test" in parts or "__tests__" in parts:
        return True
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def detect_single_use_abstractions(
    path: Path,
    graph: dict,
    barrel_names: set[str],
) -> tuple[list[dict], int]:
    """Find exported symbols imported by exactly 1 file — candidates for inlining.

    Args:
        barrel_names: set of barrel filenames to skip. Required.

    Returns:
        (entries, total_candidate_files) — candidates are files with exactly 1 importer.
    """
    entries = []
    total_candidates = 0
    for filepath, entry in graph.items():
        if entry["importer_count"] != 1:
            continue
        try:
            p = Path(filepath)
            if not p.exists():
                continue
            basename = p.name
            if basename in barrel_names:
                continue
            importer = list(entry["importers"])[0]
            if _is_test_path(importer):
                continue
            total_candidates += 1
            loc = len(p.read_text().splitlines())
            if loc < 20 or loc > 300:
                continue
            entries.append({
                "file": filepath, "loc": loc,
                "sole_importer": rel(importer),
                "reason": f"Only imported by {rel(importer)} — consider inlining",
                "import_count": entry.get("import_count", 0),
            })
        except (OSError, UnicodeDecodeError) as exc:
            LOGGER.debug("Skipping unreadable file during single-use scan: %s", filepath, exc_info=exc)
            continue
    return sorted(entries, key=lambda e: -e["loc"]), total_candidates
