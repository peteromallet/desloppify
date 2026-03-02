"""Path resolution and exclusion matching helpers."""

from __future__ import annotations

import os
import tempfile
import fnmatch
from pathlib import Path

from desloppify.core._internal.text_utils import get_project_root


def matches_exclusion(rel_path: str, exclusion: str) -> bool:
    """Check if a relative path matches an exclusion pattern."""
    parts = Path(rel_path).parts
    if exclusion in parts:
        return True
    if "*" in exclusion:
        if any(fnmatch.fnmatch(part, exclusion) for part in parts):
            return True
        # Full-path glob match for patterns with directory separators
        # (e.g. "Wan2GP/**" should match "Wan2GP/models/rf.py").
        if "/" in exclusion or os.sep in exclusion:
            normalized_path = rel_path.lstrip("./")
            if fnmatch.fnmatch(normalized_path, exclusion):
                return True
    if "/" in exclusion or os.sep in exclusion:
        normalized = exclusion.rstrip("/").rstrip(os.sep)
        return rel_path.startswith(normalized + "/") or rel_path.startswith(
            normalized + os.sep
        )
    return False


def normalize_path_separators(path: str) -> str:
    return path.replace("\\", "/")


def safe_relpath(path: str | Path, start: str | Path) -> str:
    try:
        return os.path.relpath(str(path), str(start))
    except ValueError:
        return str(Path(path).resolve())


def rel(path: str) -> str:
    root = get_project_root()
    resolved = Path(path).resolve()
    try:
        return normalize_path_separators(str(resolved.relative_to(root)))
    except ValueError:
        return normalize_path_separators(safe_relpath(resolved, root))


def resolve_path(filepath: str) -> str:
    """Resolve a filepath to absolute, handling both relative and absolute."""
    p = Path(filepath)
    if p.is_absolute():
        return str(p.resolve())
    return str((get_project_root() / filepath).resolve())


def resolve_scan_file(
    filepath: str | Path,
    *,
    scan_root: str | Path | None = None,
) -> Path:
    """Resolve a scan file path with explicit scan-root-first semantics.

    Relative file paths are resolved against ``scan_root`` first (when provided)
    and then against the process project root as a fallback.
    """
    p = Path(filepath)
    if p.is_absolute():
        return p.resolve()

    root = get_project_root()
    if scan_root is not None:
        scan_root_path = Path(scan_root)
        scan_root_abs = (
            scan_root_path.resolve()
            if scan_root_path.is_absolute()
            else (root / scan_root_path).resolve()
        )
        scan_candidate = (scan_root_abs / p).resolve()
        if scan_candidate.exists():
            return scan_candidate

    return (root / p).resolve()


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


__all__ = [
    "matches_exclusion",
    "normalize_path_separators",
    "rel",
    "resolve_path",
    "resolve_scan_file",
    "safe_relpath",
    "safe_write_text",
]
