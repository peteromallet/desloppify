"""GDScript-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from desloppify.languages.gdscript.patterns import (
    CLASS_NAME_RE,
    COMMENT_RE,
    EXTENDS_RE,
    LOAD_PATH_RE,
    STRING_RE,
)

# A bare PascalCase identifier is how a suite names the thing it exercises,
# because Godot resolves `class_name` globally with no import statement.
_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")

_GDS_LOGIC_RE = re.compile(r"(?m)^\s*(?:func|class_name|extends)\b")

ASSERT_PATTERNS = [re.compile(p) for p in [r"\bassert\(", r"\bassert_[A-Za-z_]\w*\("]]
MOCK_PATTERNS: list[re.Pattern[str]] = []
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"(?m)^\s*func\s+test_[A-Za-z_]\w*\s*\(")
BARREL_BASENAMES: set[str] = set()


def _find_project_root(path: Path) -> Path:
    cursor = path if path.is_dir() else path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "project.godot").is_file():
            return candidate
    return cursor


@lru_cache(maxsize=8)
def _class_name_index(production_files: frozenset[str]) -> dict[str, str]:
    """Map each declared ``class_name`` to the file that declares it."""
    index: dict[str, str] = {}
    for filepath in production_files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue
        match = CLASS_NAME_RE.search(content)
        if match:
            index.setdefault(match.group("name"), filepath)
    return index


def _resolve_res_path(spec: str, project_root: Path) -> Path | None:
    if not spec.startswith("res://"):
        return None
    return (project_root / spec[len("res://") :]).resolve()


def has_testable_logic(filepath: str, content: str) -> bool:
    if filepath.endswith((".import", ".uid")):
        return False
    return bool(_GDS_LOGIC_RE.search(content))


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    cleaned = (spec or "").strip()
    if not cleaned:
        return None

    project_root = _find_project_root(Path(test_path))
    resolved = _resolve_res_path(cleaned, project_root)
    if resolved is not None:
        resolved_str = str(resolved)
        return resolved_str if resolved_str in production_files else None

    # Not a path — try the global class registry.
    return _class_name_index(frozenset(production_files)).get(cleaned)


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    try:
        content = Path(filepath).read_text(errors="replace")
    except OSError:
        return set()
    out: set[str] = set()
    for match in LOAD_PATH_RE.finditer(content):
        resolved = resolve_import_spec(match.group("path"), filepath, production_files)
        if resolved:
            out.add(resolved)
    return out


def parse_test_import_specs(content: str) -> list[str]:
    """Return everything a suite names: ``res://`` paths and global classes."""
    specs = [match.group("path") for match in LOAD_PATH_RE.finditer(content)]
    extends = EXTENDS_RE.search(content)
    if extends:
        specs.append(extends.group("path"))

    # Comments and strings are stripped so a class merely described in prose
    # is not counted as covered.
    body = COMMENT_RE.sub("", STRING_RE.sub(" ", content))
    specs.extend(dict.fromkeys(_IDENTIFIER_RE.findall(body)))
    return specs


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    basename = os.path.basename(test_path)
    src_name = strip_test_markers(basename)
    if not src_name:
        return None
    candidate = Path(test_path).with_name(src_name).resolve()
    candidate_str = str(candidate)
    if candidate_str in production_set:
        return candidate_str
    return None


def strip_test_markers(basename: str) -> str | None:
    if basename.startswith("test_") and basename.endswith(".gd"):
        return basename[len("test_") :]
    if basename.endswith("_test.gd"):
        return f"{basename[:-8]}.gd"
    return None


def strip_comments(content: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in content.splitlines())
