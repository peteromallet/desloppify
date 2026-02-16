"""Shared utilities: paths, colors, output formatting, file discovery."""

import hashlib
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("DESLOPPIFY_ROOT", Path.cwd())).resolve()
DEFAULT_PATH = PROJECT_ROOT / "src"
SRC_PATH = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")

# Directories that are never useful to scan — always pruned during traversal.
DEFAULT_EXCLUSIONS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".env",
    "dist", "build", ".next", ".nuxt", ".output",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".eggs", "*.egg-info",
    ".svn", ".hg",
})

# Extra exclusions set via --exclude CLI flag, applied to all file discovery
_extra_exclusions: tuple[str, ...] = ()


def set_exclusions(patterns: list[str]):
    """Set global exclusion patterns (called once from CLI at startup)."""
    global _extra_exclusions
    _extra_exclusions = tuple(patterns)
    _find_source_files_cached.cache_clear()


def get_exclusions() -> tuple[str, ...]:
    """Return current extra exclusion patterns.

    Use this instead of accessing _extra_exclusions directly —
    from-imports bind to the initial value and become stale after set_exclusions().
    """
    return _extra_exclusions


# ── File content cache (opt-in, scan-scoped) ─────────────

_file_cache: dict[str, str | None] = {}
_cache_enabled = False


def enable_file_cache():
    """Enable scan-scoped file content cache."""
    global _cache_enabled
    _cache_enabled = True
    _file_cache.clear()


def disable_file_cache():
    """Disable file content cache and free memory."""
    global _cache_enabled
    _cache_enabled = False
    _file_cache.clear()


# ── Atomic file writes ─────────────────────────────────────

import tempfile


def safe_write_text(filepath: str | Path, content: str) -> None:
    """Atomically write text to a file using temp+rename."""
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, str(p))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Cross-platform grep replacements ────────────────────────


def read_file_text(filepath: str) -> str | None:
    """Read a file as text, with optional caching."""
    if _cache_enabled:
        if filepath in _file_cache:
            return _file_cache[filepath]
    try:
        content = Path(filepath).read_text(errors="replace")
    except OSError:
        content = None
    if _cache_enabled:
        _file_cache[filepath] = content
    return content


def grep_files(pattern: str, file_list: list[str], *,
               flags: int = 0) -> list[tuple[str, int, str]]:
    """Search files for a regex pattern. Returns list of (filepath, lineno, line_text).

    Cross-platform replacement for ``grep -rn -E <pattern> <path>``.
    """
    compiled = re.compile(pattern, flags)
    results: list[tuple[str, int, str]] = []
    for filepath in file_list:
        abs_path = filepath if os.path.isabs(filepath) else str(PROJECT_ROOT / filepath)
        content = read_file_text(abs_path)
        if content is None:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if compiled.search(line):
                results.append((filepath, lineno, line))
    return results


def grep_files_containing(names: set[str], file_list: list[str], *,
                          word_boundary: bool = True) -> dict[str, set[str]]:
    r"""Find which files contain which names. Returns {name: set(filepaths)}.

    Cross-platform replacement for ``grep -rlFw -f patternfile <path>``
    followed by per-file ``grep -oFw``.
    """
    if not names:
        return {}
    if word_boundary:
        escaped = sorted(names, key=len, reverse=True)
        combined = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in escaped) + r")\b")
    else:
        escaped = sorted(names, key=len, reverse=True)
        combined = re.compile("|".join(re.escape(n) for n in escaped))

    name_to_files: dict[str, set[str]] = {}
    for filepath in file_list:
        abs_path = filepath if os.path.isabs(filepath) else str(PROJECT_ROOT / filepath)
        content = read_file_text(abs_path)
        if content is None:
            continue
        found = set(combined.findall(content))
        for name in found & names:
            name_to_files.setdefault(name, set()).add(filepath)
    return name_to_files


def grep_count_files(name: str, file_list: list[str], *,
                     word_boundary: bool = True) -> list[str]:
    """Return list of files containing name. Replacement for ``grep -rl -w name``."""
    if word_boundary:
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
    else:
        pat = re.compile(re.escape(name))
    matching: list[str] = []
    for filepath in file_list:
        abs_path = filepath if os.path.isabs(filepath) else str(PROJECT_ROOT / filepath)
        content = read_file_text(abs_path)
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


c = colorize


def log(msg: str):
    """Print a dim status message to stderr."""
    print(colorize(msg, "dim"), file=sys.stderr)


def print_table(headers: list[str], rows: list[list[str]], widths: list[int] | None = None):
    if not rows:
        return
    if not widths:
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(colorize(header_line, "bold"))
    print(colorize("─" * (sum(widths) + 2 * (len(widths) - 1)), "dim"))
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
        print(colorize(empty_msg, "green"))
        return False
    print(colorize(f"\n{label}: {len(entries)}\n", "bold"))
    top = getattr(args, "top", 20)
    rows = [row_fn(e) for e in entries[:top]]
    print_table(columns, rows, widths)
    if overflow and len(entries) > top:
        print(f"\n  ... and {len(entries) - top} more")
    return True


def _normalize_path_separators(path: str) -> str:
    """Normalize path separators to forward slashes for stable output."""
    return path.replace("\\", "/")


def _safe_relpath(path: str | Path, start: str | Path) -> str:
    """Compute relpath with cross-drive fallback to absolute path.

    On Windows, os.path.relpath raises ValueError when path and start are on
    different drives. In that case return an absolute path string.
    """
    try:
        return os.path.relpath(str(path), str(start))
    except ValueError:
        return str(Path(path).resolve())


def rel(path: str) -> str:
    resolved = Path(path).resolve()
    try:
        return _normalize_path_separators(str(resolved.relative_to(PROJECT_ROOT)))
    except ValueError:
        # Path outside PROJECT_ROOT: prefer relative form when possible, else absolute.
        return _normalize_path_separators(_safe_relpath(resolved, PROJECT_ROOT))


def resolve_path(filepath: str) -> str:
    """Resolve a filepath to absolute, handling both relative and absolute."""
    p = Path(filepath)
    if p.is_absolute():
        return str(p.resolve())
    return str((PROJECT_ROOT / filepath).resolve())


def matches_exclusion(rel_path: str, exclusion: str) -> bool:
    """Check if a relative path matches an exclusion pattern (path-component aware).

    Matches if exclusion is a path component (e.g. "test" matches "test/foo.py"
    or "src/test/bar.py") or a directory prefix (e.g. "src/test" matches
    "src/test/bar.py"). Does NOT do substring matching — "test" will NOT match
    "testimony.py".
    """
    parts = Path(rel_path).parts
    # Direct component match
    if exclusion in parts:
        return True
    # Directory prefix match (e.g. "src/test" matches "src/test/bar.py")
    if "/" in exclusion or os.sep in exclusion:
        normalized = exclusion.rstrip("/").rstrip(os.sep)
        return rel_path.startswith(normalized + "/") or rel_path.startswith(normalized + os.sep)
    return False


def _is_excluded_dir(name: str, rel_path: str, extra: tuple[str, ...]) -> bool:
    """Check if a directory should be pruned during traversal."""
    if name in DEFAULT_EXCLUSIONS or name.endswith(".egg-info"):
        return True
    if name.startswith(".venv") or name.startswith("venv"):
        return True
    if extra and any(matches_exclusion(rel_path, ex) or ex == name for ex in extra):
        return True
    return False


@lru_cache(maxsize=16)
def _find_source_files_cached(path: str, extensions: tuple[str, ...],
                               exclusions: tuple[str, ...] | None = None,
                               extra_exclusions: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Cached file discovery using os.walk — cross-platform, prunes during traversal."""
    root = Path(path)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    all_exclusions = (exclusions or ()) + extra_exclusions
    ext_set = set(extensions)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place (prevents descending into them)
        rel_dir = _normalize_path_separators(_safe_relpath(dirpath, PROJECT_ROOT))
        dirnames[:] = sorted(
            d for d in dirnames
            if not _is_excluded_dir(d, rel_dir + "/" + d, all_exclusions)
        )
        for fname in filenames:
            if any(fname.endswith(ext) for ext in ext_set):
                full = os.path.join(dirpath, fname)
                rel_file = _normalize_path_separators(_safe_relpath(full, PROJECT_ROOT))
                if all_exclusions and any(matches_exclusion(rel_file, ex) for ex in all_exclusions):
                    continue
                files.append(rel_file)
    return tuple(sorted(files))


def find_source_files(path: str | Path, extensions: list[str],
                      exclusions: list[str] | None = None) -> list[str]:
    """Find all files with given extensions under a path, excluding patterns."""
    # Pass _extra_exclusions as part of the cache key so changes invalidate cached results
    return list(_find_source_files_cached(
        str(path), tuple(extensions), tuple(exclusions) if exclusions else None,
        _extra_exclusions))


def find_ts_files(path: str | Path) -> list[str]:
    """Find all .ts and .tsx files under a path."""
    return find_source_files(path, [".ts", ".tsx"])


def find_tsx_files(path: str | Path) -> list[str]:
    """Find all .tsx files under a path."""
    return find_source_files(path, [".tsx"])


def find_py_files(path: str | Path) -> list[str]:
    """Find all .py files under a path."""
    return find_source_files(path, [".py"])


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
            continue
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


def read_code_snippet(filepath: str, line: int, context: int = 1) -> str | None:
    """Read ±context lines around a line number. Returns formatted string or None."""
    try:
        full = str(PROJECT_ROOT / filepath)
        content = Path(full).read_text(errors="replace")
    except OSError:
        return None
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return None
    start = max(0, line - 1 - context)
    end = min(len(lines), line + context)
    parts = []
    for i in range(start, end):
        ln = i + 1
        marker = "→" if ln == line else " "
        text = lines[i]
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"    {marker} {ln:>4} │ {text}")
    return "\n".join(parts)


def get_area(filepath: str) -> str:
    """Derive an area name from a file path (generic: first 2 path components)."""
    parts = filepath.split("/")
    return "/".join(parts[:2]) if len(parts) > 1 else parts[0]


def strip_c_style_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving string literals.

    Works for any language with C-style comments (JS, TS, Java, Go, etc.).
    Handles single-quoted, double-quoted, and template literal strings.
    """
    result: list[str] = []
    i = 0
    in_str = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == '\\' and i + 1 < len(text):
                result.append(text[i:i + 2])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            result.append(ch)
            i += 1
        elif ch in ('"', "'", '`'):
            in_str = ch
            result.append(ch)
            i += 1
        elif ch == '/' and i + 1 < len(text):
            if text[i + 1] == '/':
                nl = text.find('\n', i)
                if nl == -1:
                    break
                i = nl
            elif text[i + 1] == '*':
                end = text.find('*/', i + 2)
                if end == -1:
                    break
                i = end + 2
            else:
                result.append(ch)
                i += 1
        else:
            result.append(ch)
            i += 1
    return ''.join(result)
