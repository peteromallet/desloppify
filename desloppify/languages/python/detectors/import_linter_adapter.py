"""Detect architectural layer violations via import-linter.

Reads `.importlinter` config from the scanned project's root (walking up
from the scan path to find the first `.importlinter` file, stopping at `.git`
boundaries). Falls back gracefully to None when lint-imports is not installed
or no config is found.

See https://import-linter.readthedocs.io for config format.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_BROKEN_CONTRACT_RE = re.compile(r"Broken contract '([^']+)'")
# import-linter outputs violations as "  module.a imports module.b"
_VIOLATION_IMPORTS_RE = re.compile(r"^\s+(\S+)\s+imports\s+(\S+)\s*$")
# Also handle "  module.a -> module.b" format (arrow notation)
_VIOLATION_ARROW_RE = re.compile(r"^\s+(\S+)\s+->\s+(\S+)\s*$")


def _find_importlinter_root(path: Path) -> Path | None:
    """Walk up from path to find the directory containing .importlinter.

    Stops when a .git boundary or the filesystem root is encountered.
    """
    candidate = path.resolve()
    for directory in [candidate, *candidate.parents]:
        if (directory / ".importlinter").exists():
            return directory
        # Stop at project root boundaries
        if (directory / ".git").exists() or directory.parent == directory:
            break
    return None


def _module_to_file(module: str) -> str:
    """Convert dotted module name to a relative file path."""
    return module.replace(".", "/") + ".py"


def detect_with_import_linter(path: Path) -> list[dict] | None:
    """Run lint-imports and return layer violation entries, or None on failure."""
    config_dir = _find_importlinter_root(path)
    if config_dir is None:
        logger.debug("import-linter: no .importlinter config found — skipping")
        return None

    try:
        result = subprocess.run(
            ["lint-imports"],
            capture_output=True,
            text=True,
            cwd=config_dir,
            timeout=60,
        )
    except FileNotFoundError:
        logger.debug("import-linter: lint-imports not found — skipping")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("import-linter: timed out")
        return None

    if result.returncode == 0:
        return []

    output = result.stdout + result.stderr
    if not output.strip():
        return []

    entries: list[dict] = []
    current_contract: str | None = None

    for line in output.splitlines():
        m_contract = _BROKEN_CONTRACT_RE.search(line)
        if m_contract:
            current_contract = m_contract.group(1)
            continue

        if current_contract is None:
            continue

        m_viol = _VIOLATION_IMPORTS_RE.match(line) or _VIOLATION_ARROW_RE.match(line)
        if not m_viol:
            continue

        source_mod = m_viol.group(1)
        target_mod = m_viol.group(2)
        source_file = _module_to_file(source_mod)
        source_pkg = source_mod.rsplit(".", 1)[-1] if "." in source_mod else source_mod

        entries.append(
            {
                "file": source_file,
                "line": 0,
                "summary": (
                    f"Layer violation: {source_mod} -> {target_mod}"
                    f" (contract: {current_contract})"
                ),
                "confidence": "high",
                "source_pkg": source_pkg,
                "target_pkg": target_mod,
            }
        )

    return entries


__all__ = ["detect_with_import_linter"]
