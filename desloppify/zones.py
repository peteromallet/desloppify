"""Zone classification system — deterministic file intent classification.

Classifies files into zones (production, test, config, generated, script, vendor)
based on path patterns. Zone metadata flows through findings, scoring, and the LLM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class Zone(str, Enum):
    """File intent zone — determines scoring and detection policy."""
    PRODUCTION = "production"
    TEST = "test"
    CONFIG = "config"
    GENERATED = "generated"
    SCRIPT = "script"
    VENDOR = "vendor"


# Zones excluded from the health score
EXCLUDED_ZONES = {Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR}

# String values for quick lookup in scoring (findings store zone as string)
EXCLUDED_ZONE_VALUES = {z.value for z in EXCLUDED_ZONES}


@dataclass
class ZoneRule:
    """A classification rule: zone + list of path patterns.

    Patterns are matched against relative file paths. First matching rule wins.
    Pattern types (auto-detected from shape):
      - "/dir/"   → substring match on full path (directory marker)
      - ".ext"    → basename ends-with (suffix/extension, e.g. ".d.ts", ".test.")
      - "prefix_" → basename starts-with (trailing underscore)
      - "name.py" → basename exact match (has extension, no /)
      - fallback  → substring on full path
    """
    zone: Zone
    patterns: list[str]


def _match_pattern(rel_path: str, pattern: str) -> bool:
    """Match a zone pattern against a relative file path.

    See ZoneRule docstring for pattern type conventions.
    """
    basename = os.path.basename(rel_path)

    # Directory pattern: "/dir/" → substring on padded path
    if pattern.startswith("/") and pattern.endswith("/"):
        return pattern in ("/" + rel_path + "/")

    # Suffix/extension pattern: starts with "." → contains on basename
    if pattern.startswith("."):
        return pattern in basename

    # Prefix pattern: ends with "_" → basename starts-with
    if pattern.endswith("_"):
        return basename.startswith(pattern)

    # Suffix pattern: starts with "_" → basename ends-with (_test.py, _pb2.py)
    if pattern.startswith("_"):
        return basename.endswith(pattern)

    # Exact basename: has a proper file extension (1-5 chars after last dot),
    # no "/" → exact basename match (config.py, setup.py, conftest.py)
    if "/" not in pattern and "." in pattern:
        ext = pattern.rsplit(".", 1)[-1]
        if ext and len(ext) <= 5 and ext.isalnum():
            return basename == pattern

    # Fallback: substring on full path (vite.config, tsconfig, eslint, etc.)
    return pattern in rel_path


# ── Common zone rules (shared across languages) ──────────

COMMON_ZONE_RULES = [
    ZoneRule(Zone.VENDOR, ["/vendor/", "/third_party/", "/vendored/"]),
    ZoneRule(Zone.GENERATED, ["/generated/", "/__generated__/"]),
    ZoneRule(Zone.TEST, ["/tests/", "/test/", "/fixtures/"]),
    ZoneRule(Zone.SCRIPT, ["/scripts/", "/bin/"]),
]


def classify_file(rel_path: str, rules: list[ZoneRule],
                  overrides: dict[str, str] | None = None) -> Zone:
    """Classify a file by its relative path. Overrides take priority."""
    if overrides:
        override = overrides.get(rel_path)
        if override:
            try:
                return Zone(override)
            except ValueError:
                pass  # Invalid zone value — fall through to rules
    for rule in rules:
        for pattern in rule.patterns:
            if _match_pattern(rel_path, pattern):
                return rule.zone
    return Zone.PRODUCTION


class FileZoneMap:
    """Cached zone classification for a set of files.

    Built once per scan from file list + zone rules.
    """

    def __init__(self, files: list[str], rules: list[ZoneRule],
                 rel_fn=None, overrides: dict[str, str] | None = None):
        """Build zone map.

        Args:
            files: List of file paths (absolute or relative).
            rules: Ordered zone rules (first match wins).
            rel_fn: Optional function to convert paths to relative.
            overrides: Manual zone overrides {rel_path: zone_value}.
        """
        self._map: dict[str, Zone] = {}
        self._overrides = overrides
        for f in files:
            rp = rel_fn(f) if rel_fn else f
            self._map[f] = classify_file(rp, rules, overrides)

    def get(self, path: str) -> Zone:
        """Get zone for a file path. Returns PRODUCTION if not classified."""
        return self._map.get(path, Zone.PRODUCTION)

    def exclude(self, files: list[str], *zones: Zone) -> list[str]:
        """Return files NOT in the given zones."""
        zone_set = set(zones)
        return [f for f in files if self._map.get(f, Zone.PRODUCTION) not in zone_set]

    def include_only(self, files: list[str], *zones: Zone) -> list[str]:
        """Return files that ARE in the given zones."""
        zone_set = set(zones)
        return [f for f in files if self._map.get(f, Zone.PRODUCTION) in zone_set]

    def counts(self) -> dict[str, int]:
        """Return file count per zone."""
        counts: dict[str, int] = {}
        for zone in self._map.values():
            counts[zone.value] = counts.get(zone.value, 0) + 1
        return counts

    def production_count(self) -> int:
        """Count files classified as production."""
        return len(self._map) - self.non_production_count()

    def non_production_count(self) -> int:
        """Count files in excluded zones (test/config/generated/vendor)."""
        return sum(1 for z in self._map.values() if z in EXCLUDED_ZONES)

    def all_files(self) -> list[str]:
        """Return all classified file paths."""
        return list(self._map.keys())

    def items(self) -> list[tuple[str, Zone]]:
        """Return all (path, zone) pairs."""
        return list(self._map.items())


# ── Zone detection policies ────────────────────────────────

@dataclass
class ZonePolicy:
    """Per-zone detection policy.

    skip_detectors: detectors to skip entirely for this zone.
    downgrade_detectors: detectors whose confidence is downgraded to "low".
    exclude_from_score: whether findings in this zone are excluded from scoring.
    """
    skip_detectors: set[str] = field(default_factory=set)
    downgrade_detectors: set[str] = field(default_factory=set)
    exclude_from_score: bool = False


# Skip almost all detectors for generated/vendor code
_SKIP_ALL_DETECTORS = frozenset({
    "unused", "logs", "exports", "deprecated", "structural",
    "props", "smells", "react", "dupes", "single_use",
    "orphaned", "coupling", "facade", "naming", "patterns",
    "cycles", "flat_dirs", "dict_keys", "test_coverage",
    "security",
})

ZONE_POLICIES: dict[Zone, ZonePolicy] = {
    Zone.PRODUCTION: ZonePolicy(),
    Zone.TEST: ZonePolicy(
        skip_detectors={"dupes", "single_use", "orphaned", "coupling", "facade",
                        "dict_keys", "test_coverage"},
        downgrade_detectors={"smells", "structural"},
        exclude_from_score=True,
    ),
    Zone.CONFIG: ZonePolicy(
        skip_detectors={"smells", "structural", "dupes", "naming",
                        "single_use", "orphaned", "coupling", "facade",
                        "dict_keys", "test_coverage"},
        exclude_from_score=True,
    ),
    Zone.GENERATED: ZonePolicy(
        skip_detectors=_SKIP_ALL_DETECTORS,
        exclude_from_score=True,
    ),
    Zone.VENDOR: ZonePolicy(
        skip_detectors=_SKIP_ALL_DETECTORS,
        exclude_from_score=True,
    ),
    Zone.SCRIPT: ZonePolicy(
        skip_detectors={"coupling", "single_use", "orphaned", "facade"},
        downgrade_detectors={"structural"},
    ),
}


# ── Helpers for phase runners ─────────────────────────────

def adjust_potential(zone_map, total: int) -> int:
    """Subtract non-production files from a potential count.

    Uses the zone map's own file list — no need to pass files separately.
    No-op if zone_map is None (backward compat).
    """
    if zone_map is None:
        return total
    return max(total - zone_map.non_production_count(), 0)


def should_skip_finding(zone_map, filepath: str, detector: str) -> bool:
    """Check if a finding should be skipped based on zone policy.

    Returns True if the file's zone policy says to skip this detector.
    """
    if zone_map is None:
        return False
    zone = zone_map.get(filepath)
    policy = ZONE_POLICIES.get(zone)
    return policy is not None and detector in policy.skip_detectors


def filter_entries(zone_map, entries: list[dict], detector: str,
                   file_key: str = "file") -> list[dict]:
    """Filter detector entries by zone policy. No-op if zone_map is None.

    If file_key points to a list (e.g. cycle entries with "files"), checks
    the first element.
    """
    if zone_map is None:
        return entries

    def _get_path(entry):
        val = entry[file_key]
        return val[0] if isinstance(val, list) else val

    return [e for e in entries
            if not should_skip_finding(zone_map, _get_path(e), detector)]
