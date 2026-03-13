"""C/C++-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re
from pathlib import Path

from desloppify.base.text_utils import strip_c_style_comments

ASSERT_PATTERNS = [re.compile(r"\bASSERT_[A-Z_]+\b"), re.compile(r"\bEXPECT_[A-Z_]+\b")]
MOCK_PATTERNS = [re.compile(r"\bMOCK_METHOD\b"), re.compile(r"\bFakeIt\b")]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"\bTEST(?:_F|_P)?\s*\(")
BARREL_BASENAMES: set[str] = set()
_INCLUDE_RE = re.compile(r'(?m)^\s*#include\s*[<"]([^>"]+)[>"]')
_SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx")
_HEADER_EXTENSIONS = (".h", ".hh", ".hpp")
_CMAKE_COMMENT_RE = re.compile(r"(?m)#.*$")
_CMAKE_COMMAND_RE = re.compile(r"\b(?:add_executable|add_library|target_sources)\s*\(", re.IGNORECASE)
_CMAKE_SOURCE_SPEC_RE = re.compile(
    r'"([^"\n]+\.(?:cpp|cxx|cc|c|hpp|hh|h))"|([^\s()"]+\.(?:cpp|cxx|cc|c|hpp|hh|h))',
    re.IGNORECASE,
)
_TESTABLE_LOGIC_RE = re.compile(
    r"\b(?:class|struct|enum|namespace)\b|^\s*(?:inline\s+|static\s+)?[A-Za-z_]\w*(?:[\s*&:<>]+[A-Za-z_]\w*)*\s+\w+\s*\(",
    re.MULTILINE,
)


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True when a file looks like it contains runtime logic."""
    basename = os.path.basename(filepath)
    if filepath.endswith(("_test.c", "_test.cc", "_test.cpp", "_test.cxx")):
        return False
    if basename.startswith("test_") and basename.endswith(_SOURCE_EXTENSIONS):
        return False
    return bool(_TESTABLE_LOGIC_RE.search(content))



def _match_candidate(candidate: Path, production_files: set[str]) -> str | None:
    resolved = str(candidate.resolve())
    normalized = {str(Path(path).resolve()): path for path in production_files}
    if resolved in normalized:
        return normalized[resolved]
    return None



def resolve_import_spec(
    spec: str,
    test_path: str,
    production_files: set[str],
) -> str | None:
    """Resolve include-like specs used in C/C++ tests."""
    cleaned = (spec or "").strip().strip("\"'")
    if not cleaned:
        return None

    test_file = Path(test_path).resolve()
    candidates: list[Path] = []
    if cleaned.startswith("./") or cleaned.startswith("../"):
        candidates.append((test_file.parent / cleaned).resolve())
    else:
        candidates.append((test_file.parent / cleaned).resolve())
        leaf = Path(cleaned).name
        for production in production_files:
            if Path(production).name == leaf:
                return production

    for candidate in candidates:
        matched = _match_candidate(candidate, production_files)
        if matched:
            return matched
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



def discover_test_mapping_files(test_files: set[str], production_files: set[str]) -> set[str]:
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
        if Path(production).name == src_name and not re.search(r"(?:^|[\\/])tests?(?:[\\/]|$)", production):
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
