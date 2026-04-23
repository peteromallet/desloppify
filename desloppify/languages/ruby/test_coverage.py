"""Ruby-specific test coverage heuristics and mappings.

Supports RSpec (_spec.rb) and Minitest (test_*.rb / *_test.rb) naming conventions.
Handles ``require_relative`` and ``require`` statement parsing for import-based
coverage mapping, including cross-directory ``require_relative`` paths such as
``require_relative "../lib/my_module"`` from a ``spec/`` directory.
"""

from __future__ import annotations

import os
import re

# ── Assertion / mock / snapshot patterns ──────────────────────

ASSERT_PATTERNS = [
    re.compile(p)
    for p in [
        r"\bexpect\s*\(",
        r"\bshould\b",
        r"\bshould_not\b",
        r"\bassert\w*\s*\(",
        r"\brefute\w*\s*\(",
        r"\.to\s+(?:eq|be|raise_error|have_been_requested|include|match|be_nil|be_truthy|be_falsey)\b",
        r"\.not_to\s+raise_error",
    ]
]

MOCK_PATTERNS = [
    re.compile(p)
    for p in [
        r"\ballow\s*\(",
        r"\bexpect\s*\(",
        r"\breceive\s*\(",
        r"\band_return\b",
        r"\bstub_request\s*\(",
        r"\binstance_double\s*\(",
        r"\bdouble\s*\(",
        r"\bspy\s*\(",
    ]
]

SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []

TEST_FUNCTION_RE = re.compile(
    r"(?m)"
    r"(?:"
    r"^\s*(?:it|describe|context|specify|example)\s+['\"]"  # RSpec blocks
    r"|^\s*def\s+test_\w+"                                  # Minitest method
    r")"
)

# Ruby has no barrel files.
BARREL_BASENAMES: set[str] = set()

# ── require / require_relative parser ─────────────────────────

_REQUIRE_RE = re.compile(
    r"""(?m)^\s*require(?:_relative)?\s+['"]([^'"]+)['"]"""
)


def parse_test_import_specs(content: str) -> list[str]:
    """Extract import specs from Ruby test content.

    Returns the path strings from ``require`` and ``require_relative``
    statements so the caller can resolve them to production file paths.
    Standard library modules (no slashes, no ``../``) that look like simple
    names are also returned — the resolver will discard those that don't match
    any production file.
    """
    return [m.group(1) for m in _REQUIRE_RE.finditer(content)]


# ── Testable logic heuristic ─────────────────────────────────

_RUBY_DEF_RE = re.compile(
    r"(?m)^\s*(?:def\s+\w|class\s+\w|module\s+\w)"
)


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True when a Ruby file contains a method, class, or module definition."""
    del filepath
    return bool(_RUBY_DEF_RE.search(content))


# ── Import spec resolver ──────────────────────────────────────

def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Resolve a Ruby ``require``/``require_relative`` path to a production file.

    Handles:
    - Relative paths (``require_relative``): resolved from the test file's dir.
    - Bare names (``require``): checked as ``<spec>.rb`` and ``lib/<spec>.rb``.
    """
    if not spec:
        return None

    candidates: list[str] = []

    # Relative path (contains "/" or starts with "."): resolve from test_path dir.
    if "/" in spec or spec.startswith("."):
        if test_path:
            test_dir = os.path.dirname(test_path)
            raw = os.path.normpath(os.path.join(test_dir, spec))
            candidates.append(raw + ".rb")
            candidates.append(raw)
        else:
            candidates.append(os.path.normpath(spec) + ".rb")
    else:
        # Bare name — could be stdlib (json, time, etc.) or a gem.
        # Check common Ruby project layout locations.
        candidates.extend([
            f"{spec}.rb",
            f"lib/{spec}.rb",
        ])

    for candidate in candidates:
        # Normalise separators and leading ./
        normalised = candidate.replace("\\", "/").lstrip("./")
        if normalised in production_files:
            return normalised
        if candidate in production_files:
            return candidate

    return None


def resolve_barrel_reexports(
    _filepath: str, _production_files: set[str]
) -> set[str]:
    """Ruby has no barrel-file re-export expansion."""
    return set()


# ── Test marker stripping ─────────────────────────────────────

def strip_test_markers(basename: str) -> str | None:
    """Strip RSpec / Minitest naming markers to derive a source basename.

    ``user_spec.rb``  → ``user.rb``
    ``test_user.rb``  → ``user.rb``
    ``user_test.rb``  → ``user.rb``
    """
    if basename.endswith("_spec.rb"):
        return basename[: -len("_spec.rb")] + ".rb"
    if basename.startswith("test_") and basename.endswith(".rb"):
        return basename[len("test_"):].strip("_") + ".rb"
    if basename.endswith("_test.rb"):
        return basename[: -len("_test.rb")] + ".rb"
    return None


# ── Comment stripping ─────────────────────────────────────────

def strip_comments(content: str) -> str:
    """Strip Ruby # comments while preserving string literals."""
    out: list[str] = []
    for line in content.splitlines():
        out.append(_strip_ruby_comment(line))
    return "\n".join(out)


def _strip_ruby_comment(line: str) -> str:
    in_str: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == "\\" and i + 1 < len(line):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "#":
            return line[:i]
        i += 1
    return line
