"""Zone and line-level filtering helpers for security detector."""

from __future__ import annotations

from desloppify.engine.detectors.patterns.security import (
    has_secret_format_match as _has_secret_format_match,
)
from desloppify.engine.detectors.patterns.security import (
    is_comment_line as _is_comment_line,
)
from desloppify.engine.policy.zones import FileZoneMap, Zone

_EXCLUDED_SECURITY_ZONES = (Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR)


def _should_scan_file(filepath: str, zone_map: FileZoneMap | None) -> bool:
    if zone_map is None:
        return True
    zone = zone_map.get(filepath)
    return zone not in _EXCLUDED_SECURITY_ZONES


def _is_test_file(filepath: str, zone_map: FileZoneMap | None) -> bool:
    return zone_map is not None and zone_map.get(filepath) == Zone.TEST


def _should_skip_line(line: str) -> bool:
    return _is_comment_line(line) and not _has_secret_format_match(line)
