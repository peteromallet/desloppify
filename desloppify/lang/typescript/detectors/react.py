"""React anti-pattern detection: useState+useEffect state sync."""

import json
import re
from pathlib import Path

from ....utils import PROJECT_ROOT, c, find_tsx_files, print_table, rel
from ._smell_helpers import scan_code, _strip_ts_comments

MAX_EFFECT_BODY = 1000  # max characters to scan for brace-matching a useEffect callback
MAX_FUNC_SCAN = 2000    # max lines to scan for function body extent


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
            body_end = None
            for ci, ch, in_s in scan_code(content, brace_start, min(brace_start + MAX_EFFECT_BODY, len(content))):
                if in_s:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        body_end = ci
                        break

            if body_end is None:
                continue

            body = content[brace_start + 1:body_end]
            # Strip comments (string-aware to avoid corrupting URLs etc.)
            body_clean = _strip_ts_comments(body).strip()

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


def detect_context_nesting(path: Path) -> tuple[list[dict], int]:
    """Find deeply nested React Context provider trees (>5 levels in one file).

    Counts opening <*Provider> tags and tracks nesting depth via matching
    closing tags. Flags files where the max provider depth exceeds 5.
    """
    entries = []
    total_files = 0
    provider_open = re.compile(r"<(\w+Provider)\b(?!.*/>)")  # opening, not self-closing
    provider_close = re.compile(r"</(\w+Provider)\s*>")

    for filepath in find_tsx_files(path):
        total_files += 1
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        depth = 0
        max_depth = 0
        providers_at_max: list[str] = []
        provider_stack: list[str] = []

        for line in lines:
            # Process opening tags first, then closing, to handle
            # <FooProvider></FooProvider> on the same line correctly
            for m in provider_open.finditer(line):
                depth += 1
                provider_stack.append(m.group(1))
                if depth > max_depth:
                    max_depth = depth
                    providers_at_max = list(provider_stack)

            for m in provider_close.finditer(line):
                if provider_stack and provider_stack[-1] == m.group(1):
                    provider_stack.pop()
                    depth -= 1

        if max_depth > 5:
            entries.append({
                "file": filepath,
                "depth": max_depth,
                "providers": providers_at_max,
            })

    return sorted(entries, key=lambda e: -e["depth"]), total_files


def detect_hook_return_bloat(path: Path) -> tuple[list[dict], int]:
    """Find custom hooks returning objects with too many fields (>12).

    Scans for exported functions named use* and counts the top-level
    properties in their return object literal.
    """
    entries = []
    total_hooks = 0
    hook_re = re.compile(
        r"(?:export\s+)?(?:function|const)\s+(use[A-Z]\w*)"
    )

    for filepath in find_tsx_files(path):
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        # Also check .ts files with use* names
        for m in hook_re.finditer(content):
            hook_name = m.group(1)
            total_hooks += 1
            hook_start = content[:m.start()].count("\n")

            # Find the function body by tracking braces from the opening {
            brace_line = None
            for k in range(hook_start, min(hook_start + 5, len(lines))):
                if "{" in lines[k]:
                    brace_line = k
                    break
            if brace_line is None:
                continue

            # Find end of function
            depth = 0
            found_open = False
            func_end = None
            for j in range(brace_line, min(brace_line + MAX_FUNC_SCAN, len(lines))):
                for _, ch, in_s in scan_code(lines[j]):
                    if in_s:
                        continue
                    if ch == "{":
                        depth += 1
                        found_open = True
                    elif ch == "}":
                        depth -= 1
                        if found_open and depth == 0:
                            func_end = j
                            break
                if func_end is not None:
                    break

            if func_end is None:
                continue

            # Find the last top-level return statement with an object literal
            # Scan backwards from function end for "return {"
            func_body = "\n".join(lines[brace_line:func_end + 1])
            field_count = _count_return_fields(func_body)
            if field_count is not None and field_count > 12:
                entries.append({
                    "file": filepath,
                    "line": hook_start + 1,
                    "hook": hook_name,
                    "field_count": field_count,
                })

    return sorted(entries, key=lambda e: -e["field_count"]), total_hooks


def _count_return_fields(func_body: str) -> int | None:
    """Count fields in the last return { ... } object in a function body.

    Finds the last `return {` at depth 1 (top-level of function) and counts
    comma-separated fields at depth 1 within that object.
    """
    # Find all "return" positions at depth 1
    lines = func_body.splitlines()
    depth = 0
    return_positions: list[int] = []

    for i, line in enumerate(lines):
        # Check depth BEFORE processing braces on this line
        pre_depth = depth
        for _, ch, in_s in scan_code(line):
            if in_s:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1

        # pre_depth == 1 means we were at function body level at line start
        stripped = line.strip()
        if pre_depth == 1 and stripped.startswith("return") and "{" in stripped:
            return_positions.append(i)

    if not return_positions:
        return None

    # Take the last return statement
    return_line = return_positions[-1]

    # Count fields in the returned object — track braces from the return {
    ret_text = "\n".join(lines[return_line:])
    brace_start = ret_text.find("{")
    if brace_start == -1:
        return None

    obj_depth = 0
    field_count = 0
    started = False

    for _, ch, in_s in scan_code(ret_text, brace_start):
        if in_s:
            continue
        if ch == "{":
            obj_depth += 1
            started = True
        elif ch == "}":
            obj_depth -= 1
            if started and obj_depth == 0:
                break
        elif ch == "," and obj_depth == 1:
            field_count += 1

    # field_count counts commas; fields = commas + 1 (if any content)
    if field_count > 0:
        field_count += 1
    else:
        # Check if there's any content at all (single field, no comma)
        obj_content = ""
        d = 0
        for ch in ret_text[brace_start:]:
            if ch == "{":
                d += 1
            elif ch == "}":
                d -= 1
                if d == 0:
                    break
            elif d == 1:
                obj_content += ch
        if obj_content.strip():
            field_count = 1

    return field_count


def detect_boolean_state_explosion(path: Path) -> tuple[list[dict], int]:
    """Find components with 3+ boolean useState hooks suggesting mutually exclusive states.

    Looks for patterns like:
        const [showX, setShowX] = useState(false);
        const [showY, setShowY] = useState(false);
        const [showZ, setShowZ] = useState(false);

    When setters share a common prefix pattern (setShow*, setIs*Open, etc.),
    these are likely mutually exclusive states that should be a single
    discriminated union value.
    """
    entries = []
    total_components = 0
    # Match useState(false) or useState<boolean>(false)
    bool_state_re = re.compile(
        r"const\s+\[(\w+),\s*(set\w+)\]\s*=\s*useState(?:<boolean>)?\s*\(\s*false\s*\)"
    )

    for filepath in find_tsx_files(path):
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        matches = list(bool_state_re.finditer(content))
        if len(matches) < 3:
            continue

        total_components += 1

        # Group boolean states by their setter name prefix pattern
        # e.g., setShowExport, setShowDelete -> "setShow"
        # e.g., isModalOpen, isDialogOpen -> "is...Open"
        states = [(m.group(1), m.group(2), content[:m.start()].count("\n") + 1)
                  for m in matches]

        # Check for common prefix in setter names (at least 3 chars after "set")
        prefixes: dict[str, list[tuple]] = {}
        for state_name, setter, line in states:
            # Extract prefix: "setShow" from "setShowExport", "setIs" from "setIsOpen"
            # Look for where the varying part starts (first uppercase after "set" + camelCase)
            bare = setter[3:]  # remove "set"
            # Find split point — after the common prefix word
            for k in range(2, len(bare)):
                if bare[k].isupper():
                    prefix = "set" + bare[:k]
                    prefixes.setdefault(prefix, []).append((state_name, setter, line))
                    break

        # Find groups with 3+ members
        for prefix, group in prefixes.items():
            if len(group) >= 3:
                entries.append({
                    "file": filepath,
                    "line": group[0][2],
                    "count": len(group),
                    "setters": [g[1] for g in group],
                    "states": [g[0] for g in group],
                    "prefix": prefix,
                })
                break  # one finding per file

        # Also flag if there are 4+ boolean useState regardless of prefix pattern
        if not any(e["file"] == filepath for e in entries) and len(states) >= 4:
            entries.append({
                "file": filepath,
                "line": states[0][2],
                "count": len(states),
                "setters": [s[1] for s in states],
                "states": [s[0] for s in states],
                "prefix": "(mixed)",
            })

    return sorted(entries, key=lambda e: -e["count"]), total_components


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
