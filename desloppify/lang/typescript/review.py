"""TypeScript-specific review heuristics and guidance."""

from __future__ import annotations

import re


REVIEW_GUIDANCE = {
    "patterns": [
        "Check for `useEffect` with empty dependency arrays that should react to state changes",
        "Look for `setTimeout`/`setInterval` used for synchronization instead of proper async patterns",
        "Flag React components with >15 props — likely needs decomposition",
        "Check for `dangerouslySetInnerHTML` without sanitization",
        "Verify `useRef` isn't overused as a state escape hatch (>5 refs in a component)",
        "Look for Context providers nested >5 deep — consider composition or state management",
    ],
    "auth": [
        "Check `useAuth()` / `getServerSession()` consistency — sibling routes should use the same pattern",
        "Flag API routes that access request body without validation (zod, yup, or manual checks)",
        "Look for Supabase RLS bypass patterns — `service_role` key used outside server-only code",
        "Verify auth middleware on API routes — sibling handlers should all check auth or none",
        "Flag `createClient` with hardcoded keys or missing `cookies()` in server components",
    ],
    "naming": "TypeScript uses camelCase for functions/variables, PascalCase for types/components. "
              "Check for inconsistency within modules.",
}

MIGRATION_PATTERN_PAIRS = [
    ("class→functional components", re.compile(r"\bclass\s+\w+\s+extends\s+(?:React\.)?Component\b"),
     re.compile(r"\bfunction\s+\w+\s*\([^)]*\)\s*\{.*?return\s*\(?\s*<", re.DOTALL)),
    ("axios→fetch", re.compile(r"\baxios\b"), re.compile(r"\bfetch\(")),
    ("moment→dayjs", re.compile(r"\bmoment\b"), re.compile(r"\bdayjs\b")),
    ("var→let/const", re.compile(r"\bvar\s+\w+"), re.compile(r"\b(?:let|const)\s+\w+")),
    ("require→import", re.compile(r"\brequire\("), re.compile(r"\bimport\s+")),
]

MIGRATION_MIXED_EXTENSIONS = {".js", ".ts", ".jsx", ".tsx"}

LOW_VALUE_PATTERN = re.compile(
    r"(?:^|/)(?:types|constants|enums|index)\.[a-z]+$"
    r"|\.d\.ts$"
)


def module_patterns(content: str) -> list[str]:
    """Return TypeScript-specific module convention markers for a file."""
    out: list[str] = []
    if re.search(r"\bexport\s+default\b", content):
        out.append("default_export")
    if re.search(r"\bexport\s+(?:function|const|class)\b", content):
        out.append("named_export")
    return out


def api_surface(file_contents: dict[str, str]) -> dict:
    """Compute TypeScript API-surface consistency context."""
    sync_async_mix: list[str] = []
    for filepath, content in file_contents.items():
        has_sync = bool(re.search(r"\bexport\s+function\s+\w+", content))
        has_async = bool(re.search(r"\bexport\s+async\s+function\s+\w+", content))
        if has_sync and has_async:
            from ...utils import rel
            sync_async_mix.append(rel(filepath))
    if not sync_async_mix:
        return {}
    return {"sync_async_mix": sync_async_mix[:20]}
