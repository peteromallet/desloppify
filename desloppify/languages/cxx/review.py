"""Review guidance hooks for C/C++."""

from __future__ import annotations

import os
import re

from desloppify.base.discovery.file_paths import rel

HOLISTIC_REVIEW_DIMENSIONS: list[str] = [
    "cross_module_architecture",
    "abstraction_fitness",
    "api_surface_coherence",
    "design_coherence",
]

REVIEW_GUIDANCE = {
    "patterns": [
        "Keep header and source responsibilities aligned.",
        "Watch for namespace drift and accidental cross-module leakage.",
        "Prefer one ownership style per subsystem; mixed raw and smart-pointer lifecycles are a smell.",
        "Prefer explicit boundaries between platform, runtime, and library code.",
    ],
    "naming": "Use consistent type, namespace, and file naming conventions.",
}

MIGRATION_PATTERN_PAIRS: list[tuple[str, object, object]] = []
MIGRATION_MIXED_EXTENSIONS: set[str] = set()
LOW_VALUE_PATTERN = re.compile(
    r"^\s*(?:#pragma\s+once|#include\s+<[^>]+>\s*$)",
    re.MULTILINE,
)
_NAMESPACE_RE = re.compile(r"\bnamespace\s+[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*")
_PUBLIC_TYPE_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b")
_PUBLIC_SECTION_RE = re.compile(
    r"(?ms)\bpublic\s*:\s*(.*?)(?:(?:private|protected)\s*:|\};|\})"
)
_FUNCTION_RE = re.compile(
    r"(?m)^\s*(?:inline\s+|static\s+|virtual\s+|constexpr\s+|friend\s+|extern\s+)*"
    r"(?>(?:[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)*(?:<[^;{}()]+>)?[\s*&:]+)+)"
    r"([A-Za-z_~]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:;|\{)"
)
_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "return"}


_HEADER_LIKE_EXTENSIONS = (
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".ipp",
    ".inl",
    ".tpp",
    ".txx",
    ".tcc",
)


def _public_function_names(content: str) -> list[str]:
    names: set[str] = set()
    for section in _PUBLIC_SECTION_RE.findall(content):
        for match in _FUNCTION_RE.finditer(section):
            name = match.group(1)
            if name not in _CONTROL_KEYWORDS:
                names.add(name)
    for match in _FUNCTION_RE.finditer(content):
        name = match.group(1)
        if name not in _CONTROL_KEYWORDS:
            names.add(name)
    return sorted(names)


def module_patterns(content: str) -> list[str]:
    """Extract module-like review anchors from C/C++ content."""
    out: list[str] = []
    if _NAMESPACE_RE.search(content):
        out.append("namespace")
    if _PUBLIC_TYPE_RE.search(content):
        out.append("public_types")
    if _public_function_names(content):
        out.append("public_methods")
    return out


def api_surface(file_contents: dict[str, str]) -> dict[str, list[str]]:
    """Build a minimal API surface summary for C/C++ files."""
    public_types: set[str] = set()
    public_functions: set[str] = set()
    public_headers: list[str] = []

    for filepath, content in file_contents.items():
        if not filepath.endswith(_HEADER_LIKE_EXTENSIONS):
            continue
        for match in _PUBLIC_TYPE_RE.finditer(content):
            public_types.add(match.group(1))
        public_functions.update(_public_function_names(content))
        public_headers.append(rel(filepath) if os.path.isabs(filepath) else filepath)

    summary: dict[str, list[str]] = {}
    if public_types:
        summary["public_types"] = sorted(public_types)
    if public_functions:
        summary["public_functions"] = sorted(public_functions)
    if public_headers:
        summary["public_headers"] = sorted(public_headers)[:20]
    return summary
