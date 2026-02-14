"""Test coverage mapping — import resolution, naming conventions, quality analysis."""

from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path

from ..utils import PROJECT_ROOT, SRC_PATH

# ── Assertion / mock / snapshot patterns ──────────────────

PY_ASSERT_PATTERNS = [
    re.compile(p) for p in [
        r"^\s*assert\s+", r"self\.assert\w+\(", r"pytest\.raises\(",
        r"\.assert_called", r"\.assert_not_called",
    ]
]
TS_ASSERT_PATTERNS = [
    re.compile(p) for p in [
        r"expect\(", r"assert\.", r"\.should\.",
        r"\b(?:getBy|findBy|getAllBy|findAllBy)\w+\(",
        r"\bwaitFor\(",
        r"\.toBeInTheDocument\(",
        r"\.toBeVisible\(",
        r"\.toHaveTextContent\(",
        r"\.toHaveAttribute\(",
    ]
]
PY_MOCK_PATTERNS = [
    re.compile(p) for p in [
        r"@(?:mock\.)?patch", r"Mock\(\)", r"MagicMock\(\)", r"mocker\.", r"monkeypatch\.",
    ]
]
TS_MOCK_PATTERNS = [
    re.compile(p) for p in [
        r"jest\.mock\(", r"jest\.spyOn\(", r"vi\.mock\(", r"vi\.spyOn\(", r"sinon\.",
    ]
]
TS_SNAPSHOT_PATTERNS = [
    re.compile(p) for p in [
        r"toMatchSnapshot", r"toMatchInlineSnapshot",
    ]
]
CSHARP_ASSERT_PATTERNS = [
    re.compile(p) for p in [
        r"\bAssert\.\w+\(",
        r"\bShould\(\)\.\w+\(",
        r"\bFluentAssertions\b",
    ]
]
CSHARP_MOCK_PATTERNS = [
    re.compile(p) for p in [
        r"\bMock<",
        r"\bSubstitute\.For<",
        r"\bFakeItEasy\b",
    ]
]

PY_TEST_FUNC = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(")
TS_TEST_FUNC = re.compile(r"""(?:it|test)\s*\(\s*['"]""")
CSHARP_TEST_FUNC = re.compile(
    r"(?m)^\s*\[(?:Fact|Theory|Test(?:Method|Case)?)\]"
)


def _import_based_mapping(
    graph: dict, test_files: set[str], production_files: set[str],
) -> set[str]:
    """Map test files to production files via import edges.

    For test files in the graph, uses the graph's import edges.
    For test files NOT in the graph (external), reads the file and parses
    Python/TS import statements to find references to production files.
    """
    tested = set()
    # Build module-name→path index for resolving test imports
    prod_by_module: dict[str, str] = {}
    root_str = str(PROJECT_ROOT) + os.sep
    for pf in production_files:
        # Convert to relative path from PROJECT_ROOT for module name mapping
        rel_pf = pf[len(root_str):] if pf.startswith(root_str) else pf
        mod = rel_pf.replace("/", ".").replace("\\", ".")
        if mod.endswith(".py"):
            mod = mod[:-3]
        elif mod.endswith(".ts") or mod.endswith(".tsx"):
            mod = mod.rsplit(".", 1)[0]
        prod_by_module[mod] = pf
        # __init__.py: also map the package path (e.g. "desloppify.lang" → __init__.py)
        if mod.endswith(".__init__"):
            prod_by_module[mod[:-len(".__init__")]] = pf
        # Also map just the final module name: "utils" → path
        parts = mod.split(".")
        if parts:
            prod_by_module[parts[-1]] = pf

    for tf in test_files:
        entry = graph.get(tf)
        if entry is not None:
            for imp in entry.get("imports", set()):
                if imp in production_files:
                    tested.add(imp)
        else:
            # External test file: parse imports from source
            tested |= _parse_test_imports(tf, production_files, prod_by_module)

    # Expand barrel files (index.ts/index.tsx) — one level deep
    barrel_files = [
        f for f in tested
        if os.path.basename(f) in ("index.ts", "index.tsx")
    ]
    for bf in barrel_files:
        tested |= _resolve_barrel_reexports(bf, production_files)

    return tested


_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE
)
_TS_IMPORT_RE = re.compile(
    r"""(?:from|import)\s+['"]([^'"]+)['"]""", re.MULTILINE
)


_TS_EXTENSIONS = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]


def _resolve_ts_import(
    spec: str, test_path: str, production_files: set[str],
) -> str | None:
    """Resolve a TS import specifier to a production file path.

    Handles @/ and ~/ aliases (via SRC_PATH), relative paths (./  ../),
    and probes common extensions (.ts, .tsx, /index.ts, /index.tsx).
    """
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
        # Also try resolving symlinks / normalising for on-disk check
        try:
            resolved = str(Path(str(base) + ext).resolve())
            if resolved in production_files:
                return resolved
        except OSError:
            pass
    return None


_REEXPORT_RE = re.compile(
    r"""^export\s+(?:\{[^}]*\}|\*)\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE
)


def _resolve_barrel_reexports(
    filepath: str, production_files: set[str],
) -> set[str]:
    """Resolve re-exports from a barrel file (index.ts/index.tsx).

    One level deep only — no recursive barrel chaining.
    Returns the set of production files re-exported by this barrel.
    """
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return set()

    results = set()
    for m in _REEXPORT_RE.finditer(content):
        spec = m.group(1)
        resolved = _resolve_ts_import(spec, filepath, production_files)
        if resolved:
            results.add(resolved)
    return results


def _parse_test_imports(
    test_path: str, production_files: set[str], prod_by_module: dict[str, str],
) -> set[str]:
    """Parse import statements from a test file and resolve to production files."""
    tested = set()
    try:
        content = Path(test_path).read_text()
    except (OSError, UnicodeDecodeError):
        return tested

    # Try Python imports
    for m in _PY_IMPORT_RE.finditer(content):
        module = m.group(1) or m.group(2)
        if not module:
            continue
        # Try full module path and progressively shorter prefixes
        parts = module.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in prod_by_module:
                tested.add(prod_by_module[candidate])
                break

    # Try TS imports
    for m in _TS_IMPORT_RE.finditer(content):
        spec = m.group(1)
        if not spec:
            continue
        # First try proper resolution (relative paths, @/ alias)
        resolved = _resolve_ts_import(spec, test_path, production_files)
        if resolved:
            tested.add(resolved)
            continue
        # Fallback: fuzzy module lookup
        cleaned = spec.lstrip("./").replace("/", ".")
        if cleaned in prod_by_module:
            tested.add(prod_by_module[cleaned])

    return tested


def _map_test_to_source(
    test_path: str, production_set: set[str], lang_name: str,
) -> str | None:
    """Try to match a test file to a production file by naming convention."""
    basename = os.path.basename(test_path)
    dirname = os.path.dirname(test_path)
    parent = os.path.dirname(dirname)

    candidates: list[str] = []

    if lang_name == "python":
        # test_X.py → X.py
        if basename.startswith("test_"):
            src = basename[5:]
            candidates.append(os.path.join(dirname, src))
            if parent:
                candidates.append(os.path.join(parent, src))
        # X_test.py → X.py
        if basename.endswith("_test.py"):
            src = basename[:-8] + ".py"
            candidates.append(os.path.join(dirname, src))
            if parent:
                candidates.append(os.path.join(parent, src))
    elif lang_name == "csharp":
        # FooTests.cs / FooTest.cs / Foo.Tests.cs -> Foo.cs
        src = basename
        src = src.replace(".Tests.", ".").replace(".Test.", ".")
        if src.endswith("Tests.cs"):
            src = src[:-8] + ".cs"
        elif src.endswith("Test.cs"):
            src = src[:-7] + ".cs"
        candidates.append(os.path.join(dirname, src))
        if parent:
            candidates.append(os.path.join(parent, src))
        # tests/Foo.cs -> ../Foo.cs
        dir_basename = os.path.basename(dirname).lower()
        if dir_basename in ("tests", "test") and parent:
            candidates.append(os.path.join(parent, basename))
    else:  # typescript
        # X.test.ts → X.ts, X.test.tsx → X.tsx
        for pattern in (".test.", ".spec."):
            if pattern in basename:
                src = basename.replace(pattern, ".")
                candidates.append(os.path.join(dirname, src))
                if parent:
                    candidates.append(os.path.join(parent, src))
        # __tests__/X.ts → ../X.ts
        dir_basename = os.path.basename(dirname)
        if dir_basename == "__tests__" and parent:
            candidates.append(os.path.join(parent, basename))

    # Fuzzy: strip test/spec suffix and try matching basename
    for prod in production_set:
        prod_base = os.path.basename(prod)
        for c in candidates:
            if os.path.basename(c) == prod_base:
                # Check if the candidate path matches (same dir or parent)
                if prod in production_set:
                    return prod

    # Direct path match
    for c in candidates:
        if c in production_set:
            return c

    return None


def _naming_based_mapping(
    test_files: set[str], production_files: set[str], lang_name: str,
) -> set[str]:
    """Map test files to production files by naming conventions."""
    tested = set()
    # Build basename → set of full paths for fast lookup
    prod_by_basename: dict[str, list[str]] = {}
    for p in production_files:
        bn = os.path.basename(p)
        prod_by_basename.setdefault(bn, []).append(p)

    for tf in test_files:
        matched = _map_test_to_source(tf, production_files, lang_name)
        if matched:
            tested.add(matched)
            continue

        # Fallback: fuzzy basename matching
        basename = os.path.basename(tf)
        src_name = _strip_test_markers(basename, lang_name)
        if src_name and src_name in prod_by_basename:
            for p in prod_by_basename[src_name]:
                tested.add(p)

    return tested


def _strip_test_markers(basename: str, lang_name: str) -> str | None:
    """Strip test naming markers from a basename to get the source name."""
    if lang_name == "python":
        if basename.startswith("test_"):
            return basename[5:]
        if basename.endswith("_test.py"):
            return basename[:-8] + ".py"
    elif lang_name == "csharp":
        out = basename.replace(".Tests.", ".").replace(".Test.", ".")
        if out.endswith("Tests.cs"):
            return out[:-8] + ".cs"
        if out.endswith("Test.cs"):
            return out[:-7] + ".cs"
        return out
    else:
        for marker in (".test.", ".spec."):
            if marker in basename:
                return basename.replace(marker, ".")
    return None


def _transitive_coverage(
    directly_tested: set[str],
    graph: dict,
    production_files: set[str],
) -> set[str]:
    """BFS from directly-tested files through dep graph imports.

    Returns production files reachable from tested files (transitively covered).
    """
    visited = set(directly_tested)
    queue = deque(directly_tested)

    while queue:
        current = queue.popleft()
        entry = graph.get(current)
        if entry is None:
            continue
        for imp in entry.get("imports", set()):
            if imp in production_files and imp not in visited:
                visited.add(imp)
                queue.append(imp)

    # Transitively covered = reachable but NOT directly tested
    return visited - directly_tested


def _strip_py_comment(line: str) -> str:
    """Strip Python # comments while respecting string literals."""
    in_str = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == '\\' and i + 1 < len(line):
                continue  # skip escaped char (next iteration handles it)
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == '#' and not in_str:
            return line[:i]
    return line


def _analyze_test_quality(
    test_files: set[str], lang_name: str,
) -> dict[str, dict]:
    """Analyze quality of each test file.

    Returns {test_path: {"assertions": int, "mocks": int, "test_functions": int,
                          "snapshots": int, "quality": str}}
    """
    if lang_name == "python":
        assert_pats = PY_ASSERT_PATTERNS
        mock_pats = PY_MOCK_PATTERNS
        test_func_re = PY_TEST_FUNC
    elif lang_name == "csharp":
        assert_pats = CSHARP_ASSERT_PATTERNS
        mock_pats = CSHARP_MOCK_PATTERNS
        test_func_re = CSHARP_TEST_FUNC
    else:
        assert_pats = TS_ASSERT_PATTERNS
        mock_pats = TS_MOCK_PATTERNS
        test_func_re = TS_TEST_FUNC

    quality_map: dict[str, dict] = {}

    for tf in test_files:
        try:
            content = Path(tf).read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Strip comments before pattern matching
        if lang_name == "typescript":
            from ..lang.typescript.detectors._smell_helpers import _strip_ts_comments
            stripped = _strip_ts_comments(content)
        else:
            stripped = "\n".join(_strip_py_comment(line) for line in content.splitlines())

        lines = stripped.splitlines()

        # Use any() per line to avoid double-counting when multiple patterns
        # match the same line (e.g. expect(el).toBeVisible() matching both)
        assertions = sum(
            1 for line in lines
            if any(pat.search(line) for pat in assert_pats)
        )
        mocks = sum(
            1 for line in lines
            if any(pat.search(line) for pat in mock_pats)
        )
        snapshots = sum(
            1 for line in lines
            if any(pat.search(line) for pat in TS_SNAPSHOT_PATTERNS)
        ) if lang_name == "typescript" else 0

        test_functions = len(test_func_re.findall(stripped))

        # Classify quality
        if test_functions == 0:
            quality = "no_tests"
        elif assertions == 0:
            quality = "assertion_free"
        elif mocks > assertions:
            quality = "over_mocked"
        elif snapshots > 0 and snapshots > assertions * 0.5:
            quality = "snapshot_heavy"
        elif test_functions > 0 and assertions / test_functions < 1:
            quality = "smoke"
        elif assertions / test_functions >= 3:
            quality = "thorough"
        else:
            quality = "adequate"

        quality_map[tf] = {
            "assertions": assertions,
            "mocks": mocks,
            "test_functions": test_functions,
            "snapshots": snapshots,
            "quality": quality,
        }

    return quality_map


def _get_test_files_for_prod(
    prod_file: str,
    test_files: set[str],
    graph: dict,
    lang_name: str,
) -> list[str]:
    """Find which test files test a given production file."""
    result = []
    for tf in test_files:
        entry = graph.get(tf)
        if entry and prod_file in entry.get("imports", set()):
            result.append(tf)
            continue
        # Naming match
        if _map_test_to_source(tf, {prod_file}, lang_name) == prod_file:
            result.append(tf)
    return result
