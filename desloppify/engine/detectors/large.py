"""Large file detection (LOC threshold)."""

import logging
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT

logger = logging.getLogger(__name__)


def detect_large_files(
    path: Path, file_finder, threshold: int = 500
) -> tuple[list[dict], int]:
    """Find files exceeding a line count threshold.

    Args:
        file_finder: callable(path) -> list[str]. Required.
        threshold: LOC threshold.

    Returns:
        (entries, total_files_checked)
    """
    files = file_finder(path)
    entries = []
    for filepath in files:
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            loc = len(p.read_text().splitlines())
            if loc > threshold:
                entries.append({"file": filepath, "loc": loc})
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(
                "Skipping unreadable file in large-file detector: %s (%s)",
                filepath,
                exc,
            )
            continue
    return sorted(entries, key=lambda e: -e["loc"]), len(files)
