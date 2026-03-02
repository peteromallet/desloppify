"""PHP-specific test coverage heuristics and mappings.

Supports PHPUnit (tests/Feature/, tests/Unit/) and Pest naming conventions.
Handles ``use`` statement parsing for import-based coverage mapping.
"""

from __future__ import annotations

import os
import re

# ── Assertion / mock / snapshot patterns ──────────────────────

ASSERT_PATTERNS = [
    re.compile(p)
    for p in [
        r"\$this->assert\w+\(",
        r"\$this->expect\w*\(",
        r"\bexpect\s*\(",
        r"\bassertTrue\b",
        r"\bassertFalse\b",
        r"\bassertEquals\b",
        r"\bassertSame\b",
        r"\bassertCount\b",
        r"\bassertNull\b",
        r"\bassertNotNull\b",
        r"\bassertInstanceOf\b",
        r"\bassertContains\b",
        r"\bassertThrows\b",
        r"->assertStatus\(",
        r"->assertJson\(",
        r"->assertRedirect\(",
        r"->assertSee\(",
        r"->assertSessionHas\(",
        r"->assertDatabaseHas\(",
        r"->assertDatabaseMissing\(",
    ]
]

MOCK_PATTERNS = [
    re.compile(p)
    for p in [
        r"\$this->mock\(",
        r"\$this->partialMock\(",
        r"\bMockery::mock\(",
        r"\bMockery::spy\(",
        r"->shouldReceive\(",
        r"->expects\(\$this->",
        r"\$this->createMock\(",
        r"\bMock::handler\(",
    ]
]

SNAPSHOT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"->assertMatchesSnapshot\("),
    re.compile(r"->toMatchSnapshot\("),
]

TEST_FUNCTION_RE = re.compile(
    r"(?m)(?:"
    r"^\s*(?:public\s+)?function\s+(test\w+)\s*\("                 # PHPUnit method
    r"|^\s*/\*\*[^*]*@test[^/]*/\s*\n\s*(?:public\s+)?function\s+" # @test docblock
    r"|^\s*(?:it|test)\s*\("                                        # Pest test/it
    r")"
)

# PHP has no barrel files.
BARREL_BASENAMES: set[str] = set()


# ── PHP use-statement parser ──────────────────────────────────

# Matches: use App\Models\User;
# Matches: use App\Models\{User, Provider};
# Matches: use App\Models\User as UserModel;
_PHP_USE_RE = re.compile(
    r"^\s*use\s+"
    r"([\w\\]+)"          # namespace prefix
    r"(?:"
    r"\\\{([^}]+)\}"      # group import list
    r"|(?:\s+as\s+\w+)?"  # optional alias (ignored for resolution)
    r")\s*;",
    re.MULTILINE,
)


def parse_test_import_specs(content: str) -> list[str]:
    """Extract fully-qualified class names from PHP ``use`` statements.

    Handles both simple ``use App\\Models\\User;`` and group
    ``use App\\Models\\{User, Provider};`` forms.
    """
    specs: list[str] = []
    for m in _PHP_USE_RE.finditer(content):
        prefix = m.group(1)
        group = m.group(2)
        if group:
            for part in group.split(","):
                part = part.strip()
                if part:
                    specs.append(f"{prefix}\\{part}")
        else:
            specs.append(prefix)
    return specs


# ── Testable logic heuristic ─────────────────────────────────

# Files containing only interface/abstract declarations, config arrays,
# migrations with up()/down(), or empty classes lack testable logic.
_PHP_FUNCTION_RE = re.compile(
    r"(?m)^\s*(?:public|protected|private|static|\s)*\s*function\s+\w+\s*\(",
)
_PHP_INTERFACE_ONLY_RE = re.compile(
    r"(?m)^\s*(?:interface|abstract\s+class)\s+",
)
_PHP_CONFIG_RETURN_RE = re.compile(
    r"(?ms)\A\s*<\?php\s*\n\s*(?:/\*.*?\*/\s*\n\s*)?return\s+\[",
)


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True when a PHP file contains runtime logic worth testing.

    Returns False for:
    - Interface-only files
    - Config files (return [...])
    - Migration stubs (only up/down)
    - Files with no function definitions
    """
    lowered = filepath.replace("\\", "/").lower()

    # Config files: bare return array
    if _PHP_CONFIG_RETURN_RE.search(content):
        return False

    # Interface/abstract-only: no concrete method bodies
    if _PHP_INTERFACE_ONLY_RE.search(content):
        # If there's a concrete function body, it's testable
        if "function " in content and "{" in content.split("function ", 1)[1][:200]:
            pass  # has body, keep going
        else:
            return False

    # Migration stubs: only up() and down()
    if "/migrations/" in lowered or "database/migrations" in lowered:
        funcs = _PHP_FUNCTION_RE.findall(content)
        func_names = {
            re.search(r"function\s+(\w+)", f).group(1)  # type: ignore[union-attr]
            for f in funcs
            if re.search(r"function\s+(\w+)", f)
        }
        if func_names <= {"up", "down"}:
            return False

    return bool(_PHP_FUNCTION_RE.search(content))


# ── Runtime entrypoint detection ─────────────────────────────

_ENTRYPOINT_PATH_PATTERNS = [
    "routes/",
    "app/http/controllers/",
    "app/console/commands/",
    "app/http/middleware/",
    "app/providers/",
    "app/jobs/",
    "app/listeners/",
    "app/mail/",
    "app/notifications/",
    "app/policies/",
]

_ENTRYPOINT_CONTENT_PATTERNS = [
    re.compile(r"class\s+\w+\s+extends\s+(?:Controller|Command|Job|Mailable|Notification)\b"),
    re.compile(r"class\s+\w+\s+implements\s+ShouldQueue\b"),
    re.compile(r"Route::\w+\("),
    re.compile(r"Artisan::command\("),
]


def is_runtime_entrypoint(filepath: str, content: str) -> bool:
    """Detect PHP runtime entrypoints (controllers, commands, jobs, routes, etc.)."""
    lowered = filepath.replace("\\", "/").lower()

    for pattern in _ENTRYPOINT_PATH_PATTERNS:
        if pattern in lowered:
            return True

    return any(pat.search(content) for pat in _ENTRYPOINT_CONTENT_PATTERNS)


# ── Test-to-source mapping ───────────────────────────────────


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map a PHP test file to its production counterpart by naming convention.

    Handles PHPUnit conventions:
    - tests/Unit/Models/UserTest.php → app/Models/User.php
    - tests/Feature/Http/Controllers/UserControllerTest.php → app/Http/Controllers/UserController.php
    """
    basename = os.path.basename(test_path)
    if not basename.endswith("Test.php"):
        return None

    src_basename = basename[:-8] + ".php"  # strip "Test.php", add ".php"

    # Try direct basename match first
    for prod in production_set:
        if os.path.basename(prod) == src_basename:
            return prod

    # Try path-based mapping: tests/Unit/X → app/X, tests/Feature/X → app/X
    normalized = test_path.replace("\\", "/")
    for test_prefix in ("tests/Unit/", "tests/Feature/", "tests/"):
        idx = normalized.find(test_prefix)
        if idx == -1:
            continue
        rel_from_test = normalized[idx + len(test_prefix):]
        # Replace Test.php suffix
        if rel_from_test.endswith("Test.php"):
            rel_from_test = rel_from_test[:-8] + ".php"
        for src_prefix in ("app/", "src/", ""):
            candidate_suffix = src_prefix + rel_from_test
            for prod in production_set:
                if prod.replace("\\", "/").endswith(candidate_suffix):
                    return prod

    return None


def strip_test_markers(basename: str) -> str | None:
    """Strip PHP test naming markers to derive source basename.

    UserTest.php → User.php
    """
    if basename.endswith("Test.php"):
        return basename[:-8] + ".php"
    return None


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Resolve a PHP fully-qualified class name to a production file path.

    Maps ``App\\Models\\User`` → any production file ending in Models/User.php.
    """
    # Convert namespace to path segments
    parts = spec.replace("\\", "/").split("/")
    if len(parts) < 2:
        return None

    # Try matching progressively shorter suffixes (skip vendor prefixes)
    for prefix_len in range(1, min(3, len(parts))):
        suffix = "/".join(parts[prefix_len:]) + ".php"
        for prod in production_files:
            if prod.replace("\\", "/").endswith(suffix):
                return prod

    return None


def resolve_barrel_reexports(
    _filepath: str, _production_files: set[str]
) -> set[str]:
    """PHP has no barrel-file re-export expansion."""
    return set()


# ── Comment stripping ────────────────────────────────────────


def strip_comments(content: str) -> str:
    """Strip PHP comments (// and /* */) while preserving string literals."""
    out: list[str] = []
    in_block = False
    in_string: str | None = None
    i = 0
    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        if in_block:
            if ch == "\n":
                out.append("\n")
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue

        if in_string is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < len(content):
                out.append(content[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue

        if ch in ('"', "'"):
            in_string = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "/" and nxt == "/":
            while i < len(content) and content[i] != "\n":
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)
