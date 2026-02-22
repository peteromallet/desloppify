"""Unused declarations detection via tsc TS6133/TS6192.

Includes a Deno/edge-functions fallback where `tsc` cannot model URL-based imports.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import (
    find_ts_files,
    read_file_text,
    rel,
    resolve_path,
    safe_write_text,
)
from desloppify.core._internal.text_utils import strip_c_style_comments
from desloppify.utils import colorize, print_table

TS6133_RE = re.compile(
    r"^(.+)\((\d+),(\d+)\): error TS6133: '(\S+)' is declared but its value is never read\."
)
TS6192_RE = re.compile(
    r"^(.+)\((\d+),(\d+)\): error TS6192: All imports in import declaration are unused\."
)
_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_DENO_IMPORT_RE = re.compile(
    r"""(?:from\s+['"](?:https://(?:deno\.land|esm\.sh)|npm:|jsr:)|^\s*import\s+['"](?:https://(?:deno\.land|esm\.sh)|npm:|jsr:))"""
)
_DECL_RE = re.compile(
    r"^\s*(export\s+)?(?:const|let|var|function|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"
)
logger = logging.getLogger(__name__)


def _identifier_occurrences(content: str, name: str) -> int:
    pat = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])")
    return len(pat.findall(content))


def _extract_import_names(line: str) -> list[str]:
    """Return local identifier names declared by an import line."""
    if " from " not in line:
        return []

    left = line.split(" from ", 1)[0].strip()
    if not left.startswith("import "):
        return []

    clause = left[len("import ") :].strip()
    if clause.startswith("type "):
        clause = clause[len("type ") :].strip()
    if not clause:
        return []

    names: list[str] = []
    star_match = re.search(r"\*\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)", clause)
    if star_match:
        names.append(star_match.group(1))

    # Default import (e.g., import Foo, {bar} from "x")
    default_part = clause.split(",", 1)[0].strip()
    if default_part and not default_part.startswith("{") and not default_part.startswith(
        "*"
    ):
        if _IDENT_RE.match(default_part):
            names.append(default_part)

    # Named imports
    for block in re.findall(r"\{([^}]*)\}", clause):
        for item in block.split(","):
            token = item.strip()
            if not token:
                continue
            if token.startswith("type "):
                token = token[len("type ") :].strip()
            alias = re.split(r"\s+as\s+", token)
            local_name = alias[-1].strip()
            if _IDENT_RE.match(local_name):
                names.append(local_name)

    # Preserve stable order while deduping.
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped


def _detect_unused_fallback(path: Path, category: str) -> tuple[list[dict], int]:
    """Conservative source-based fallback for Deno/edge TS projects."""
    files = find_ts_files(path)
    entries: list[dict] = []

    for filepath in files:
        full = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        raw = read_file_text(str(full))
        if raw is None:
            continue
        code = strip_c_style_comments(raw)
        lines = raw.splitlines()

        # Import-based unused checks.
        if category in {"all", "imports"}:
            for lineno, line in enumerate(lines, 1):
                if line.lstrip() != line:
                    continue
                if not line.strip().startswith("import "):
                    continue
                for name in _extract_import_names(line):
                    if name.startswith("_"):
                        continue
                    if _identifier_occurrences(code, name) <= 1:
                        entries.append(
                            {
                                "file": filepath,
                                "line": lineno,
                                "col": max(1, line.find(name) + 1),
                                "name": name,
                                "category": "imports",
                            }
                        )

        # Top-level variable/function/class declarations (non-exported only).
        if category in {"all", "vars"}:
            for lineno, line in enumerate(lines, 1):
                if line.lstrip() != line:
                    continue
                m = _DECL_RE.match(line)
                if not m:
                    continue
                exported, name = m.group(1), m.group(2)
                if exported or name.startswith("_"):
                    continue
                if _identifier_occurrences(code, name) <= 1:
                    entries.append(
                        {
                            "file": filepath,
                            "line": lineno,
                            "col": max(1, line.find(name) + 1),
                            "name": name,
                            "category": "vars",
                        }
                    )

    return entries, len(files)


def _contains_deno_markers(path: Path) -> bool:
    markers = ("deno.json", "deno.jsonc", "import_map.json", "deno.lock")
    current = path.resolve()
    root = PROJECT_ROOT.resolve()
    for parent in (current, *current.parents):
        for marker in markers:
            if (parent / marker).is_file():
                return True
        if parent == root:
            break
    return False


def _has_deno_import_syntax(ts_files: list[str]) -> bool:
    for filepath in ts_files:
        full = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        content = read_file_text(str(full))
        if content and _DENO_IMPORT_RE.search(content):
            return True
    return False


def _should_use_deno_fallback(path: Path, ts_files: list[str]) -> bool:
    normalized = path.resolve().as_posix().lower()
    if normalized.endswith("/supabase/functions") or "/supabase/functions/" in normalized:
        return True
    if _contains_deno_markers(path):
        return True
    return _has_deno_import_syntax(ts_files)


def detect_unused(path: Path, category: str = "all") -> tuple[list[dict], int]:
    ts_files = find_ts_files(path)
    total_files = len(ts_files)
    if _should_use_deno_fallback(path, ts_files):
        return _detect_unused_fallback(path, category)

    # Create a temporary tsconfig that enables declaration-read checks
    # (the project tsconfig keeps declaration-read checks disabled)
    tmp_tsconfig = {
        "extends": "./tsconfig.app.json",
        "compilerOptions": {
            "noUnusedLocals": True,
            "noUnusedParameters": True,
        },
    }
    tmp_path = PROJECT_ROOT / "tsconfig.desloppify.json"
    try:
        safe_write_text(tmp_path, json.dumps(tmp_tsconfig, indent=2))
        try:
            result = subprocess.run(
                ["npx", "tsc", "--project", str(tmp_path), "--noEmit"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
                timeout=120,
                shell=(sys.platform == "win32"),
            )
        except (subprocess.SubprocessError, OSError) as exc:
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
            # Skip _ prefixed names (intentionally unused by convention)
            if name.startswith("_"):
                continue
        else:
            filepath, lineno, col = m2.group(1), int(m2.group(2)), int(m2.group(3))
            name = "(entire import)"
        # Scope to requested path
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
        p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        lines = p.read_text().splitlines()
        if lineno <= len(lines):
            src_line = lines[lineno - 1].strip()
            if (
                src_line.startswith("import ")
                or "from '" in src_line
                or 'from "' in src_line
            ):
                return "imports"
            # If the line starts with a declaration keyword, it's definitely not an import
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
            # Walk back to check if this line is within a multi-line import block
            for back in range(1, 10):
                idx = lineno - 1 - back
                if idx < 0:
                    break
                prev = lines[idx].strip()
                if prev.startswith("import "):
                    return "imports"
                # Stop at blank lines or non-import-continuation lines
                if not prev or (
                    not prev.startswith("{")
                    and not prev.startswith(",")
                    and "," not in prev
                ):
                    break
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("Unable to read %s for unused categorization: %s", filepath, exc)
        return "imports"  # Safer fallback — import fixers are less destructive.
    return "imports"


def cmd_unused(args: argparse.Namespace) -> None:
    if _should_use_deno_fallback(Path(args.path), find_ts_files(Path(args.path))):
        print(
            colorize(
                "Deno/edge TypeScript context detected — using source-based unused scan",
                "dim",
            ),
            file=sys.stderr,
        )
    else:
        print(colorize("Running tsc... (this may take a moment)", "dim"), file=sys.stderr)
    entries, _ = detect_unused(Path(args.path), args.category)
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(colorize("No unused declarations found.", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    by_cat: dict[str, int] = defaultdict(int)
    for e in entries:
        by_cat[e["category"]] += 1

    print(
        colorize(
            f"\nUnused declarations: {len(entries)} across {len(by_file)} files\n",
            "bold",
        )
    )

    print(colorize("By category:", "cyan"))
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print()

    print(colorize("Top files:", "cyan"))
    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
    rows = []
    for filepath, file_entries in sorted_files[: args.top]:
        names = ", ".join(e["name"] for e in file_entries[:5])
        if len(file_entries) > 5:
            names += f", ... (+{len(file_entries) - 5})"
        rows.append([rel(filepath), str(len(file_entries)), names])
    print_table(["File", "Count", "Names"], rows, [55, 6, 50])
