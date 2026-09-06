"""C/C++-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

from desloppify.base.text_utils import strip_c_style_comments

ASSERT_PATTERNS = [
    re.compile(r"\bASSERT_[A-Z_]+\b"),
    re.compile(r"\bEXPECT_[A-Z_]+\b"),
    re.compile(r"\b(?:STATIC_)?(?:REQUIRE|CHECK)(?:_[A-Z_]+)?\s*\("),
    re.compile(r"\b(?:SUCCEED|FAIL|FAIL_CHECK)\s*\("),
]
MOCK_PATTERNS = [re.compile(r"\bMOCK_METHOD\b"), re.compile(r"\bFakeIt\b")]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(
    r"\b(?:TEST(?:_F|_P)?|"
    r"(?:TEMPLATE_(?:PRODUCT_)?|TEMPLATE_LIST_)?TEST_CASE(?:_METHOD|_SIG)?|"
    r"SCENARIO(?:_METHOD)?)\s*\("
)
BARREL_BASENAMES: set[str] = set()
_INCLUDE_RE = re.compile(r'(?m)^\s*#include\s*[<"]([^>"]+)[>"]')
_SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx")
_HEADER_EXTENSIONS = (".h", ".hh", ".hpp")
_CMAKE_COMMENT_RE = re.compile(r"(?m)#.*$")
_CMAKE_COMMAND_RE = re.compile(
    r"\b(?:(?:qt6?_)?add_executable|(?:qt6?_)?add_library|target_sources)\s*\(",
    re.IGNORECASE,
)
_CMAKE_SOURCE_SPEC_RE = re.compile(
    r'"([^"\n]+\.(?:cpp|cxx|cc|c|hpp|hh|h))"|([^\s()"]+\.(?:cpp|cxx|cc|c|hpp|hh|h))',
    re.IGNORECASE,
)
_TYPE_DECLARATION_RE = re.compile(
    r"\b(?:class|struct|union|enum(?:\s+class)?)\s+([A-Za-z_]\w*)"
)
_CALLABLE_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_NON_SYMBOL_CALLABLES = frozenset(
    {
        "alignof",
        "catch",
        "decltype",
        "for",
        "if",
        "noexcept",
        "requires",
        "sizeof",
        "static_assert",
        "switch",
        "while",
    }
)
_TYPE_OR_NAMESPACE_RE = re.compile(r"\b(?:class|struct|enum|namespace)\b")
_FUNCTION_NAME_AT_END_RE = re.compile(
    r"(?:operator\s*[^\s]+|~?[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)$"
)
_NON_FUNCTION_PREFIXES = (
    "#",
    "case ",
    "co_return ",
    "for ",
    "if ",
    "return ",
    "static_assert ",
    "switch ",
    "throw ",
    "while ",
)


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True when a file looks like it contains runtime logic."""
    basename = os.path.basename(filepath)
    if filepath.endswith(("_test.c", "_test.cc", "_test.cpp", "_test.cxx")):
        return False
    if basename.startswith("test_") and basename.endswith(_SOURCE_EXTENSIONS):
        return False
    if _TYPE_OR_NAMESPACE_RE.search(content):
        return True
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if "(" not in line or line.startswith(_NON_FUNCTION_PREFIXES):
            continue
        prefix = line.partition("(")[0].rstrip()
        if _FUNCTION_NAME_AT_END_RE.search(prefix) and (
            "::" in prefix or any(character.isspace() for character in prefix)
        ):
            return True
    return False


def _match_candidate(candidate: Path, production_files: set[str]) -> str | None:
    absolute = os.path.abspath(candidate)
    if absolute in production_files:
        return absolute

    normalized_candidate = os.path.normcase(absolute)
    matches = [
        production
        for production in production_files
        if os.path.normcase(os.path.abspath(production)) == normalized_candidate
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _unique_suffix_match(spec: str, production_files: set[str]) -> str | None:
    normalized_spec = spec.replace("\\", "/").lstrip("./")
    matches = [
        production
        for production in production_files
        if production.replace("\\", "/") == normalized_spec
        or production.replace("\\", "/").endswith(f"/{normalized_spec}")
    ]
    return matches[0] if len(matches) == 1 else None


@cache
def _declared_header_symbols(header_path: str) -> frozenset[str]:
    try:
        header = strip_c_style_comments(Path(header_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return frozenset()

    symbols = set(_TYPE_DECLARATION_RE.findall(header))
    symbols.update(_CALLABLE_IDENTIFIER_RE.findall(header))
    return frozenset(symbols - _NON_SYMBOL_CALLABLES)


@cache
def _test_body_identifiers(test_path: str) -> frozenset[str]:
    try:
        test = strip_c_style_comments(Path(test_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return frozenset()
    return frozenset(_IDENTIFIER_RE.findall(_INCLUDE_RE.sub("", test)))


def _test_references_declared_symbol(header_path: str, test_path: str) -> bool:
    return bool(
        _declared_header_symbols(header_path) & _test_body_identifiers(test_path)
    )


def _unique_source_companion(
    header_path: str,
    test_path: str,
    production_files: set[str],
) -> str | None:
    header = Path(header_path)
    if header.suffix.lower() not in _HEADER_EXTENSIONS:
        return None
    if not _test_references_declared_symbol(header_path, test_path):
        return None
    matches = [
        production
        for production in production_files
        if Path(production).suffix.lower() in _SOURCE_EXTENSIONS
        and Path(production).stem == header.stem
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_import_spec(
    spec: str,
    test_path: str,
    production_files: set[str],
) -> str | None:
    """Resolve include-like specs used in C/C++ tests."""
    cleaned = (spec or "").strip().strip("\"'")
    if not cleaned:
        return None

    test_file = Path(os.path.abspath(test_path))
    candidate = test_file.parent / cleaned
    matched = _match_candidate(candidate, production_files)
    if matched:
        return _unique_source_companion(matched, test_path, production_files) or matched

    matched = _unique_suffix_match(cleaned, production_files)
    if matched:
        return _unique_source_companion(matched, test_path, production_files) or matched
    return None


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    """C/C++ has no barrel-file re-export expansion."""
    del filepath, production_files
    return set()


def _unique_preserving_order(specs: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in specs:
        cleaned = (spec or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _parse_cmake_source_specs(content: str) -> list[str]:
    if not _CMAKE_COMMAND_RE.search(content):
        return []
    stripped = _CMAKE_COMMENT_RE.sub("", content)
    specs: list[str] = []
    for quoted, bare in _CMAKE_SOURCE_SPEC_RE.findall(stripped):
        spec = quoted or bare
        if spec:
            specs.append(spec)
    return _unique_preserving_order(specs)


def parse_test_import_specs(content: str) -> list[str]:
    """Return include-like specs from test content and test build files."""
    include_specs = [match.group(1).strip() for match in _INCLUDE_RE.finditer(content)]
    cmake_specs = _parse_cmake_source_specs(content)
    return _unique_preserving_order(include_specs + cmake_specs)


def _iter_test_tree_ancestors(test_file: Path) -> list[Path]:
    ancestors = [test_file.parent, *test_file.parents]
    stop_at: int | None = None
    for index, ancestor in enumerate(ancestors):
        if ancestor.name.lower() in {"tests", "test"}:
            stop_at = index
            break
    if stop_at is None:
        return []
    return ancestors[: stop_at + 1]


def discover_test_mapping_files(
    test_files: set[str], production_files: set[str]
) -> set[str]:
    """Find CMake/Make build files that define test target sources within test trees."""
    del production_files
    discovered: set[str] = set()
    for test_path in sorted(test_files):
        test_file = Path(test_path).resolve()
        for ancestor in _iter_test_tree_ancestors(test_file):
            for build_file in ("CMakeLists.txt", "Makefile"):
                candidate = ancestor / build_file
                if candidate.is_file():
                    discovered.add(str(candidate.resolve()))
    return discovered


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map a C/C++ test file to its likely source counterpart."""
    basename = os.path.basename(test_path)
    src_name = strip_test_markers(basename)
    if not src_name:
        return None

    test_file = Path(test_path).resolve()
    candidates = [
        test_file.with_name(src_name),
        test_file.parent.parent / src_name,
        test_file.parent.parent / "src" / src_name,
        test_file.parent.parent / "source" / src_name,
        test_file.parent.parent / "lib" / src_name,
    ]
    for candidate in candidates:
        matched = _match_candidate(candidate, production_set)
        if matched:
            return matched

    for production in production_set:
        if Path(production).name == src_name and not re.search(
            r"(?:^|[\\/])tests?(?:[\\/]|$)", production
        ):
            return production
    return None


def strip_test_markers(basename: str) -> str | None:
    """Strip common C/C++ test-name markers to derive source basename."""
    stem, ext = os.path.splitext(basename)
    if ext.lower() not in _SOURCE_EXTENSIONS:
        return None
    if stem.endswith("_test"):
        return f"{stem[:-5]}{ext}"
    if stem.startswith("test_"):
        return f"{stem[5:]}{ext}"
    if stem.endswith("Tests"):
        return f"{stem[:-5]}{ext}"
    if stem.endswith("Test"):
        return f"{stem[:-4]}{ext}"
    return None


def strip_comments(content: str) -> str:
    """Strip C-style comments while preserving string literals."""
    return strip_c_style_comments(content)
