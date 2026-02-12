"""Shared utilities: paths, colors, output formatting, file discovery."""

import hashlib
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("DESLOPPIFY_ROOT", Path.cwd()))
DEFAULT_PATH = PROJECT_ROOT / "src"
SRC_PATH = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")

# Extra exclusions set via --exclude CLI flag, applied to all file discovery
_extra_exclusions: tuple[str, ...] = ()


def set_exclusions(patterns: list[str]):
    """Set global exclusion patterns (called once from CLI at startup)."""
    global _extra_exclusions
    _extra_exclusions = tuple(patterns)
    _find_source_files_cached.cache_clear()


def run_grep(cmd: list[str]) -> str:
    """Run a grep command, filtering results by active exclusions.

    Exclusion matching uses only the file path portion (before ':') converted
    to a relative path, so patterns like 'Wan2GP' won't falsely match when the
    project root directory name contains that substring (e.g. 'Headless-Wan2GP').
    """
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if not _extra_exclusions or not result.stdout:
        return result.stdout
    lines = result.stdout.splitlines()
    filtered = []
    for line in lines:
        # Extract just the file path portion for exclusion matching
        colon_idx = line.find(":")
        file_part = line[:colon_idx] if colon_idx != -1 else line
        # Convert to relative path to avoid matching project root directory name
        try:
            file_part = str(Path(file_part).relative_to(PROJECT_ROOT))
        except ValueError:
            pass  # already relative or outside project root
        if not any(ex in file_part for ex in _extra_exclusions):
            filtered.append(line)
    return "\n".join(filtered) + ("\n" if filtered else "")

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


def c(text: str, color: str) -> str:
    if NO_COLOR or not sys.stdout.isatty():
        return str(text)
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def log(msg: str):
    """Print a dim status message to stderr."""
    print(c(msg, "dim"), file=sys.stderr)


def print_table(headers: list[str], rows: list[list[str]], widths: list[int] | None = None):
    if not rows:
        return
    if not widths:
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(c(header_line, "bold"))
    print(c("─" * (sum(widths) + 2 * (len(widths) - 1)), "dim"))
    for row in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))


def display_entries(args, entries, *, label, empty_msg, columns, widths, row_fn,
                    json_payload=None, overflow=True):
    """Standard JSON/empty/table display for detect commands.

    Handles the three-branch pattern shared by most cmd wrappers:
    1. --json → dump payload  2. empty → green message  3. table → header + rows + overflow.
    Returns True if entries were displayed, False if empty.
    """
    import json as _json
    if getattr(args, "json", False):
        payload = json_payload or {"count": len(entries), "entries": entries}
        print(_json.dumps(payload, indent=2))
        return True
    if not entries:
        print(c(empty_msg, "green"))
        return False
    print(c(f"\n{label}: {len(entries)}\n", "bold"))
    top = getattr(args, "top", 20)
    rows = [row_fn(e) for e in entries[:top]]
    print_table(columns, rows, widths)
    if overflow and len(entries) > top:
        print(f"\n  ... and {len(entries) - top} more")
    return True


def rel(path: str) -> str:
    try:
        return str(Path(path).relative_to(PROJECT_ROOT))
    except ValueError:
        return path


def resolve_path(filepath: str) -> str:
    """Resolve a filepath to absolute, handling both relative and absolute."""
    p = Path(filepath)
    if p.is_absolute():
        return str(p.resolve())
    return str((PROJECT_ROOT / filepath).resolve())


@lru_cache(maxsize=16)
def _find_source_files_cached(path: str, extensions: tuple[str, ...],
                               exclusions: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Cached file discovery — returns tuple for hashability."""
    args = ["find", path]
    name_parts: list[str] = []
    for ext in extensions:
        if name_parts:
            name_parts.append("-o")
        name_parts.extend(["-name", f"*{ext}"])
    if len(extensions) > 1:
        args += ["(", *name_parts, ")"]
    else:
        args += name_parts

    result = subprocess.run(args, capture_output=True, text=True, cwd=PROJECT_ROOT)
    files = [f for f in result.stdout.strip().splitlines() if f]

    all_exclusions = (exclusions or ()) + _extra_exclusions
    if all_exclusions:
        files = [f for f in files if not any(ex in f for ex in all_exclusions)]
    return tuple(files)


def find_source_files(path: str | Path, extensions: list[str],
                      exclusions: list[str] | None = None) -> list[str]:
    """Find all files with given extensions under a path, excluding patterns."""
    return list(_find_source_files_cached(
        str(path), tuple(extensions), tuple(exclusions) if exclusions else None))


def find_ts_files(path: str | Path) -> list[str]:
    """Find all .ts and .tsx files under a path."""
    return find_source_files(path, [".ts", ".tsx"])


def find_tsx_files(path: str | Path) -> list[str]:
    """Find all .tsx files under a path."""
    return find_source_files(path, [".tsx"])


def find_py_files(path: str | Path) -> list[str]:
    """Find all .py files under a path, excluding common non-source dirs."""
    return find_source_files(path, [".py"], ["__pycache__", ".venv", "node_modules"])


TOOL_DIR = Path(__file__).resolve().parent


def compute_tool_hash() -> str:
    """Compute a content hash of all .py files in the desloppify package.

    Changes to any tool source file produce a different hash, enabling
    staleness detection for scan results.
    """
    h = hashlib.sha256()
    for py_file in sorted(TOOL_DIR.rglob("*.py")):
        h.update(str(py_file.relative_to(TOOL_DIR)).encode())
        h.update(py_file.read_bytes())
    return h.hexdigest()[:12]


def check_tool_staleness(state: dict) -> str | None:
    """Return a warning string if tool code has changed since last scan, else None."""
    stored = state.get("tool_hash")
    if not stored:
        return None
    current = compute_tool_hash()
    if current != stored:
        return (f"Tool code changed since last scan (was {stored}, now {current}). "
                f"Consider re-running: desloppify scan")
    return None


def get_area(filepath: str) -> str:
    """Derive an area name from a file path for grouping structural findings."""
    parts = filepath.split("/")
    if filepath.startswith("src/tools/") and len(parts) >= 3:
        return "/".join(parts[:3])
    if filepath.startswith("src/shared/components/") and len(parts) > 3:
        if not parts[3].endswith((".tsx", ".ts")):
            return "/".join(parts[:4])
        return "/".join(parts[:3])
    if filepath.startswith("src/shared/") and len(parts) >= 3:
        return "/".join(parts[:3])
    if filepath.startswith("src/pages/") and len(parts) >= 3:
        return "/".join(parts[:3])
    return "/".join(parts[:2]) if len(parts) > 1 else parts[0]
