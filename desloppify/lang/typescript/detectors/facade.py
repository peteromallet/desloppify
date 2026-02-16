"""TypeScript facade detection helpers."""

from __future__ import annotations

import re
from pathlib import Path


def is_ts_facade(filepath: str) -> dict | None:
    """Check if a TypeScript file is a pure re-export facade."""
    try:
        content = Path(filepath).read_text()
        lines = content.splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    if not lines:
        return None

    imports_from: list[str] = []
    export_re = re.compile(r"""^export\s+(?:\{[^}]*\}|\*)\s+from\s+['"]([^'"]+)['"]""")
    reexport_re = re.compile(r"""^export\s+(?:type\s+)?\{[^}]*\}\s+from\s+['"]([^'"]+)['"]""")

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        m = export_re.match(stripped) or reexport_re.match(stripped)
        if m:
            imports_from.append(m.group(1))
            continue

        return None

    if not imports_from:
        return None

    return {"imports_from": imports_from, "loc": len(lines)}


def detect_reexport_facades(
    graph: dict,
    *,
    max_importers: int = 2,
) -> tuple[list[dict], int]:
    """Detect TypeScript re-export facade files."""
    entries: list[dict] = []
    total_checked = 0

    for filepath in graph:
        total_checked += 1
        importer_count = graph[filepath].get("importer_count", 0)
        if importer_count > max_importers:
            continue

        result = is_ts_facade(filepath)
        if result:
            entries.append(
                {
                    "file": filepath,
                    "loc": result["loc"],
                    "importers": importer_count,
                    "imports_from": result["imports_from"],
                    "kind": "file",
                }
            )

    return sorted(entries, key=lambda e: (e["kind"], e["importers"], -e["loc"])), total_checked

