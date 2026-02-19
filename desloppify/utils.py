"""Shared utilities: paths, colors, output formatting, file discovery."""

import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from desloppify.core.internal import text_utils as _text_utils
from desloppify.core.runtime_state import current_runtime_context

get_area = _text_utils.get_area
strip_c_style_comments = _text_utils.strip_c_style_comments

PROJECT_ROOT = _text_utils.PROJECT_ROOT
DEFAULT_PATH = PROJECT_ROOT / "src"
SRC_PATH = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")


def read_code_snippet(filepath: str, line: int, context: int = 1) -> str | None:
    """Read a snippet around a 1-based line number."""
    return _text_utils.read_code_snippet(
        filepath, line, context, project_root=PROJECT_ROOT
    )

# Directories that are never useful to scan — always pruned during traversal.
DEFAULT_EXCLUSIONS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".output",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
        "*.egg-info",
        ".svn",
        ".hg",
    }
)


def set_exclusions(patterns: list[str]):
    """Set global exclusion patterns (called once from CLI at startup)."""
    runtime = current_runtime_context()
    runtime.exclusion_config.values = tuple(patterns)
    runtime.source_file_cache.clear()


def get_exclusions() -> tuple[str, ...]:
    """Return current extra exclusion patterns.

    Use this instead of accessing exclusion state directly —
    from-imports bind to the initial value and become stale after set_exclusions().
    """
    return current_runtime_context().exclusion_config.values


def enable_file_cache():
    """Enable scan-scoped file content cache."""
    runtime = current_runtime_context()
    runtime.file_text_cache.enable()
    runtime.cache_enabled.set(True)


def disable_file_cache():
    """Disable file content cache and free memory."""
    runtime = current_runtime_context()
    runtime.file_text_cache.disable()
    runtime.cache_enabled.set(False)


def is_file_cache_enabled() -> bool:
    """Return whether scan-scoped file cache is currently enabled."""
    return bool(current_runtime_context().cache_enabled)


# ── Atomic file writes ─────────────────────────────────────
def safe_write_text(filepath: str | Path, content: str) -> None:
    """Atomically write text to a file using temp+rename."""
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, str(p))
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── Cross-platform grep replacements ────────────────────────


def read_file_text(filepath: str) -> str | None:
    """Read a file as text, with optional caching."""
    return current_runtime_context().file_text_cache.read(filepath)


def grep_files(
    pattern: str, file_list: list[str], *, flags: int = 0
) -> list[tuple[str, int, str]]:
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
        abs_path = filepath if os.path.isabs(filepath) else str(PROJECT_ROOT / filepath)
        content = read_file_text(abs_path)
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
    Returns True if entries were displayed, False if empty.
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
        return rel_path.startswith(normalized + "/") or rel_path.startswith(
            normalized + os.sep
        )
    return False


def _is_excluded_dir(name: str, rel_path: str, extra: tuple[str, ...]) -> bool:
    """Check if a directory should be pruned during traversal."""
    in_default_exclusions = name in DEFAULT_EXCLUSIONS or name.endswith(".egg-info")
    is_virtualenv_dir = name.startswith(".venv") or name.startswith("venv")
    matches_extra_exclusion = bool(
        extra
        and any(
            matches_exclusion(rel_path, exclusion) or exclusion == name
            for exclusion in extra
        )
    )
    return in_default_exclusions or is_virtualenv_dir or matches_extra_exclusion


def _clear_source_file_cache() -> None:
    """Clear cached source-file discovery results."""
    current_runtime_context().source_file_cache.clear()


def _find_source_files_cached(
    path: str,
    extensions: tuple[str, ...],
    exclusions: tuple[str, ...] | None = None,
    extra_exclusions: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Cached file discovery using os.walk — cross-platform, prunes during traversal."""
    cache_key = (path, extensions, exclusions, extra_exclusions)
    cache = current_runtime_context().source_file_cache
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

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
            d
            for d in dirnames
            if not _is_excluded_dir(d, rel_dir + "/" + d, all_exclusions)
        )
        for fname in filenames:
            if any(fname.endswith(ext) for ext in ext_set):
                full = os.path.join(dirpath, fname)
                rel_file = _normalize_path_separators(_safe_relpath(full, PROJECT_ROOT))
                if all_exclusions and any(
                    matches_exclusion(rel_file, ex) for ex in all_exclusions
                ):
                    continue
                files.append(rel_file)
    result = tuple(sorted(files))
    cache.put(cache_key, result)
    return result


_find_source_files_cached.cache_clear = _clear_source_file_cache


def find_source_files(
    path: str | Path, extensions: list[str], exclusions: list[str] | None = None
) -> list[str]:
    """Find all files with given extensions under a path, excluding patterns."""
    # Pass configured extra exclusions as part of the cache key so changes invalidate cached results.
    return list(
        _find_source_files_cached(
            str(path),
            tuple(extensions),
            tuple(exclusions) if exclusions else None,
            get_exclusions(),
        )
    )


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
