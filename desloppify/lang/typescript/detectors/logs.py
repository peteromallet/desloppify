"""Tagged console.log('[Tag]') detection.

Catches:
- Direct tags: console.log('[Tag] ...')
- Emoji-prefixed tags: console.log('🔍 [Tag] ...')
- Template-literal tags: console.log(`${TAG_VAR} ...`) where TAG_VAR = '[Tag]'
"""

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, c, print_table, rel


TAG_EXTRACT_RE = re.compile(r"\[([^\]]+)\]")


def detect_logs(path: Path) -> tuple[list[dict], int]:
    # Pattern 1: Direct and emoji-prefixed tags — console.log('[Tag]' or console.log('emoji [Tag]'
    # The .{0,4} allows up to 4 chars of emoji/whitespace before the bracket
    result1 = subprocess.run(
        ["grep", "-rn", "--include=*.ts", "--include=*.tsx", "-E",
         r"console\.(log|warn|info|debug)\s*\(\s*['\"`].{0,4}\[", str(path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )

    # Pattern 2: Template-literal tag via variable containing TAG/DEBUG/LOG in its name
    # (catches indirect tags like REORDER_DEBUG_TAG)
    result2 = subprocess.run(
        ["grep", "-rn", "--include=*.ts", "--include=*.tsx", "-Ei",
         r"console\.(log|warn|info|debug)\s*\(\s*`\$\{\w*(TAG|DEBUG|LOG)\w*\}", str(path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )

    from ....utils import find_ts_files
    total_files = len(find_ts_files(path))
    seen: set[tuple[str, str]] = set()  # (filepath, lineno) dedup
    entries = []

    for output in [result1.stdout, result2.stdout]:
        for line in output.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            filepath, lineno, content = parts[0], parts[1], parts[2]
            key = (filepath, lineno)
            if key in seen:
                continue
            seen.add(key)
            tag_match = TAG_EXTRACT_RE.search(content)
            tag = tag_match.group(1) if tag_match else "unknown"
            entries.append({"file": filepath, "line": int(lineno), "tag": tag, "content": content.strip()})

    return entries, total_files


def cmd_logs(args):
    entries, _ = detect_logs(Path(args.path))
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(c("No tagged console.logs found.", "green"))
        return

    by_file: dict[str, list] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)
    sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))

    by_tag: dict[str, int] = defaultdict(int)
    for e in entries:
        by_tag[e["tag"]] += 1

    print(c(f"\nTagged console.logs: {len(entries)} across {len(by_file)} files\n", "bold"))

    print(c("Top tags:", "cyan"))
    for tag, count in sorted(by_tag.items(), key=lambda x: -x[1])[:10]:
        print(f"  [{tag}] × {count}")
    print()

    print(c("Top files:", "cyan"))
    rows = []
    for filepath, file_entries in sorted_files[: args.top]:
        rows.append([rel(filepath), str(len(file_entries))])
    print_table(["File", "Count"], rows, [70, 6])

    if args.fix:
        print(c(f"\n--fix: Will remove {len(entries)} tagged log lines.", "yellow"))
        confirm = input("Proceed? [y/N] ").strip().lower()
        if confirm == "y":
            _fix_logs(by_file)
        else:
            print("Aborted.")


def _fix_logs(by_file: dict[str, list]):
    removed = 0
    for filepath, file_entries in by_file.items():
        lines_to_remove = {e["line"] for e in file_entries}
        p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        original = p.read_text()
        new_lines = []
        for i, line in enumerate(original.splitlines(keepends=True), start=1):
            if i not in lines_to_remove:
                new_lines.append(line)
            else:
                removed += 1
        p.write_text("".join(new_lines))
    print(c(f"Removed {removed} lines across {len(by_file)} files.", "green"))
