"""Python-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Python: does the file contain any function definition?
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+", re.MULTILINE)

# Import parsing helpers
# Match both single-line and parenthesized multi-line imports:
#   from megaplan.evaluation import build_evaluation
#   from megaplan.evaluation import (build_evaluation, ...)
#   import megaplan.evaluation
PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import\s+\(?\s*(\w+)|import\s+([\w.]+))",
    re.MULTILINE,
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

# Python package __init__ files can explicitly re-export concrete submodules.
BARREL_BASENAMES: set[str] = {"__init__.py"}

PY_IMPORT_MODULE_RE = re.compile(
    r"(?P<name>\w+)\s*=\s*import_module\(\s*['\"](?P<spec>[\w.]+)['\"]\s*\)"
)
PY_SYS_MODULES_ALIAS_RE = re.compile(
    r"sys\.modules\[\s*__name__\s*\]\s*=\s*"
    r"(?:import_module\(\s*['\"](?P<spec>[\w.]+)['\"]\s*\)|(?P<name>\w+))"
)
PY_LOCAL_IMPORT_RE = re.compile(
    r"^\s*from\s+\.\s+import\s+(?P<names>[\w \t,]+)|"
    r"^\s*from\s+\.(?P<module>[\w.]+)\s+import\s+(?:\*|\(?\s*[\w \t,]+)",
    re.MULTILINE,
)

# Common source layout prefixes for src-layout projects (PEP 621).
_SRC_PREFIXES = ("src/",)


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/")


def _match_production_candidate(candidate: str, production_files: set[str]) -> str | None:
    normalized_candidate = _normalized_path(candidate).lstrip("/")
    exact_matches = [
        prod
        for prod in production_files
        if _normalized_path(prod).lstrip("/") == normalized_candidate
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]

    suffix = f"/{normalized_candidate}"
    suffix_matches = [
        prod
        for prod in production_files
        if _normalized_path(prod).endswith(suffix)
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return None


def _module_path_candidates(module_path: str) -> tuple[str, str]:
    return (
        f"{module_path}.py",
        f"{module_path}/__init__.py",
    )


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

    candidates = _module_path_candidates(module_path)
    for candidate in candidates:
        matched = _match_production_candidate(candidate, production_files)
        if matched:
            return matched
        # Try src/-prefixed variants for src-layout projects
        for prefix in _SRC_PREFIXES:
            prefixed = f"{prefix}{candidate}"
            matched = _match_production_candidate(prefixed, production_files)
            if matched:
                return matched
        if test_path:
            sibling = os.path.join(os.path.dirname(test_path), candidate)
            matched = _match_production_candidate(sibling, production_files)
            if matched:
                return matched
    return None


def _identity_alias_targets(content: str) -> list[str]:
    import_module_aliases = {
        match.group("name"): match.group("spec")
        for match in PY_IMPORT_MODULE_RE.finditer(content)
    }

    targets: list[str] = []
    for match in PY_SYS_MODULES_ALIAS_RE.finditer(content):
        spec = match.group("spec")
        if spec:
            targets.append(spec)
            continue
        alias_name = match.group("name")
        if alias_name and alias_name in import_module_aliases:
            targets.append(import_module_aliases[alias_name])
    return targets


def _local_module_path(filepath: str, imported_module: str) -> str:
    base = Path(filepath).parent
    for part in imported_module.split("."):
        base /= part
    return _normalized_path(str(base))


def _local_import_targets(content: str, filepath: str) -> list[str]:
    targets: list[str] = []
    for match in PY_LOCAL_IMPORT_RE.finditer(content):
        module_name = match.group("module")
        if module_name:
            targets.append(_local_module_path(filepath, module_name))
            continue

        raw_names = match.group("names") or ""
        for raw_name in raw_names.split(","):
            name = raw_name.strip()
            if not name or not _looks_reexported(content, name):
                continue
            targets.append(_local_module_path(filepath, name))
    return targets


def _looks_reexported(content: str, name: str) -> bool:
    return any(
        pattern in content
        for pattern in (
            f"{name}.__dict__",
            f"getattr({name},",
            f"dir({name})",
            f"{name}.__all__",
        )
    )


def _resolve_local_target(target: str, production_files: set[str]) -> str | None:
    for candidate in _module_path_candidates(target):
        matched = _match_production_candidate(candidate, production_files)
        if matched:
            return matched
    return None


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    """Resolve explicit Python identity aliases and package re-export modules."""
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return set()

    results: set[str] = set()
    for spec in _identity_alias_targets(content):
        resolved = resolve_import_spec(spec, filepath, production_files)
        if resolved:
            results.add(resolved)

    for target in _local_import_targets(content, filepath):
        resolved = _resolve_local_target(target, production_files)
        if resolved:
            results.add(resolved)
    return results


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
