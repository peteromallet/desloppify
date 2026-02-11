"""React anti-pattern detection: useState+useEffect state sync."""

import json
import re
from pathlib import Path

from ....utils import PROJECT_ROOT, c, find_tsx_files, print_table, rel

MAX_EFFECT_BODY = 1000  # max characters to scan for brace-matching a useEffect callback


def detect_state_sync(path: Path) -> tuple[list[dict], int]:
    """Find useEffect blocks whose only statements are setState calls.

    This pattern causes an unnecessary extra render cycle — the derived value
    is stale for one frame. Common variants:
    - "Derived state": should be useMemo or inline computation
    - "Reset on change": should use key prop or restructure

    Returns one entry per occurrence with setter names and line number.
    """
    entries = []
    total_effects = 0

    for filepath in find_tsx_files(path):
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        # Collect all useState setters in this file
        setters = set()
        for m in re.finditer(r"const\s+\[\w+,\s*(set\w+)\]\s*=\s*useState", content):
            setters.add(m.group(1))

        if not setters:
            continue

        # Count all useEffect calls (potential) and find matching blocks
        total_effects += len(re.findall(r"useEffect\s*\(", content))
        effect_re = re.compile(r"useEffect\s*\(\s*\(\s*\)\s*=>\s*\{")
        for m in effect_re.finditer(content):
            # Extract the callback body using brace tracking
            brace_start = m.end() - 1  # the {
            depth = 0
            in_str = None
            prev_ch = ""
            body_end = None
            for ci in range(brace_start, min(brace_start + MAX_EFFECT_BODY, len(content))):
                ch = content[ci]
                if in_str:
                    if ch == in_str and prev_ch != "\\":
                        in_str = None
                    prev_ch = ch
                    continue
                if ch in "'\"`":
                    in_str = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        body_end = ci
                        break
                prev_ch = ch

            if body_end is None:
                continue

            body = content[brace_start + 1:body_end]
            # Strip comments
            body_clean = re.sub(r"//[^\n]*", "", body)
            body_clean = re.sub(r"/\*.*?\*/", "", body_clean, flags=re.DOTALL)
            body_clean = body_clean.strip()

            if not body_clean:
                continue  # empty effect — caught by dead_useeffect

            # Split into statements
            statements = [s.strip().rstrip(";") for s in re.split(r"[;\n]", body_clean) if s.strip()]
            if not statements:
                continue

            # Check if ALL statements are setter calls from this component's useState
            matched_setters = set()
            all_setters = True
            for stmt in statements:
                found = False
                for setter in setters:
                    if stmt.startswith(setter + "("):
                        found = True
                        matched_setters.add(setter)
                        break
                if not found:
                    all_setters = False
                    break

            if all_setters and matched_setters:
                line_no = content[:m.start()].count("\n") + 1
                entries.append({
                    "file": filepath,
                    "line": line_no,
                    "setters": sorted(matched_setters),
                    "content": lines[line_no - 1].strip()[:100] if line_no <= len(lines) else "",
                })

    return entries, total_effects


def cmd_react(args):
    """Show React anti-patterns (state sync via useEffect)."""
    entries, _ = detect_state_sync(Path(args.path))

    if args.json:
        print(json.dumps({"count": len(entries), "entries": [
            {"file": rel(e["file"]), "line": e["line"],
             "setters": e["setters"]}
            for e in entries
        ]}, indent=2))
        return

    if not entries:
        print(c("\nNo state sync anti-patterns found.", "green"))
        return

    print(c(f"\nState sync anti-patterns (useEffect only calls setters): "
            f"{len(entries)}\n", "bold"))

    rows = []
    for e in entries[:args.top]:
        rows.append([
            rel(e["file"]),
            str(e["line"]),
            ", ".join(e["setters"]),
        ])
    print_table(["File", "Line", "Setters"], rows, [60, 6, 40])
    print()
