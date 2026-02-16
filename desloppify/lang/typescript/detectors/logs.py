"""Tagged console.log('[Tag]') detection.

Catches:
- Direct tags: console.log('[Tag] ...')
- Emoji-prefixed tags: console.log('🔍 [Tag] ...')
- Template-literal tags: console.log(`${TAG_VAR} ...`) where TAG_VAR = '[Tag]'
"""

import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, c, grep_files, print_table, rel

LOGGER = logging.getLogger(__name__)


TAG_EXTRACT_RE = re.compile(r"\[([^\]]+)\]")

# Pattern 1: Direct and emoji-prefixed tags
_PAT1 = r"console\.(log|warn|info|debug)\s*\(\s*['\"`].{0,4}\["
# Pattern 2: Template-literal tag via variable containing TAG/DEBUG/LOG
_PAT2 = r"console\.(log|warn|info|debug)\s*\(\s*`\$\{\w*(TAG|DEBUG|LOG)\w*\}"


def detect_logs(path: Path) -> tuple[list[dict], int]:
    from ....utils import find_ts_files
    ts_files = find_ts_files(path)
    total_files = len(ts_files)

    hits1 = grep_files(_PAT1, ts_files)
    hits2 = grep_files(_PAT2, ts_files, flags=re.IGNORECASE)

    seen: set[tuple[str, int]] = set()
    entries = []
    for filepath, lineno, content in hits1 + hits2:
        key = (filepath, lineno)
        if key in seen:
            continue
        seen.add(key)
        tag_match = TAG_EXTRACT_RE.search(content)
        tag = tag_match.group(1) if tag_match else "unknown"
        entries.append({"file": filepath, "line": lineno, "tag": tag, "content": content.strip()})

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
    import os
    removed = 0
    failed = 0
    for filepath, file_entries in by_file.items():
        lines_to_remove = {e["line"] for e in file_entries}
        p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        try:
            original = p.read_text()
            new_lines = []
            for i, line in enumerate(original.splitlines(keepends=True), start=1):
                if i not in lines_to_remove:
                    new_lines.append(line)
                else:
                    removed += 1
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text("".join(new_lines))
            os.replace(str(tmp), str(p))
        except OSError as e:
            failed += 1
            print(c(f"  Failed to fix {filepath}: {e}", "red"))
            try:
                tmp.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                LOGGER.debug("Could not remove temporary log-fix file %s", tmp, exc_info=cleanup_exc)
    msg = f"Removed {removed} lines across {len(by_file)} files."
    if failed:
        msg += f" ({failed} files failed.)"
    print(c(msg, "green"))
