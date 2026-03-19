"""Python-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re

# Python: does the file contain any function definition?
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+", re.MULTILINE)

# Import parsing helpers
PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import\s+(\w+)|import\s+([\w.]+))", re.MULTILINE
)

ASSERT_PATTERNS = [
    re.compile(p)
    for p in [
        r"^\s*assert\s+",
        r"self\.assert\w+\(",
        r"pytest\.raises\(",
        r"\.assert_called",
        r"\.assert_not_called",
    ]
]
MOCK_PATTERNS = [
    re.compile(p)
    for p in [
        r"@(?:mock\.)?patch",
        r"Mock\(\)",
        r"MagicMock\(\)",
        r"mocker\.",
        r"monkeypatch\.",
    ]
]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(", re.MULTILINE)

# Python has no barrel-file expansion in coverage mapping.
BARREL_BASENAMES: set[str] = set()


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True if the file contains runtime logic worth testing."""
    del filepath
    return bool(_PY_DEF_RE.search(content))


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Best-effort module-spec to source-file resolution for direct imports."""
    module_path = spec.strip().replace(".", "/")
    if not module_path or module_path.startswith("/"):
        return None

    candidates = (
        f"{module_path}.py",
        f"{module_path}/__init__.py",
    )
    # Common source layout prefixes to try when direct match fails
    _SRC_PREFIXES = ("src/",)
    for candidate in candidates:
        if candidate in production_files:
            return candidate
        # Try src/-prefixed variants for src-layout projects
        for prefix in _SRC_PREFIXES:
            prefixed = f"{prefix}{candidate}"
            if prefixed in production_files:
                return prefixed
        if test_path:
            sibling = os.path.join(os.path.dirname(test_path), candidate)
            if sibling in production_files:
                return sibling
    return None


def resolve_barrel_reexports(_filepath: str, _production_files: set[str]) -> set[str]:
    """Python has no barrel-file re-export expansion for coverage mapping."""
    return set()


def parse_test_import_specs(content: str) -> list[str]:
    """Extract import specs from Python test content.

    For ``from package import name``, emits both ``package`` and
    ``package.name`` so that submodule imports (e.g.
    ``from desloppify.engine._state import filtering``) resolve to
    the submodule file rather than just the package ``__init__.py``.
    """
    specs: list[str] = []
    for m in PY_IMPORT_RE.finditer(content):
        if m.group(3):
            # Plain ``import X.Y.Z``
            specs.append(m.group(3))
        elif m.group(1):
            package = m.group(1)
            imported_name = m.group(2)
            specs.append(package)
            if imported_name:
                specs.append(f"{package}.{imported_name}")
    return specs


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map a Python test file path to a production file by naming convention."""
    basename = os.path.basename(test_path)
    dirname = os.path.dirname(test_path)
    parent = os.path.dirname(dirname)

    candidates: list[str] = []

    # test_X.py -> X.py
    if basename.startswith("test_"):
        src = basename[5:]
        candidates.append(os.path.join(dirname, src))
        if parent:
            candidates.append(os.path.join(parent, src))

    # X_test.py -> X.py
    if basename.endswith("_test.py"):
        src = basename[:-8] + ".py"
        candidates.append(os.path.join(dirname, src))
        if parent:
            candidates.append(os.path.join(parent, src))

    for prod in production_set:
        prod_base = os.path.basename(prod)
        for c in candidates:
            if os.path.basename(c) == prod_base and prod in production_set:
                return prod

    for c in candidates:
        if c in production_set:
            return c

    return None


def strip_test_markers(basename: str) -> str | None:
    """Strip Python test naming markers to derive a source basename."""
    if basename.startswith("test_"):
        return basename[5:]
    suffix = "_test.py"
    if basename.endswith(suffix):
        stem = basename[: -len(suffix)]
        return f"{stem}.py"
    return None


def strip_comments(content: str) -> str:
    """Strip Python comments while respecting string literals."""
    return "\n".join(_strip_py_comment(line) for line in content.splitlines())


def _strip_py_comment(line: str) -> str:
    """Strip Python # comments while respecting string literals."""
    in_str = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == "\\" and i + 1 < len(line):
                continue
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "#" and not in_str:
            return line[:i]
    return line
