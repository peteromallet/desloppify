"""TypeScript-specific test coverage heuristics and mappings."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.core._internal.text_utils import strip_c_style_comments
from desloppify.utils import SRC_PATH

TS_IMPORT_RE = re.compile(r"""(?:from|import)\s+['\"]([^'\"]+)['\"]""", re.MULTILINE)
TS_REEXPORT_RE = re.compile(
    r"""^export\s+(?:\{[^}]*\}|\*)\s+from\s+['\"]([^'\"]+)['\"]""", re.MULTILINE
)

ASSERT_PATTERNS = [
    re.compile(p)
    for p in [
        r"expect\(",
        r"assert\.",
        r"\.should\.",
        r"\b(?:getBy|findBy|getAllBy|findAllBy)\w+\(",
        r"\bwaitFor\(",
        r"\.toBeInTheDocument\(",
        r"\.toBeVisible\(",
        r"\.toHaveTextContent\(",
        r"\.toHaveAttribute\(",
    ]
]
MOCK_PATTERNS = [
    re.compile(p)
    for p in [
        r"jest\.mock\(",
        r"jest\.spyOn\(",
        r"vi\.mock\(",
        r"vi\.spyOn\(",
        r"sinon\.",
    ]
]
SNAPSHOT_PATTERNS = [
    re.compile(p)
    for p in [
        r"toMatchSnapshot",
        r"toMatchInlineSnapshot",
    ]
]
TEST_FUNCTION_RE = re.compile(r"""(?:it|test)\s*\(\s*['\"]""")
PLACEHOLDER_LABEL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcoverage smoke\b",
        r"\bdirect test coverage entry\b",
        r"\bplaceholder\b",
    ]
]
EXPECT_COMPARISON_RE = re.compile(
    r"""expect\(\s*(?P<left>[^)]+?)\s*\)\s*\.(?:toBe|toEqual|toStrictEqual)\(\s*(?P<right>[^)]+?)\s*\)"""
)

BARREL_BASENAMES = {"index.ts", "index.tsx"}
_TS_EXTENSIONS = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]
logger = logging.getLogger(__name__)


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True if a TypeScript file has runtime logic worth testing."""
    if filepath.endswith(".d.ts"):
        return False

    in_block_comment = False
    brace_context = False  # True when inside type/interface/import/export braces
    brace_depth = 0

    for line in content.splitlines():
        stripped = line.strip()

        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block_comment = True
            continue

        if not stripped or stripped.startswith("//"):
            continue

        if brace_context:
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0:
                brace_context = False
                brace_depth = 0
            continue

        if re.match(r"(?:export\s+)?(?:type|interface)\s+\w+", stripped):
            opens = stripped.count("{")
            closes = stripped.count("}")
            if opens > closes:
                brace_context = True
                brace_depth = opens - closes
            continue

        if re.match(r"import\s+", stripped):
            if "{" in stripped and "}" not in stripped:
                brace_context = True
                brace_depth = stripped.count("{") - stripped.count("}")
            continue

        if re.match(r"export\s+(?:type\s+)?\{", stripped):
            if "}" not in stripped:
                brace_context = True
                brace_depth = stripped.count("{") - stripped.count("}")
            continue
        if re.match(r"export\s+\*\s*(?:as\s+\w+\s+)?from\s+", stripped):
            continue

        if re.match(r"export\s+default\s+(?:type|interface)\s+", stripped):
            opens = stripped.count("{")
            closes = stripped.count("}")
            if opens > closes:
                brace_context = True
                brace_depth = opens - closes
            continue

        if re.match(r"declare\s+", stripped):
            opens = stripped.count("{")
            closes = stripped.count("}")
            if opens > closes:
                brace_context = True
                brace_depth = opens - closes
            continue

        if re.match(r"^[}\])\s;,]*$", stripped):
            continue

        return True

    return False


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Resolve a TypeScript import specifier to a production file path."""
    if spec.startswith("@/") or spec.startswith("~/"):
        base = Path(str(SRC_PATH) + "/" + spec[2:])
    elif spec.startswith("."):
        test_dir = Path(test_path).parent
        base = (test_dir / spec).resolve()
    else:
        return None

    for ext in _TS_EXTENSIONS:
        candidate = str(Path(str(base) + ext))
        if candidate in production_files:
            return candidate
        try:
            resolved = str(Path(str(base) + ext).resolve())
            if resolved in production_files:
                return resolved
        except OSError as exc:
            log_best_effort_failure(
                logger,
                f"resolve TypeScript import specifier {spec} from {test_path}",
                exc,
            )
    return None


def parse_test_import_specs(content: str) -> list[str]:
    """Extract import specs from TypeScript test content."""
    return [m.group(1) for m in TS_IMPORT_RE.finditer(content) if m.group(1)]


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    """Resolve one-hop TypeScript barrel re-exports to concrete production files."""
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError) as exc:
        log_best_effort_failure(logger, f"read barrel re-export source {filepath}", exc)
        return set()

    results = set()
    for match in TS_REEXPORT_RE.finditer(content):
        spec = match.group(1)
        resolved = resolve_import_spec(spec, filepath, production_files)
        if resolved:
            results.add(resolved)
    return results


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map a TypeScript test file path to a production file by naming convention."""
    basename = os.path.basename(test_path)
    dirname = os.path.dirname(test_path)
    parent = os.path.dirname(dirname)

    candidates: list[str] = []

    for pattern in (".test.", ".spec."):
        if pattern in basename:
            src = basename.replace(pattern, ".")
            candidates.append(os.path.join(dirname, src))
            if parent:
                candidates.append(os.path.join(parent, src))

    dir_basename = os.path.basename(dirname)
    if dir_basename == "__tests__" and parent:
        candidates.append(os.path.join(parent, basename))

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
    """Strip TypeScript test naming markers to derive a source basename."""
    for marker in (".test.", ".spec."):
        if marker in basename:
            return basename.replace(marker, ".")
    return None


def strip_comments(content: str) -> str:
    """Strip C-style comments for test quality analysis."""
    return strip_c_style_comments(content)


def _normalize_tautology_token(token: str) -> str | None:
    value = token.strip().rstrip(";")
    if not value:
        return None
    if value in {"true", "false", "null", "undefined"}:
        return value
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return str(float(value)) if "." in value else str(int(value))
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return f"str:{value[1:-1]}"
    return None


def is_placeholder_test(
    content: str, *, assertions: int, test_functions: int
) -> bool:
    """Heuristic for synthetic coverage-smoke tests with tautological assertions."""
    if assertions <= 0 or test_functions <= 0:
        return False

    tautological = 0
    for line in content.splitlines():
        match = EXPECT_COMPARISON_RE.search(line)
        if not match:
            continue
        left = _normalize_tautology_token(match.group("left"))
        right = _normalize_tautology_token(match.group("right"))
        if left is not None and left == right:
            tautological += 1

    if tautological == 0:
        return False

    has_placeholder_label = any(p.search(content) for p in PLACEHOLDER_LABEL_PATTERNS)
    if tautological >= assertions and (has_placeholder_label or assertions <= test_functions):
        return True
    if has_placeholder_label and (tautological / max(assertions, 1)) >= 0.5:
        return True
    return False
