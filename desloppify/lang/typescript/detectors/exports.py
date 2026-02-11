"""Dead exports detection (zero external importers)."""

import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, SRC_PATH, c, print_table, rel, resolve_path


EXPORT_DECL_RE = re.compile(
    r"^export\s+(?:declare\s+)?(?:const|let|function|class|type|interface|enum)\s+(\w+)",
    re.MULTILINE,
)


def _build_reference_index(search_path: Path, names: set[str]) -> dict[str, set[str]]:
    """Build a map of symbol name -> set of files that contain it (word-boundary match).

    Uses grep -Fw with a pattern file for a single efficient pass.
    """
    if not names:
        return {}
    # Write all names to a temp file for grep -Fw
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(sorted(names)))
        patterns_file = f.name
    try:
        result = subprocess.run(
            ["grep", "-rlFw", "--include=*.ts", "--include=*.tsx",
             "-f", patterns_file, str(search_path)],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        # -Fw gives us files that match ANY pattern. We need per-name file lists.
        # So we do a second pass: for each matching file, grep for which names it contains.
        matching_files = [f for f in result.stdout.strip().splitlines() if f]
        if not matching_files:
            return {}

        name_to_files: dict[str, set[str]] = defaultdict(set)
        # For each matching file, find which of our names it references
        # Batch: grep -oFw from the patterns file against each file
        for filepath in matching_files:
            res = subprocess.run(
                ["grep", "-oFw", "-f", patterns_file, filepath],
                capture_output=True, text=True, cwd=PROJECT_ROOT,
            )
            resolved = resolve_path(filepath)
            for match_name in set(res.stdout.strip().splitlines()):
                if match_name in names:
                    name_to_files[match_name].add(resolved)
        return name_to_files
    finally:
        os.unlink(patterns_file)


def detect_dead_exports(path: Path) -> tuple[list[dict], int]:
    # Phase 1: Find all export declarations in the scoped path
    result = subprocess.run(
        ["grep", "-rn", "--include=*.ts", "--include=*.tsx", "-E",
         r"^export\s+(declare\s+)?(const|let|function|class|type|interface|enum)\s+\w+",
         str(path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    exports = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        filepath, lineno, content = parts[0], parts[1], parts[2]
        basename = Path(filepath).name
        if basename in ("index.ts", "index.tsx"):
            continue
        m = EXPORT_DECL_RE.search(content)
        if not m:
            continue
        name = m.group(1)
        if len(name) <= 2:
            continue
        exports.append({"file": filepath, "line": int(lineno), "name": name})

    total_exports = len(exports)
    if not exports:
        return [], 0

    # Phase 2: Build reference index from full src/ (not just --path scope)
    all_names = {e["name"] for e in exports}
    print(c(f"  Checking {len(all_names)} unique names across {rel(str(SRC_PATH))}...", "dim"), file=sys.stderr)
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


def cmd_exports(args):
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
