"""Python smell detection via ruff (B/BLE/E/F/PGH/PLW/RUF/W-series rules).

Runs ``ruff check`` with a targeted rule set and maps each ruff code to a
desloppify smell ID. Produces smell entries in the same format as detect_smells()
so they flow through make_smell_findings() without any plumbing changes.

Falls back gracefully to [] when ruff is not installed.

Rules (non-overlapping with remaining custom smells in smells.py):
  B006     – mutable default argument (replaces regex in smells.py)
  B007     – unused loop control variable
  B023     – function definition does not bind loop variable
  B026     – star-arg after keyword argument
  B904     – raise inside except without ``from err``
  BLE001   – blind exception catch (replaces broad_except regex)
  E711     – comparison to None with == / !=
  E712     – comparison to True/False with == / !=
  E722     – bare except (replaces bare_except regex)
  F403     – star import (replaces star_import regex; keep star_import_no_all AST)
  PGH003   – blanket type: ignore (replaces type_ignore regex)
  PLW0603  – global keyword (replaces global_keyword regex)
  RUF012   – mutable class variable (replaces AST mutable_class_var)
  W605     – invalid escape sequence (e.g. "\\d" instead of r"\\d")
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.core.discovery_api import (
    collect_exclude_dirs as _collect_exclude_dirs,
)
from desloppify.core.discovery_api import (
    get_exclusions as _get_exclusions,
)
from desloppify.core.discovery_api import (
    matches_exclusion as _matches_exclusion,
)

logger = logging.getLogger(__name__)

# Maps ruff code → (smell_id, label, severity)
_RULE_MAP: dict[str, tuple[str, str, str]] = {
    "B006": ("mutable_default", "Mutable default argument (list/dict/set literal)", "high"),
    "B007": ("unused_loop_var", "Unused loop control variable", "medium"),
    "B023": ("func_in_loop", "Function definition doesn't bind loop variable", "high"),
    "B026": ("star_after_keyword", "Star-arg unpacking after keyword argument", "high"),
    "B904": ("raise_without_from", "Raise inside except without `from err`", "medium"),
    "BLE001": ("broad_except", "Broad except — check library exceptions before narrowing", "medium"),
    "E711": ("none_comparison", "Comparison to None with == / !=  (use `is`)", "medium"),
    "E712": ("bool_comparison", "Comparison to True/False with == / != (use `is`)", "low"),
    "E722": ("bare_except", "Bare except clause (catches everything including SystemExit)", "high"),
    "F403": ("star_import", "Star import (from X import *)", "medium"),
    "PGH003": ("type_ignore", "type: ignore comment", "medium"),
    "PLW0603": ("global_keyword", "Global keyword usage", "medium"),
    "RUF012": ("mutable_class_var", "Class-level mutable default (shared across instances)", "high"),
    "W605": ("invalid_escape", "Invalid escape sequence (use raw string or \\\\)", "medium"),
}

_SELECT = ",".join(_RULE_MAP)


def detect_with_ruff_smells(path: Path) -> list[dict] | None:
    """Run ruff on supplemental B/E/W rules and return smell entries, or None on failure.

    Each entry matches the format expected by make_smell_findings():
        {
            "id": smell_id,
            "label": label,
            "severity": "high"|"medium"|"low",
            "matches": [{"file": str, "line": int}, ...],
        }
    """
    exclude_dirs = _collect_exclude_dirs(path)
    cmd = [
        "ruff",
        "check",
        "--select",
        _SELECT,
        "--output-format",
        "json",
        "--no-fix",
    ]
    if exclude_dirs:
        cmd.extend(["--exclude", ",".join(exclude_dirs)])
    cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60,
        )
    except FileNotFoundError:
        logger.debug("ruff smells: ruff not found — skipping supplemental smell detection")
        return None
    except OSError as exc:
        logger.debug("ruff smells: OS error running ruff: %s", exc)
        return None
    except subprocess.TimeoutExpired:
        logger.debug("ruff smells: timed out")
        return None

    stdout = result.stdout.strip()
    if not stdout:
        return []

    try:
        diagnostics: list[dict] = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.debug("ruff smells: JSON parse error: %s", exc)
        return None

    exclusions = _get_exclusions()

    # Group diagnostics by (code, file) → list of matches.
    # Then convert to smell entry format.
    by_code_file: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for diag in diagnostics:
        code = diag.get("code", "")
        if code not in _RULE_MAP:
            continue
        filepath = diag.get("filename", "")
        if not filepath:
            continue
        if exclusions and any(_matches_exclusion(filepath, ex) for ex in exclusions):
            continue
        location = diag.get("location", {})
        line = location.get("row", 0) if isinstance(location, dict) else 0
        by_code_file[(code, filepath)].append({"file": filepath, "line": line})

    # Aggregate by code across all files.
    by_code: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for (code, filepath), matches in by_code_file.items():
        by_code[code][filepath].extend(matches)

    entries: list[dict] = []
    for code, files in by_code.items():
        smell_id, label, severity = _RULE_MAP[code]
        all_matches = [m for ms in files.values() for m in ms]
        entries.append(
            {
                "id": smell_id,
                "label": label,
                "severity": severity,
                "matches": all_matches,
            }
        )

    logger.debug("ruff smells: %d supplemental smell entries", len(entries))
    return entries
