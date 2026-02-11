"""TypeScript/React code smell detection.

Defines TS-specific smell rules and multi-line smell helpers (brace-tracked).
"""

import re
from pathlib import Path

from ....utils import PROJECT_ROOT, find_ts_files


TS_SMELL_CHECKS = [
    {
        "id": "empty_catch",
        "label": "Empty catch blocks",
        "pattern": r"catch\s*\([^)]*\)\s*\{\s*\}",
        "severity": "high",
    },
    {
        "id": "any_type",
        "label": "Explicit `any` types",
        "pattern": r":\s*any\b",
        "severity": "medium",
    },
    {
        "id": "ts_ignore",
        "label": "@ts-ignore / @ts-expect-error",
        "pattern": r"@ts-(?:ignore|expect-error)",
        "severity": "medium",
    },
    {
        "id": "non_null_assert",
        "label": "Non-null assertions (!.)",
        "pattern": r"\w+!\.",
        "severity": "low",
    },
    {
        "id": "hardcoded_color",
        "label": "Hardcoded color values",
        "pattern": r"""(?:color|background|border|fill|stroke)\s*[:=]\s*['"]#[0-9a-fA-F]{3,8}['"]""",
        "severity": "medium",
    },
    {
        "id": "hardcoded_rgb",
        "label": "Hardcoded rgb/rgba",
        "pattern": r"rgba?\(\s*\d+",
        "severity": "medium",
    },
    {
        "id": "async_no_await",
        "label": "Async functions without await",
        "pattern": None,  # multi-line analysis
        "severity": "medium",
    },
    {
        "id": "magic_number",
        "label": "Magic numbers (>1000 in logic)",
        "pattern": r"(?:===?|!==?|>=?|<=?|[+\-*/])\s*\d{4,}",
        "severity": "low",
    },
    {
        "id": "console_error_no_throw",
        "label": "console.error without throw/return",
        "pattern": None,  # multi-line analysis
        "severity": "medium",
    },
    {
        "id": "empty_if_chain",
        "label": "Empty if/else chains",
        "pattern": None,  # multi-line analysis
        "severity": "high",
    },
    {
        "id": "dead_useeffect",
        "label": "useEffect with empty body",
        "pattern": None,  # multi-line analysis
        "severity": "high",
    },
    {
        "id": "swallowed_error",
        "label": "Catch blocks that only log (swallowed errors)",
        "pattern": None,  # multi-line analysis
        "severity": "medium",
    },
]


def detect_smells(path: Path) -> tuple[list[dict], int]:
    """Detect TypeScript/React code smell patterns across the codebase.

    Returns (entries, total_files_checked).
    """
    checks = TS_SMELL_CHECKS
    smell_counts: dict[str, list[dict]] = {s["id"]: [] for s in checks}
    files = find_ts_files(path)

    for filepath in files:
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        # Regex-based smells
        for check in checks:
            if check["pattern"] is None:
                continue
            for i, line in enumerate(lines):
                if re.search(check["pattern"], line):
                    smell_counts[check["id"]].append({
                        "file": filepath,
                        "line": i + 1,
                        "content": line.strip()[:100],
                    })

        # Multi-line smell helpers (brace-tracked)
        _detect_async_no_await(filepath, content, lines, smell_counts)
        _detect_error_no_throw(filepath, lines, smell_counts)
        _detect_empty_if_chains(filepath, lines, smell_counts)
        _detect_dead_useeffects(filepath, lines, smell_counts)
        _detect_swallowed_errors(filepath, content, lines, smell_counts)

    # Build summary entries sorted by severity then count
    severity_order = {"high": 0, "medium": 1, "low": 2}
    entries = []
    for check in checks:
        matches = smell_counts[check["id"]]
        if matches:
            entries.append({
                "id": check["id"],
                "label": check["label"],
                "severity": check["severity"],
                "count": len(matches),
                "files": len(set(m["file"] for m in matches)),
                "matches": matches[:50],
            })
    entries.sort(key=lambda e: (severity_order.get(e["severity"], 9), -e["count"]))
    return entries, len(files)


# ── Multi-line smell helpers (brace-tracked) ──────────────


def _detect_async_no_await(filepath: str, content: str, lines: list[str],
                           smell_counts: dict[str, list[dict]]):
    """Find async functions that don't use await.

    Algorithm: for each async declaration, track brace depth to find the function
    body extent (up to 200 lines). Scan each line for 'await' within those braces.
    If the opening brace closes (depth returns to 0) without seeing await, flag it.
    """
    async_re = re.compile(r"(?:async\s+function\s+(\w+)|(\w+)\s*=\s*async)")
    for i, line in enumerate(lines):
        m = async_re.search(line)
        if not m:
            continue
        name = m.group(1) or m.group(2)
        brace_depth = 0
        found_open = False
        has_await = False
        for j in range(i, min(i + 200, len(lines))):
            body_line = lines[j]
            for ch in body_line:
                if ch == '{':
                    brace_depth += 1
                    found_open = True
                elif ch == '}':
                    brace_depth -= 1
            if "await " in body_line or "await\n" in body_line:
                has_await = True
            if found_open and brace_depth <= 0:
                break

        if found_open and not has_await:
            smell_counts["async_no_await"].append({
                "file": filepath,
                "line": i + 1,
                "content": f"async {name or '(anonymous)'} has no await",
            })


def _detect_error_no_throw(filepath: str, lines: list[str],
                           smell_counts: dict[str, list[dict]]):
    """Find console.error calls not followed by throw or return."""
    for i, line in enumerate(lines):
        if "console.error" in line:
            following = "\n".join(lines[i+1:i+4])
            if not re.search(r"\b(?:throw|return)\b", following):
                smell_counts["console_error_no_throw"].append({
                    "file": filepath,
                    "line": i + 1,
                    "content": line.strip()[:100],
                })


def _detect_empty_if_chains(filepath: str, lines: list[str],
                            smell_counts: dict[str, list[dict]]):
    """Find if/else chains where all branches are empty."""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not re.match(r"(?:else\s+)?if\s*\(", stripped):
            i += 1
            continue

        # Single-line: if (...) { }
        if re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*\}\s*$", stripped):
            chain_start = i
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if re.match(r"else\s+if\s*\([^)]*\)\s*\{\s*\}\s*$", next_stripped):
                    j += 1
                    continue
                if re.match(r"(?:\}\s*)?else\s*\{\s*\}\s*$", next_stripped):
                    j += 1
                    continue
                break
            smell_counts["empty_if_chain"].append({
                "file": filepath,
                "line": chain_start + 1,
                "content": stripped[:100],
            })
            i = j
            continue

        # Multi-line: if (...) { followed by } on next non-blank line
        if re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$", stripped):
            chain_start = i
            chain_all_empty = True
            j = i
            while j < len(lines):
                cur = lines[j].strip()
                if j == chain_start:
                    if not re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$", cur):
                        chain_all_empty = False
                        break
                elif re.match(r"\}\s*else\s+if\s*\([^)]*\)\s*\{\s*$", cur):
                    pass
                elif re.match(r"\}\s*else\s*\{\s*$", cur):
                    pass
                elif cur == "}":
                    k = j + 1
                    while k < len(lines) and lines[k].strip() == "":
                        k += 1
                    if k < len(lines) and re.match(r"else\s", lines[k].strip()):
                        j = k
                        continue
                    j += 1
                    break
                elif cur == "":
                    j += 1
                    continue
                else:
                    chain_all_empty = False
                    break
                j += 1

            if chain_all_empty and j > chain_start + 1:
                smell_counts["empty_if_chain"].append({
                    "file": filepath,
                    "line": chain_start + 1,
                    "content": lines[chain_start].strip()[:100],
                })
            i = max(i + 1, j)
            continue

        i += 1


def _detect_dead_useeffects(filepath: str, lines: list[str],
                            smell_counts: dict[str, list[dict]]):
    """Find useEffect calls with empty or whitespace/comment-only bodies.

    Algorithm: two-pass brace/paren tracking with string-escape awareness.
    Pass 1: track paren depth to find the full useEffect(...) extent.
    Pass 2: within that extent, find the arrow body ({...} after =>) using
    brace depth, skipping characters inside string literals (', ", `).
    Then strip comments from the body and check if anything remains.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r"(?:React\.)?useEffect\s*\(\s*\(\s*\)\s*=>\s*\{", stripped):
            continue

        paren_depth = 0
        brace_depth = 0
        end = None
        for j in range(i, min(i + 30, len(lines))):
            in_str = None
            prev_ch = ""
            for ch in lines[j]:
                if in_str:
                    if ch == in_str and prev_ch != "\\":
                        in_str = None
                    prev_ch = ch
                    continue
                if ch in "'\"`":
                    in_str = ch
                elif ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth <= 0:
                        end = j
                        break
                elif ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
                prev_ch = ch
            if end is not None:
                break

        if end is None:
            continue

        text = "\n".join(lines[i:end + 1])
        arrow_pos = text.find("=>")
        if arrow_pos == -1:
            continue
        brace_pos = text.find("{", arrow_pos)
        if brace_pos == -1:
            continue

        depth = 0
        body_end = None
        in_str = None
        prev_ch = ""
        for ci in range(brace_pos, len(text)):
            ch = text[ci]
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

        body = text[brace_pos + 1:body_end]
        body_stripped = re.sub(r"//[^\n]*", "", body)
        body_stripped = re.sub(r"/\*.*?\*/", "", body_stripped, flags=re.DOTALL)
        if body_stripped.strip() == "":
            smell_counts["dead_useeffect"].append({
                "file": filepath,
                "line": i + 1,
                "content": stripped[:100],
            })


def _detect_swallowed_errors(filepath: str, content: str, lines: list[str],
                              smell_counts: dict[str, list[dict]]):
    """Find catch blocks whose only content is console.error/warn/log (swallowed errors).

    Algorithm: regex-find each `catch(...) {`, then track brace depth with
    string-escape awareness to extract the catch body (up to 500 chars).
    Strip comments, split into statements, and check if every statement
    is a console.error/warn/log call.
    """
    catch_re = re.compile(r"catch\s*\([^)]*\)\s*\{")
    for m in catch_re.finditer(content):
        brace_start = m.end() - 1
        depth = 0
        in_str = None
        prev_ch = ""
        body_end = None
        for ci in range(brace_start, min(brace_start + 500, len(content))):
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
        body_clean = re.sub(r"//[^\n]*", "", body)
        body_clean = re.sub(r"/\*.*?\*/", "", body_clean, flags=re.DOTALL)
        body_clean = body_clean.strip()

        if not body_clean:
            continue  # empty catch — caught by empty_catch detector

        statements = [s.strip().rstrip(";") for s in re.split(r"[;\n]", body_clean) if s.strip()]
        if not statements:
            continue

        all_console = all(
            re.match(r"console\.(error|warn|log)\s*\(", stmt)
            for stmt in statements
        )
        if all_console:
            line_no = content[:m.start()].count("\n") + 1
            smell_counts["swallowed_error"].append({
                "file": filepath,
                "line": line_no,
                "content": lines[line_no - 1].strip()[:100] if line_no <= len(lines) else "",
            })
