#!/usr/bin/env python3
"""CI Roslyn shim for C# integration tests.

This script emits Roslyn-like JSON payloads from the existing heuristic
C# dependency graph so integration tests can exercise the Roslyn command
path in a deterministic, self-contained way.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from desloppify.languages.csharp.detectors.deps import build_dep_graph


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: roslyn_stub.py <scan_path>", file=sys.stderr)
        return 2

    scan_path = Path(sys.argv[1]).resolve()

    # Prevent recursive invocation when this command is used via
    # DESLOPPIFY_CSHARP_ROSLYN_CMD inside build_dep_graph.
    os.environ.pop("DESLOPPIFY_CSHARP_ROSLYN_CMD", None)

    graph = build_dep_graph(scan_path)
    payload = {
        "files": [
            {
                "file": source,
                "imports": sorted(entry.get("imports", set())),
            }
            for source, entry in sorted(graph.items())
        ]
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
