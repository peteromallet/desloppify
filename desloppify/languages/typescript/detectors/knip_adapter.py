"""Knip adapter — dead exports detection via Knip.

Runs ``npx knip --reporter json`` as a subprocess and parses its JSON output
into the entry dicts expected by detect_dead_exports().

Knip understands re-exports, barrel files, dynamic imports, and entry points —
far more accurate than the old grep-based approach.

Returns None when Knip is not installed, so the caller gets [] findings rather
than a crash.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from desloppify.file_discovery import rel

logger = logging.getLogger(__name__)


def _run_knip(path: Path, timeout: int = 120) -> dict | None:
    """Run ``npx knip --reporter json`` and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            ["npx", "knip", "--reporter", "json", "--no-gitignore"],
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.debug("knip: npx not found")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("knip: timed out after %ds", timeout)
        return None
    except OSError as exc:
        logger.debug("knip: OSError: %s", exc)
        return None

    stdout = result.stdout.strip()
    if not stdout:
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.debug("knip: JSON parse error: %s", exc)
        return None


def _normalize_path(raw: str, scan_path: Path) -> str:
    """Return a path relative to PROJECT_ROOT, scoped to scan_path."""
    p = Path(raw)
    if not p.is_absolute():
        p = (scan_path / p).resolve()
    try:
        p.relative_to(scan_path.resolve())
    except ValueError:
        return ""
    return rel(str(p))


def detect_with_knip(path: Path) -> list[dict] | None:
    """Run Knip and return export entries, or None if Knip is unavailable.

    Each entry: {"file": str, "name": str, "line": int, "kind": "export"|"type"}
    """
    data = _run_knip(path)
    if data is None:
        return None

    entries: list[dict] = []

    for issue in data.get("issues", []):
        raw_file = issue.get("file", "")
        norm = _normalize_path(raw_file, path)
        if not norm:
            continue

        for export in issue.get("exports", []):
            name = export.get("name", "")
            if not name:
                continue
            raw_pos = export.get("pos", {})
            if isinstance(raw_pos, dict):
                start = raw_pos.get("start", {})
                line = start.get("line", 0) if isinstance(start, dict) else (start if isinstance(start, int) else 0)
            elif isinstance(raw_pos, int):
                line = raw_pos
            else:
                line = 0
            entries.append({"file": norm, "name": name, "line": line, "kind": "export"})

        for export in issue.get("types", []):
            name = export.get("name", "")
            if not name:
                continue
            raw_pos = export.get("pos", {})
            if isinstance(raw_pos, dict):
                start = raw_pos.get("start", {})
                line = start.get("line", 0) if isinstance(start, dict) else (start if isinstance(start, int) else 0)
            elif isinstance(raw_pos, int):
                line = raw_pos
            else:
                line = 0
            entries.append({"file": norm, "name": name, "line": line, "kind": "type"})

    logger.debug("knip: %d dead exports", len(entries))
    return entries
