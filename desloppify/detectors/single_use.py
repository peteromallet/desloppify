"""Single-use abstraction detection (imported by exactly 1 file = inline candidate)."""

from pathlib import Path

from ..utils import rel


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
            total_candidates += 1
            loc = len(p.read_text().splitlines())
            if loc < 20 or loc > 300:
                continue
            importer = list(entry["importers"])[0]
            entries.append({
                "file": filepath, "loc": loc,
                "sole_importer": rel(importer),
                "reason": f"Only imported by {rel(importer)} — consider inlining",
                "import_count": entry.get("import_count", 0),
            })
        except (OSError, UnicodeDecodeError):
            continue
    return sorted(entries, key=lambda e: -e["loc"]), total_candidates
