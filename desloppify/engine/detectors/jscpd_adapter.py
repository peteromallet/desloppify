"""Detect repeated code blocks via jscpd.

Replaces boilerplate_duplication.py with a thin adapter around jscpd
(https://github.com/kucherenko/jscpd), which uses proper per-language
tokenisation and supports type-2 clones (renamed identifiers).

Falls back gracefully to None when jscpd/npx is not installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_jscpd_report(report: dict, scan_path: Path) -> list[dict]:
    """Parse a jscpd JSON report dict and return clustered duplication entries.

    Clusters pairwise duplicates that share the same fragment into multi-file
    groups, producing the same output shape as the old boilerplate_duplication
    detector so that phase_boilerplate_duplication() needs no further changes.
    """
    duplicates = report.get("duplicates", [])
    if not duplicates:
        return []

    path_resolved = scan_path.resolve()

    # Cluster pairs by SHA1(fragment.strip()[:200])[:16]
    clusters: dict[str, dict] = {}

    for dup in duplicates:
        fragment = dup.get("fragment", "")
        fragment_key = hashlib.sha1(
            fragment.strip()[:200].encode("utf-8", errors="replace")
        ).hexdigest()[:16]

        first = dup.get("firstFile", {})
        second = dup.get("secondFile", {})
        first_name = first.get("name", "")
        second_name = second.get("name", "")

        # Skip pairs where either file is outside the scan path
        valid_pair = True
        for name in (first_name, second_name):
            if not name:
                valid_pair = False
                break
            try:
                if not Path(name).resolve().is_relative_to(path_resolved):
                    valid_pair = False
                    break
            except (ValueError, OSError):
                valid_pair = False
                break
        if not valid_pair:
            continue

        lines = dup.get("lines", 0)
        if fragment_key not in clusters:
            clusters[fragment_key] = {
                "id": fragment_key,
                "lines": lines,
                "fragment": fragment,
                "files": {},
            }

        cluster = clusters[fragment_key]
        for name, info in [(first_name, first), (second_name, second)]:
            if name not in cluster["files"]:
                cluster["files"][name] = info.get("start", 0)

    entries: list[dict] = []
    for fragment_key, cluster in clusters.items():
        files = cluster["files"]
        locations = [
            {"file": f, "line": line}
            for f, line in sorted(files.items(), key=lambda kv: kv[0])
        ]
        entries.append(
            {
                "id": cluster["id"],
                "distinct_files": len(files),
                "window_size": cluster["lines"],
                "locations": locations,
                "sample": cluster["fragment"].splitlines()[:4],
            }
        )

    entries.sort(key=lambda e: (-e["distinct_files"], e["id"]))
    return entries


def detect_with_jscpd(path: Path) -> list[dict] | None:
    """Run jscpd on *path* and return duplication entries, or None on failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run(
                [
                    "npx",
                    "--yes",
                    "jscpd",
                    str(path),
                    "--reporters",
                    "json",
                    "--output",
                    tmpdir,
                    "--min-lines",
                    "4",
                    "--min-tokens",
                    "50",
                    "--ignore",
                    "**/node_modules/**,**/.git/**,**/__pycache__/**,**/.venv*/**,**/venv/**",
                    "--silent",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            logger.debug("jscpd: npx not found — skipping boilerplate duplication detection")
            return None
        except OSError as exc:
            logger.debug("jscpd: OS error running npx/jscpd: %s", exc)
            return None
        except subprocess.TimeoutExpired:
            logger.debug("jscpd: timed out")
            return None

        report_file = Path(tmpdir) / "jscpd-report.json"
        if not report_file.exists():
            logger.debug("jscpd: no report file produced — assuming no duplicates")
            return []

        try:
            report = json.loads(report_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("jscpd: failed to parse report: %s", exc)
            return None

        return _parse_jscpd_report(report, path)


__all__ = ["_parse_jscpd_report", "detect_with_jscpd"]
