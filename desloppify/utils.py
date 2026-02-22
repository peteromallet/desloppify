"""Shared utilities: paths, colors, output formatting, grep helpers."""

import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    # Path constants
    "PROJECT_ROOT",
    "DEFAULT_PATH",
    "SRC_PATH",
    # Grep helpers
    "read_code_snippet",
    "grep_files",
    "grep_files_containing",
    "grep_count_files",
    # Output formatting
    "LOC_COMPACT_THRESHOLD",
    "COLORS",
    "NO_COLOR",
    "colorize",
    "log",
    "print_table",
    "display_entries",
    # Tool staleness
    "TOOL_DIR",
    "compute_tool_hash",
    "check_tool_staleness",
    # Skill document tracking
    "SKILL_VERSION",
    "SKILL_VERSION_RE",
    "SKILL_OVERLAY_RE",
    "SKILL_BEGIN",
    "SKILL_END",
    "SKILL_SEARCH_PATHS",
    "SKILL_TARGETS",
    "SkillInstall",
    "find_installed_skill",
    "check_skill_version",
]

from desloppify.core._internal import text_utils as _text_utils
from desloppify.file_discovery import read_file_text as _read_file_text

_get_project_root = _text_utils.get_project_root

PROJECT_ROOT = _text_utils.PROJECT_ROOT
DEFAULT_PATH = PROJECT_ROOT / "src"
SRC_PATH = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")


def read_code_snippet(filepath: str, line: int, context: int = 1) -> str | None:
    """Read a snippet around a 1-based line number."""
    return _text_utils.read_code_snippet(
        filepath, line, context, project_root=_get_project_root()
    )


# ── Cross-platform grep replacements ────────────────────────


def grep_files(
    pattern: str, file_list: list[str], *, flags: int = 0
) -> list[tuple[str, int, str]]:
    """Search files for a regex pattern. Returns list of (filepath, lineno, line_text).

    Cross-platform replacement for ``grep -rn -E <pattern> <path>``.
    """
    compiled = re.compile(pattern, flags)
    results: list[tuple[str, int, str]] = []
    for filepath in file_list:
        abs_path = filepath if os.path.isabs(filepath) else str(_get_project_root() / filepath)
        content = _read_file_text(abs_path)
        if content is None:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if compiled.search(line):
                results.append((filepath, lineno, line))
    return results


def grep_files_containing(
    names: set[str], file_list: list[str], *, word_boundary: bool = True
) -> dict[str, set[str]]:
    r"""Find which files contain which names. Returns {name: set(filepaths)}.

    Cross-platform replacement for ``grep -rlFw -f patternfile <path>``
    followed by per-file ``grep -oFw``.
    """
    if not names:
        return {}
    names_by_length = sorted(names, key=len, reverse=True)
    if word_boundary:
        combined = re.compile(
            r"\b(?:" + "|".join(re.escape(n) for n in names_by_length) + r")\b"
        )
    else:
        combined = re.compile("|".join(re.escape(n) for n in names_by_length))

    name_to_files: dict[str, set[str]] = {}
    for filepath in file_list:
        abs_path = filepath if os.path.isabs(filepath) else str(_get_project_root() / filepath)
        content = _read_file_text(abs_path)
        if content is None:
            continue
        found = set(combined.findall(content))
        for name in found & names:
            name_to_files.setdefault(name, set()).add(filepath)
    return name_to_files


def grep_count_files(
    name: str, file_list: list[str], *, word_boundary: bool = True
) -> list[str]:
    """Return list of files containing name. Replacement for ``grep -rl -w name``."""
    if word_boundary:
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
    else:
        pat = re.compile(re.escape(name))
    matching: list[str] = []
    for filepath in file_list:
        abs_path = filepath if os.path.isabs(filepath) else str(_get_project_root() / filepath)
        content = _read_file_text(abs_path)
        if content is None:
            continue
        if pat.search(content):
            matching.append(filepath)
    return matching


LOC_COMPACT_THRESHOLD = 10000  # Switch from "1,234" to "1K" format

COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
}

NO_COLOR = os.environ.get("NO_COLOR") is not None


def colorize(text: str, color: str) -> str:
    if NO_COLOR or not sys.stdout.isatty():
        return str(text)
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def log(msg: str):
    """Print a dim status message to stderr."""
    print(colorize(msg, "dim"), file=sys.stderr)


def print_table(
    headers: list[str], rows: list[list[str]], widths: list[int] | None = None
) -> None:
    if not rows:
        return
    if not widths:
        widths = [
            max(len(str(h)), *(len(str(r[i])) for r in rows))
            for i, h in enumerate(headers)
        ]
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False))
    print(colorize(header_line, "bold"))
    print(colorize("─" * (sum(widths) + 2 * (len(widths) - 1)), "dim"))
    for row in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths, strict=False)))


def display_entries(
    args: object,
    entries: Sequence[Any],
    *,
    label: str,
    empty_msg: str,
    columns: Sequence[str],
    widths: list[int] | None,
    row_fn: Callable[[Any], list[str]],
    json_payload: dict | None = None,
    overflow: bool = True,
) -> bool:
    """Standard JSON/empty/table display for detect commands.

    Handles the three-branch pattern shared by most cmd wrappers:
    1. --json → dump payload  2. empty → green message  3. table → header + rows + overflow.
    Returns True if entries were displayed (or JSON was emitted), False if empty.
    """
    if getattr(args, "json", False):
        payload = json_payload or {"count": len(entries), "entries": entries}
        print(json.dumps(payload, indent=2))
        return True
    if not entries:
        print(colorize(empty_msg, "green"))
        return False
    print(colorize(f"\n{label}: {len(entries)}\n", "bold"))
    top = getattr(args, "top", 20)
    rows = [row_fn(e) for e in entries[:top]]
    print_table(list(columns), rows, widths)
    if overflow and len(entries) > top:
        print(f"\n  ... and {len(entries) - top} more")
    return True


TOOL_DIR = Path(__file__).resolve().parent


def compute_tool_hash() -> str:
    """Compute a content hash of all .py files in the desloppify package.

    Changes to any tool source file produce a different hash, enabling
    staleness detection for scan results.
    """
    h = hashlib.sha256()
    for py_file in sorted(TOOL_DIR.rglob("*.py")):
        rel_parts = py_file.relative_to(TOOL_DIR).parts
        # Keep the hash focused on runtime code. Colocated test modules under
        # lang/*/tests should not trigger scan staleness warnings.
        if "tests" in rel_parts:
            continue
        try:
            h.update(str(py_file.relative_to(TOOL_DIR)).encode())
            h.update(py_file.read_bytes())
        except OSError:
            # Keep hash deterministic even when a source file is temporarily unreadable.
            h.update(f"[unreadable:{py_file.name}]".encode())
            continue
    return h.hexdigest()[:12]


def check_tool_staleness(state: dict) -> str | None:
    """Return a warning string if tool code has changed since last scan, else None."""
    stored = state.get("tool_hash")
    if not stored:
        return None
    current = compute_tool_hash()
    if current != stored:
        return (
            f"Tool code changed since last scan (was {stored}, now {current}). "
            f"Consider re-running: desloppify scan"
        )
    return None


# ── Skill document version tracking ─────────────────────────
# Bump this integer whenever docs/SKILL.md changes in a way that agents
# should pick up (new commands, changed workflows, removed sections).
SKILL_VERSION = 1

SKILL_VERSION_RE = re.compile(r"<!--\s*desloppify-skill-version:\s*(\d+)\s*-->")
SKILL_OVERLAY_RE = re.compile(r"<!--\s*desloppify-overlay:\s*(\w+)\s*-->")

SKILL_BEGIN = "<!-- desloppify-begin -->"
SKILL_END = "<!-- desloppify-end -->"

# Locations where the skill doc might be installed, relative to PROJECT_ROOT.
SKILL_SEARCH_PATHS = (
    ".claude/skills/desloppify/SKILL.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/desloppify.md",
    ".github/copilot-instructions.md",
)

# Interface name → (target file, overlay filename, dedicated).
# Dedicated files are overwritten entirely; shared files get section replacement.
SKILL_TARGETS: dict[str, tuple[str, str, bool]] = {
    "claude": (".claude/skills/desloppify/SKILL.md", "CLAUDE", True),
    "codex": ("AGENTS.md", "CODEX", False),
    "cursor": (".cursor/rules/desloppify.md", "CURSOR", True),
    "copilot": (".github/copilot-instructions.md", "COPILOT", False),
    "windsurf": ("AGENTS.md", "WINDSURF", False),
    "gemini": ("AGENTS.md", "GEMINI", False),
}


@dataclass
class SkillInstall:
    """Detected skill document installation."""

    rel_path: str
    version: int
    overlay: str | None
    stale: bool


def find_installed_skill() -> SkillInstall | None:
    """Find the installed skill document and return its metadata, or None."""
    for rel_path in SKILL_SEARCH_PATHS:
        full = _get_project_root() / rel_path
        if not full.is_file():
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        version_match = SKILL_VERSION_RE.search(content)
        if not version_match:
            continue
        installed_version = int(version_match.group(1))
        overlay_match = SKILL_OVERLAY_RE.search(content)
        overlay = overlay_match.group(1) if overlay_match else None
        return SkillInstall(
            rel_path=rel_path,
            version=installed_version,
            overlay=overlay,
            stale=installed_version < SKILL_VERSION,
        )
    return None


def check_skill_version() -> str | None:
    """Return a warning if the installed skill doc is outdated, else None."""
    install = find_installed_skill()
    if not install or not install.stale:
        return None
    return (
        f"Your desloppify skill document is outdated "
        f"(v{install.version}, current v{SKILL_VERSION}). "
        f"Run: desloppify update-skill"
    )
