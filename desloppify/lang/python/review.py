"""Python-specific review heuristics and guidance."""

from __future__ import annotations

import re


REVIEW_GUIDANCE = {
    "patterns": [
        "Check for `async def` functions that never `await` — they add overhead with no benefit",
        "Look for bare `except:` or `except Exception:` that swallow errors silently",
        "Verify `@lru_cache` isn't used on methods with mutable default args",
        "Flag `subprocess` calls without `timeout` parameter",
        "Check for mutable class-level variables (list/dict/set as class attributes)",
        "Verify `__all__` is defined when `from module import *` is used",
    ],
    "auth": [
        "Check `@login_required` consistency — sibling views in same module should all have it or none",
        "Flag `request.user` access in views without `@login_required` or equivalent auth decorator",
        "Look for unvalidated `request.data` / `request.POST` used directly in ORM queries",
        "Verify permission decorators match route sensitivity (admin views need `@staff_member_required`)",
    ],
    "naming": "Python uses snake_case for functions/variables, PascalCase for classes. "
              "Check for Java-style camelCase leaking in.",
}

MIGRATION_PATTERN_PAIRS = [
    ("os.path→pathlib", re.compile(r"\bos\.path\b"), re.compile(r"\bpathlib\b|\bPath\(")),
    ("format()→f-string", re.compile(r"\.format\("), re.compile(r'\bf"')),
    ("unittest→pytest", re.compile(r"\bunittest\b"), re.compile(r"\bpytest\b")),
    ("print→logging", re.compile(r"\bprint\("), re.compile(r"\blogging\.\w+\(")),
]

# Python has no mixed JS/TS migration extensions to track.
MIGRATION_MIXED_EXTENSIONS: set[str] = set()

LOW_VALUE_PATTERN = re.compile(r"(?:^|/)(?:types|constants|enums|index)\.[a-z]+$")


def module_patterns(content: str) -> list[str]:
    """Return Python-specific module convention markers for a file."""
    out: list[str] = []
    if re.search(r"\bdef\s+\w+", content):
        out.append("functions")
    if re.search(r"^__all__\s*=", content, re.MULTILINE):
        out.append("explicit_api")
    return out


def api_surface(_file_contents: dict[str, str]) -> dict:
    """Python-specific API surface summary for holistic review."""
    return {}
