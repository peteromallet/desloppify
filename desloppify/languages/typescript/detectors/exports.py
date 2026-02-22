"""Dead exports detection via Knip."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.languages.typescript.detectors.knip_adapter import detect_with_knip
from desloppify.file_discovery import rel
from desloppify.utils import colorize, print_table


def detect_dead_exports(path: Path) -> tuple[list[dict], int]:
    """Return (dead_export_entries, total_exports) using Knip."""
    result = detect_with_knip(path)
    if result is None:
        return [], 0
    entries = result
    return entries, len(entries)


def cmd_exports(args: argparse.Namespace) -> None:
    print(colorize("Scanning exports via Knip...", "dim"), file=sys.stderr)
    entries, _ = detect_dead_exports(Path(args.path))
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(colorize("No dead exports found.", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    print(colorize(f"\nDead exports: {len(entries)} across {len(by_file)} files\n", "bold"))

    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
    rows = []
    for filepath, file_entries in sorted_files[: args.top]:
        names = ", ".join(e["name"] for e in file_entries[:5])
        if len(file_entries) > 5:
            names += f", ... (+{len(file_entries) - 5})"
        rows.append([rel(filepath), str(len(file_entries)), names])
    print_table(["File", "Count", "Exports"], rows, [55, 6, 50])
