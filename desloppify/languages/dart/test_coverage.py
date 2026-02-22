"""Dart-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re
from pathlib import Path

from desloppify.languages.dart.pubspec import read_package_name
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.utils import strip_c_style_comments

_DART_LOGIC_RE = re.compile(
    r"(?m)^\s*(?:class|enum|mixin|extension|typedef)\s+\w+|"
    r"^\s*(?:[A-Za-z_]\w*(?:<[^>{}]+>)?\??\s+)?[A-Za-z_]\w*\s*\([^)]*\)\s*(?:async\s*)?(?:\{|=>)"
)
_DART_IMPORT_RE = re.compile(r"""(?m)^\s*import\s+['"]([^'"]+)['"]""")
_DART_EXPORT_RE = re.compile(r"""(?m)^\s*export\s+['"]([^'"]+)['"]""")

ASSERT_PATTERNS = [re.compile(p) for p in [r"\bexpect\(", r"\bexpectLater\("]]
MOCK_PATTERNS = [
    re.compile(p)
    for p in [r"\bwhen\(", r"\bmocktail\.", r"\bmockito\.", r"\bMock[A-Za-z_]\w*\("]
]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"""(?:test|testWidgets)\s*\(\s*['"]""")
BARREL_BASENAMES: set[str] = {"index.dart"}


def _find_pubspec_root(path: Path) -> Path:
    cursor = path if path.is_dir() else path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pubspec.yaml").is_file():
            return candidate
    return PROJECT_ROOT


def _candidate_matches(candidate: Path, production_files: set[str]) -> str | None:
    probes = [candidate]
    if not candidate.suffix:
        probes.append(candidate.with_suffix(".dart"))
    for probe in probes:
        probe_str = str(probe)
        if probe_str in production_files:
            return probe_str
        try:
            rel_probe = str(probe.relative_to(PROJECT_ROOT))
        except ValueError:
            rel_probe = None
        if rel_probe and rel_probe in production_files:
            return rel_probe
    return None


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True if Dart file has runtime logic worth testing."""
    if filepath.endswith((".g.dart", ".freezed.dart", ".mocks.dart")):
        return False
    return bool(_DART_LOGIC_RE.search(content))


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Resolve Dart test imports to production files."""
    cleaned = (spec or "").strip()
    if not cleaned or cleaned.startswith("dart:"):
        return None

    project_root = _find_pubspec_root(Path(test_path))
    package_name = read_package_name(project_root)
    candidates: list[Path] = []

    if cleaned.startswith("package:"):
        package_ref = cleaned[len("package:") :]
        if "/" in package_ref:
            package, rel_path = package_ref.split("/", 1)
            if package_name and package == package_name:
                candidates.append((project_root / "lib" / rel_path).resolve())
    elif cleaned.startswith("./") or cleaned.startswith("../"):
        candidates.append((Path(test_path).parent / cleaned).resolve())
    elif cleaned.startswith("/"):
        candidates.append((project_root / cleaned.lstrip("/")).resolve())
    else:
        candidates.append((project_root / "lib" / cleaned).resolve())

    for candidate in candidates:
        matched = _candidate_matches(candidate, production_files)
        if matched:
            return matched
    return None


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    """Resolve exported modules from Dart barrel files."""
    try:
        content = Path(filepath).read_text(errors="replace")
    except OSError:
        return set()
    out: set[str] = set()
    for match in _DART_EXPORT_RE.finditer(content):
        resolved = resolve_import_spec(match.group(1), filepath, production_files)
        if resolved:
            out.add(resolved)
    return out


def parse_test_import_specs(content: str) -> list[str]:
    """Extract import specs from Dart test content."""
    return [match.group(1) for match in _DART_IMPORT_RE.finditer(content)]


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map Dart *_test.dart file to its source counterpart."""
    basename = os.path.basename(test_path)
    if not basename.endswith("_test.dart"):
        return None

    src_name = f"{basename[:-10]}.dart"
    test_file = Path(test_path).resolve()
    dirname = test_file.parent
    candidates: list[Path] = [dirname / src_name]

    for marker in ("test", "integration_test"):
        parts = test_file.parts
        if marker not in parts:
            continue
        idx = parts.index(marker)
        project_root = Path(*parts[:idx]) if idx > 0 else Path("/")
        rel_tail = Path(*parts[idx + 1 : -1]) if idx + 1 < len(parts) - 1 else Path()
        candidates.append(project_root / "lib" / rel_tail / src_name)

    for candidate in candidates:
        matched = _candidate_matches(candidate, production_set)
        if matched:
            return matched
    return None


def strip_test_markers(basename: str) -> str | None:
    """Strip Dart test marker suffix."""
    if basename.endswith("_test.dart"):
        return f"{basename[:-10]}.dart"
    return None


def strip_comments(content: str) -> str:
    """Strip Dart comments while preserving strings."""
    return strip_c_style_comments(content)
