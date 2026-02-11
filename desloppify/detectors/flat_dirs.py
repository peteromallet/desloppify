"""Flat directory detection — directories with too many source files."""

from collections import Counter
from pathlib import Path


def detect_flat_dirs(path: Path, file_finder, threshold: int = 20) -> tuple[list[dict], int]:
    """Find directories with too many source files (suggests missing sub-organization).

    Args:
        file_finder: callable(path) -> list[str]. Required.
        threshold: minimum file count to flag.

    Returns:
        (entries, total_directories)
    """
    files = file_finder(path)
    dir_counts: Counter[str] = Counter()
    for f in files:
        parent = str(Path(f).parent)
        dir_counts[parent] += 1

    entries = []
    for dir_path, count in dir_counts.items():
        if count >= threshold:
            entries.append({"directory": dir_path, "file_count": count})
    return sorted(entries, key=lambda e: -e["file_count"]), len(dir_counts)
