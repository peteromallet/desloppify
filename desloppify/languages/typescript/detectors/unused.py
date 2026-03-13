"""Unused declarations detection via tsc TS6133/TS6192.

Includes a Deno/edge-functions fallback where `tsc` cannot model URL-based imports.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess  # nosec B404
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.base.discovery.file_paths import rel, resolve_path, safe_write_text
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.discovery.source import find_ts_and_tsx_files
from desloppify.base.output.terminal import colorize, print_table
from desloppify.languages.typescript.detectors.unused_fallback import (
    _contains_deno_markers,
    _extract_import_names,
    _has_deno_import_syntax,
    _identifier_occurrences,
    detect_unused_fallback,
    should_use_deno_fallback,
)

TS6133_RE = re.compile(
    r"^(.+)\((\d+),(\d+)\): error TS6133: '(\S+)' is declared but its value is never read\."
)
TS6192_RE = re.compile(
    r"^(.+)\((\d+),(\d+)\): error TS6192: All imports in import declaration are unused\."
)
logger = logging.getLogger(__name__)
_proc_runtime = subprocess

# Compatibility aliases for external callers/tests that imported private names.
_detect_unused_fallback = detect_unused_fallback
_should_use_deno_fallback = should_use_deno_fallback


def _run_tsc_unused_check(
    project_root: Path,
    tsconfig_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the unused-symbol check for one project root.

    Prefers `npx tsc` (project-local), then `node_modules/.bin/tsc`, then `tsc`.
    """
    npx_path = shutil.which("npx")
    if npx_path:
        cmd = [npx_path, "tsc"]
    else:
        local_tsc = project_root / "node_modules" / ".bin" / "tsc"
        if local_tsc.is_file():
            cmd = [str(local_tsc)]
        else:
            tsc_path = shutil.which("tsc")
            if tsc_path:
                cmd = [tsc_path]
            else:
                raise OSError("TypeScript compiler not found (npx/tsc)")

    return _proc_runtime.run(  # nosec B603
        [
            *cmd,
            "--project",
            str(tsconfig_path),
            "--noEmit",
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=120,
    )


def detect_unused(path: Path, category: str = "all") -> tuple[list[dict], int]:
    ts_files = find_ts_and_tsx_files(path)
    total_files = len(ts_files)
    if _should_use_deno_fallback(path, ts_files):
        return _detect_unused_fallback(path, category)

    tmp_tsconfig = {
        "extends": "./tsconfig.app.json",
        "compilerOptions": {
            "noUnusedLocals": True,
            "noUnusedParameters": True,
        },
    }
    tmp_path = get_project_root() / "tsconfig.desloppify.json"
    try:
        safe_write_text(tmp_path, json.dumps(tmp_tsconfig, indent=2))
        try:
            result = _run_tsc_unused_check(get_project_root(), tmp_path)
        except (_proc_runtime.SubprocessError, OSError) as exc:
            logger.debug("Falling back to source-based unused detection: %s", exc)
            return _detect_unused_fallback(path, category)
    finally:
        tmp_path.unlink(missing_ok=True)

    entries = []
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        m = TS6133_RE.match(line)
        m2 = TS6192_RE.match(line) if not m else None
        if not m and not m2:
            continue
        if m:
            filepath, lineno, col, name = (
                m.group(1),
                int(m.group(2)),
                int(m.group(3)),
                m.group(4),
            )
            if name.startswith("_"):
                continue
        else:
            filepath, lineno, col = m2.group(1), int(m2.group(2)), int(m2.group(3))
            name = "(entire import)"

        try:
            full = Path(resolve_path(filepath))
            if not str(full).startswith(str(path.resolve())):
                continue
        except (OSError, ValueError) as exc:
            logger.debug("Skipping path scope check for %s: %s", filepath, exc)
            continue

        cat = _categorize_unused(filepath, lineno)
        if category != "all" and cat != category:
            continue
        entries.append(
            {
                "file": filepath,
                "line": lineno,
                "col": col,
                "name": name,
                "category": cat,
            }
        )
    return entries, total_files


def _categorize_unused(filepath: str, lineno: int) -> str:
    try:
        p = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
        lines = p.read_text().splitlines()
        if lineno <= len(lines):
            src_line = lines[lineno - 1].strip()
            if src_line.startswith("import ") or "from '" in src_line or 'from "' in src_line:
                return "imports"
            if src_line.startswith(
                (
                    "const ",
                    "let ",
                    "var ",
                    "export ",
                    "function ",
                    "class ",
                    "type ",
                    "interface ",
                )
            ):
                return "vars"
            for back in range(1, 10):
                idx = lineno - 1 - back
                if idx < 0:
                    break
                prev = lines[idx].strip()
                if prev.startswith("import "):
                    return "imports"
                if not prev or (
                    not prev.startswith("{") and not prev.startswith(",") and "," not in prev
                ):
                    break
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("Unable to read %s for unused categorization: %s", filepath, exc)
        return "imports"
    return "imports"


def cmd_unused(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if _should_use_deno_fallback(path, find_ts_and_tsx_files(path)):
        print(
            colorize(
                "Deno/edge TypeScript context detected — using source-based unused scan",
                "dim",
            ),
            file=sys.stderr,
        )
    else:
        print(colorize("Running tsc... (this may take a moment)", "dim"), file=sys.stderr)

    entries, _ = detect_unused(path, args.category)
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(colorize("No unused declarations found.", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for entry in entries:
        by_file[entry["file"]].append(entry)

    by_cat: dict[str, int] = defaultdict(int)
    for entry in entries:
        by_cat[entry["category"]] += 1

    print(
        colorize(
            f"\nUnused declarations: {len(entries)} across {len(by_file)} files\n",
            "bold",
        )
    )

    print(colorize("By category:", "cyan"))
    for cat, count in sorted(by_cat.items(), key=lambda item: -item[1]):
        print(f"  {cat}: {count}")
    print()

    print(colorize("Top files:", "cyan"))
    sorted_files = sorted(by_file.items(), key=lambda item: -len(item[1]))
    rows = []
    for filepath, file_entries in sorted_files[: args.top]:
        names = ", ".join(entry["name"] for entry in file_entries[:5])
        if len(file_entries) > 5:
            names += f", ... (+{len(file_entries) - 5})"
        rows.append([rel(filepath), str(len(file_entries)), names])
    print_table(["File", "Count", "Names"], rows, [55, 6, 50])


__all__ = [
    "TS6133_RE",
    "TS6192_RE",
    "_categorize_unused",
    "_contains_deno_markers",
    "_detect_unused_fallback",
    "_extract_import_names",
    "_has_deno_import_syntax",
    "_identifier_occurrences",
    "_should_use_deno_fallback",
    "cmd_unused",
    "detect_unused",
]
