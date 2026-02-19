"""Cross-language security detector entrypoint."""

from __future__ import annotations

import logging
from pathlib import Path

from desloppify.engine.policy.zones import FileZoneMap

from .filters import _is_test_file, _should_scan_file, _should_skip_line
from .scanner import _scan_line_for_security_entries

logger = logging.getLogger(__name__)


def detect_security_issues(
    files: list[str],
    zone_map: FileZoneMap | None,
    lang_name: str,
) -> tuple[list[dict], int]:
    """Detect cross-language security issues in source files."""
    _ = lang_name
    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if not _should_scan_file(filepath, zone_map):
            continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            logger.debug(
                "Skipping unreadable file in security detector: %s (%s)", filepath, exc
            )
            continue

        scanned += 1
        lines = content.splitlines()
        is_test = _is_test_file(filepath, zone_map)

        for line_num, line in enumerate(lines, 1):
            if _should_skip_line(line):
                continue
            entries.extend(
                _scan_line_for_security_entries(
                    filepath=filepath,
                    line_num=line_num,
                    line=line,
                    is_test=is_test,
                )
            )

    return entries, scanned
