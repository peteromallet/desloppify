"""C#-specific review heuristics and guidance."""

from __future__ import annotations

import re


REVIEW_GUIDANCE = {
    "patterns": [
        "Check for async methods that never await or block on .Result/.Wait()",
        "Look for overly large service classes with mixed responsibilities",
        "Flag static mutable state shared across request or thread boundaries",
        "Check for duplicate business rules across sibling classes",
        "Look for expression-bodied methods with hidden side effects and vague names",
    ],
    "auth": [
        "Check controller/action authorization consistency ([Authorize], policy usage)",
        "Flag data access methods building SQL from string interpolation or concatenation",
        "Look for token/cookie handling without explicit validation or expiry checks",
        "Verify admin/service-role operations are isolated and auditable",
    ],
    "naming": "C# uses PascalCase for public members/types and camelCase for locals/parameters. "
              "Check for inconsistent naming inside the same layer.",
}

MIGRATION_PATTERN_PAIRS = [
    ("Newtonsoft→System.Text.Json", re.compile(r"\bNewtonsoft\.Json\b"), re.compile(r"\bSystem\.Text\.Json\b")),
    ("SqlClient→Dapper/EF", re.compile(r"\bSqlConnection\b|\bSqlCommand\b"), re.compile(r"\bDapper\b|\bDbContext\b")),
    ("sync→async APIs", re.compile(r"\b[A-Za-z_]\w+\s*\([^)]*\)\s*\{"), re.compile(r"\basync\s+Task\b")),
]

MIGRATION_MIXED_EXTENSIONS: set[str] = set()

LOW_VALUE_PATTERN = re.compile(r"(?:^|/)(?:AssemblyInfo|GlobalUsings)\.cs$")


def module_patterns(content: str) -> list[str]:
    """Return C#-specific module convention markers for a file."""
    out: list[str] = []
    if re.search(r"\bnamespace\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", content):
        out.append("namespace")
    if re.search(r"\b(?:public|internal)\s+(?:class|record|struct)\s+\w+", content):
        out.append("public_types")
    if re.search(r"\bpublic\s+.*\(", content):
        out.append("public_methods")
    return out


def api_surface(file_contents: dict[str, str]) -> dict:
    """Compute C# API-surface consistency context."""
    from ...utils import rel

    sync_async_mix: list[str] = []
    for filepath, content in file_contents.items():
        has_sync = bool(re.search(r"\bpublic\s+(?:\w+\s+)+\w+\s*\(", content))
        has_async = bool(re.search(r"\bpublic\s+async\s+Task(?:<[^>]+>)?\s+\w+\s*\(", content))
        if has_sync and has_async:
            sync_async_mix.append(rel(filepath))
    if not sync_async_mix:
        return {}
    return {"sync_async_mix": sync_async_mix[:20]}
