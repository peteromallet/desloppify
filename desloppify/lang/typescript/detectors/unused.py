"""Unused declarations detection via tsc TS6133/TS6192."""

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, c, print_table, rel, resolve_path


TS6133_RE = re.compile(r"^(.+)\((\d+),(\d+)\): error TS6133: '(\S+)' is declared but its value is never read\.")
TS6192_RE = re.compile(r"^(.+)\((\d+),(\d+)\): error TS6192: All imports in import declaration are unused\.")


def detect_unused(path: Path, category: str = "all") -> tuple[list[dict], int]:
    # Create a temporary tsconfig that enables unused detection
    # (the project tsconfig has noUnusedLocals/Parameters: false)
    tmp_tsconfig = {
        "extends": "./tsconfig.app.json",
        "compilerOptions": {
            "noUnusedLocals": True,
            "noUnusedParameters": True,
        },
    }
    tmp_path = PROJECT_ROOT / "tsconfig.desloppify.json"
    try:
        tmp_path.write_text(json.dumps(tmp_tsconfig, indent=2))
        result = subprocess.run(
            ["npx", "tsc", "--project", str(tmp_path), "--noEmit"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    from ....utils import find_ts_files
    total_files = len(find_ts_files(path))
    entries = []
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        m = TS6133_RE.match(line)
        m2 = TS6192_RE.match(line) if not m else None
        if not m and not m2:
            continue
        if m:
            filepath, lineno, col, name = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
            # Skip _ prefixed names (intentionally unused by convention)
            if name.startswith('_'):
                continue
        else:
            filepath, lineno, col = m2.group(1), int(m2.group(2)), int(m2.group(3))
            name = "(entire import)"
        # Scope to requested path
        try:
            full = Path(resolve_path(filepath))
            if not str(full).startswith(str(path.resolve())):
                continue
        except (OSError, ValueError):
            continue
        cat = _categorize_unused(filepath, lineno)
        if category != "all" and cat != category:
            continue
        entries.append({"file": filepath, "line": lineno, "col": col, "name": name, "category": cat})
    return entries, total_files


def _categorize_unused(filepath: str, lineno: int) -> str:
    try:
        p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        lines = p.read_text().splitlines()
        if lineno <= len(lines):
            src_line = lines[lineno - 1].strip()
            if src_line.startswith("import ") or "from '" in src_line or 'from "' in src_line:
                return "imports"
            # If the line starts with a declaration keyword, it's definitely not an import
            if src_line.startswith(("const ", "let ", "var ", "export ", "function ", "class ", "type ", "interface ")):
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
                if not prev or (not prev.startswith("{") and not prev.startswith(",") and "," not in prev):
                    break
    except (OSError, UnicodeDecodeError):
        pass
    return "vars"


def cmd_unused(args):
    print(c("Running tsc... (this may take a moment)", "dim"), file=sys.stderr)
    entries, _ = detect_unused(Path(args.path), args.category)
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(c("No unused declarations found.", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    by_cat: dict[str, int] = defaultdict(int)
    for e in entries:
        by_cat[e["category"]] += 1

    print(c(f"\nUnused declarations: {len(entries)} across {len(by_file)} files\n", "bold"))

    print(c("By category:", "cyan"))
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print()

    print(c("Top files:", "cyan"))
    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
    rows = []
    for filepath, file_entries in sorted_files[: args.top]:
        names = ", ".join(e["name"] for e in file_entries[:5])
        if len(file_entries) > 5:
            names += f", ... (+{len(file_entries) - 5})"
        rows.append([rel(filepath), str(len(file_entries)), names])
    print_table(["File", "Count", "Names"], rows, [55, 6, 50])
