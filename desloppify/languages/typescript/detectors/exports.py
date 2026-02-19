"""Dead exports detection (zero external importers)."""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.languages.typescript.detectors.deps import _FRAMEWORK_EXTENSIONS
from desloppify.utils import (
    SRC_PATH,
    c,
    find_source_files,
    find_ts_files,
    grep_files,
    grep_files_containing,
    print_table,
    rel,
    resolve_path,
)

EXPORT_DECL_RE = re.compile(
    r"^export\s+(?:declare\s+)?(?:const|let|function|class|type|interface|enum)\s+(\w+)",
    re.MULTILINE,
)

_EXPORT_GREP_PAT = (
    r"^export\s+(declare\s+)?(const|let|function|class|type|interface|enum)\s+\w+"
)


def _build_reference_index(search_path: Path, names: set[str]) -> dict[str, set[str]]:
    """Build a map of symbol name -> set of files that contain it (word-boundary match)."""
    if not names:
        return {}
    ts_files = find_ts_files(search_path)
    # Also search framework files that may reference these exports
    fw_files = find_source_files(search_path, list(_FRAMEWORK_EXTENSIONS))
    all_files = ts_files + fw_files
    raw = grep_files_containing(names, all_files, word_boundary=True)
    # Convert to resolved paths for comparison
    return {name: {resolve_path(f) for f in files} for name, files in raw.items()}


def detect_dead_exports(path: Path) -> tuple[list[dict], int]:
    # Phase 1: Find all export declarations in the scoped path
    ts_files = find_ts_files(path)
    hits = grep_files(_EXPORT_GREP_PAT, ts_files)

    exports = []
    for filepath, lineno, content in hits:
        basename = Path(filepath).name
        if basename in ("index.ts", "index.tsx"):
            continue
        m = EXPORT_DECL_RE.search(content)
        if not m:
            continue
        name = m.group(1)
        if len(name) <= 2:
            continue
        exports.append({"file": filepath, "line": lineno, "name": name})

    total_exports = len(exports)
    if not exports:
        return [], 0

    # Phase 2: Build reference index from full src/ (not just --path scope)
    all_names = {e["name"] for e in exports}
    print(
        c(
            f"  Checking {len(all_names)} unique names across {rel(str(SRC_PATH))}...",
            "dim",
        ),
        file=sys.stderr,
    )
    ref_index = _build_reference_index(SRC_PATH, all_names)

    # Phase 3: Check each export against the reference index
    dead = []
    for exp in exports:
        declaring_resolved = resolve_path(exp["file"])
        references = ref_index.get(exp["name"], set())
        external_refs = references - {declaring_resolved}
        if not external_refs:
            dead.append(exp)

    return dead, total_exports


def cmd_exports(args: argparse.Namespace) -> None:
    print(c("Scanning exports...", "dim"), file=sys.stderr)
    entries, _ = detect_dead_exports(Path(args.path))
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(c("No dead exports found.", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    print(c(f"\nDead exports: {len(entries)} across {len(by_file)} files\n", "bold"))

    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
    rows = []
    for filepath, file_entries in sorted_files[: args.top]:
        names = ", ".join(e["name"] for e in file_entries[:5])
        if len(file_entries) > 5:
            names += f", ... (+{len(file_entries) - 5})"
        rows.append([rel(filepath), str(len(file_entries)), names])
    print_table(["File", "Count", "Exports"], rows, [55, 6, 50])
