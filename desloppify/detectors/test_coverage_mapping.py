"""Test coverage mapping — import resolution, naming conventions, quality analysis."""

from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path

from .lang_hooks import load_lang_hook_module
from ..utils import PROJECT_ROOT


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


def _load_lang_test_coverage_module(lang_name: str | None):
    """Load language-specific test coverage helpers from ``lang/<name>/test_coverage.py``."""
    return load_lang_hook_module(lang_name, "test_coverage") or object()


def _infer_lang_name(test_files: set[str], production_files: set[str]) -> str | None:
    """Infer language from known file extensions when explicit lang is unavailable."""
    paths = list(test_files) + list(production_files)

    try:
        from ..lang import available_langs, get_lang
    except Exception:
        return None

    best_lang = None
    best_count = -1
    langs = available_langs()
    if not langs:
        return None
    for lang_name in langs:
        try:
            exts = tuple(get_lang(lang_name).extensions)
        except Exception:
            exts = ()
        if not exts:
            continue
        count = sum(1 for path in paths if path.endswith(exts))
        if count > best_count:
            best_lang = lang_name
            best_count = count

    if best_lang is not None and best_count > 0:
        return best_lang
    return None


def _import_based_mapping(
    graph: dict,
    test_files: set[str],
    production_files: set[str],
    lang_name: str | None = None,
) -> set[str]:
    """Map test files to production files via import edges."""
    lang_name = lang_name or _infer_lang_name(test_files, production_files)
    mod = _load_lang_test_coverage_module(lang_name)

    tested = set()

    # Build module-name->path index for resolving test imports.
    prod_by_module: dict[str, str] = {}
    root_str = str(PROJECT_ROOT) + os.sep
    for pf in production_files:
        rel_pf = pf[len(root_str):] if pf.startswith(root_str) else pf
        module_name = rel_pf.replace("/", ".").replace("\\", ".")
        if "." in module_name:
            module_name = module_name.rsplit(".", 1)[0]
        prod_by_module[module_name] = pf

        # __init__.py: also map package path (e.g. "foo.bar" -> __init__.py).
        if module_name.endswith(".__init__"):
            prod_by_module[module_name[:-len(".__init__")]] = pf

        parts = module_name.split(".")
        if parts:
            prod_by_module[parts[-1]] = pf

    for tf in test_files:
        entry = graph.get(tf)
        if entry is not None:
            for imp in entry.get("imports", set()):
                if imp in production_files:
                    tested.add(imp)
        else:
            tested |= _parse_test_imports(tf, production_files, prod_by_module, lang_name)

    barrel_basenames = getattr(mod, "BARREL_BASENAMES", set())
    if barrel_basenames:
        barrel_files = [f for f in tested if os.path.basename(f) in barrel_basenames]
        for bf in barrel_files:
            tested |= _resolve_barrel_reexports(bf, production_files, lang_name)

    return tested


def _resolve_import(
    spec: str,
    test_path: str,
    production_files: set[str],
    lang_name: str | None,
) -> str | None:
    mod = _load_lang_test_coverage_module(lang_name)
    resolver = getattr(mod, "resolve_import_spec", None)
    if callable(resolver):
        return resolver(spec, test_path, production_files)
    return None


def _resolve_barrel_reexports(
    filepath: str,
    production_files: set[str],
    lang_name: str | None = None,
) -> set[str]:
    """Resolve one-hop re-exports using language-specific helpers."""
    if lang_name is None:
        lang_name = _infer_lang_name({filepath}, production_files)
    mod = _load_lang_test_coverage_module(lang_name)
    resolver = getattr(mod, "resolve_barrel_reexports", None)
    if callable(resolver):
        return resolver(filepath, production_files)
    return set()


def _parse_test_imports(
    test_path: str,
    production_files: set[str],
    prod_by_module: dict[str, str],
    lang_name: str | None = None,
) -> set[str]:
    """Parse import statements from a test file and resolve production files."""
    tested = set()
    try:
        content = Path(test_path).read_text()
    except (OSError, UnicodeDecodeError):
        return tested

    if lang_name is None:
        lang_name = _infer_lang_name({test_path}, production_files)

    mod = _load_lang_test_coverage_module(lang_name)
    parse_specs = getattr(mod, "parse_test_import_specs", None)
    if not callable(parse_specs):
        return tested

    for spec in parse_specs(content):
        if not spec:
            continue

        resolved = _resolve_import(spec, test_path, production_files, lang_name)
        if resolved:
            tested.add(resolved)
            continue

        # Fallback: module-name lookup with progressively shorter prefixes.
        cleaned = spec.lstrip("./").replace("/", ".")
        parts = cleaned.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in prod_by_module:
                tested.add(prod_by_module[candidate])
                break

    return tested


def _map_test_to_source(
    test_path: str,
    production_set: set[str],
    lang_name: str,
) -> str | None:
    """Match a test file to a production file using language conventions."""
    mod = _load_lang_test_coverage_module(lang_name)
    mapper = getattr(mod, "map_test_to_source", None)
    if callable(mapper):
        mapped = mapper(test_path, production_set)
        if mapped:
            return mapped

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
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
) -> set[str]:
    """Map test files to production files by naming conventions."""
    tested = set()

    prod_by_basename: dict[str, list[str]] = {}
    for p in production_files:
        bn = os.path.basename(p)
        prod_by_basename.setdefault(bn, []).append(p)

    for tf in test_files:
        matched = _map_test_to_source(tf, production_files, lang_name)
        if matched:
            tested.add(matched)
            continue

        basename = os.path.basename(tf)
        src_name = _strip_test_markers(basename, lang_name)
        if src_name and src_name in prod_by_basename:
            for p in prod_by_basename[src_name]:
                tested.add(p)

    return tested


def _strip_test_markers(basename: str, lang_name: str) -> str | None:
    """Strip test naming markers from a basename to derive source basename."""
    mod = _load_lang_test_coverage_module(lang_name)
    strip_markers = getattr(mod, "strip_test_markers", None)
    if callable(strip_markers):
        stripped = strip_markers(basename)
        if stripped:
            return stripped

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
    """BFS from directly-tested files through dep-graph imports."""
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

    return visited - directly_tested


def _strip_py_comment(line: str) -> str:
    """Strip Python # comments while respecting string literals."""
    from ..lang.python.test_coverage import _strip_py_comment as py_strip_py_comment

    return py_strip_py_comment(line)


def _analyze_test_quality(
    test_files: set[str],
    lang_name: str,
) -> dict[str, dict]:
    """Analyze test quality per file."""
    mod = _load_lang_test_coverage_module(lang_name)
    assert_pats = list(getattr(mod, "ASSERT_PATTERNS", []) or [])
    mock_pats = list(getattr(mod, "MOCK_PATTERNS", []) or [])
    snapshot_pats = list(getattr(mod, "SNAPSHOT_PATTERNS", []) or [])
    test_func_re = getattr(mod, "TEST_FUNCTION_RE", re.compile(r"$^"))
    strip_comments = getattr(mod, "strip_comments", None)

    if not assert_pats:
        if lang_name == "python":
            assert_pats = PY_ASSERT_PATTERNS
        elif lang_name == "csharp":
            assert_pats = CSHARP_ASSERT_PATTERNS
        else:
            assert_pats = TS_ASSERT_PATTERNS
    if not mock_pats:
        if lang_name == "python":
            mock_pats = PY_MOCK_PATTERNS
        elif lang_name == "csharp":
            mock_pats = CSHARP_MOCK_PATTERNS
        else:
            mock_pats = TS_MOCK_PATTERNS
    if not snapshot_pats and lang_name == "typescript":
        snapshot_pats = TS_SNAPSHOT_PATTERNS
    if not hasattr(test_func_re, "findall"):
        if lang_name == "python":
            test_func_re = PY_TEST_FUNC
        elif lang_name == "csharp":
            test_func_re = CSHARP_TEST_FUNC
        else:
            test_func_re = TS_TEST_FUNC
    if not callable(strip_comments):
        if lang_name == "python":
            strip_comments = lambda text: "\n".join(_strip_py_comment(line) for line in text.splitlines())
        else:
            strip_comments = lambda text: text

    quality_map: dict[str, dict] = {}

    for tf in test_files:
        try:
            content = Path(tf).read_text()
        except (OSError, UnicodeDecodeError):
            continue

        stripped = strip_comments(content)
        lines = stripped.splitlines()

        assertions = sum(1 for line in lines if any(pat.search(line) for pat in assert_pats))
        mocks = sum(1 for line in lines if any(pat.search(line) for pat in mock_pats))
        snapshots = sum(1 for line in lines if any(pat.search(line) for pat in snapshot_pats))
        test_functions = len(test_func_re.findall(stripped))

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
    """Find which test files exercise a given production file."""
    result = []
    for tf in test_files:
        entry = graph.get(tf)
        if entry and prod_file in entry.get("imports", set()):
            result.append(tf)
            continue
        if _map_test_to_source(tf, {prod_file}, lang_name) == prod_file:
            result.append(tf)
    return result
