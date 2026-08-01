"""Heavy runtime helpers for Python regex/AST smell scanning."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root
from desloppify.base.discovery.source import find_py_files
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.languages.python.detectors.smells_ast._dispatch import (
    detect_ast_smells,
)
from desloppify.languages.python.detectors.smells_ast._source_detectors import (
    _resolve_import_target,
    collect_module_constants,
    detect_duplicate_constants,
    detect_star_import_no_all,
    detect_vestigial_parameter,
)

CallableDefaultProvider = tuple[str, str]
LoadedSmellSource = tuple[str, str, list[str]]


def build_string_line_set(lines: list[str]) -> set[int]:
    """Build 0-indexed line numbers that are inside multi-line strings."""
    in_multiline: str | None = None
    string_lines: set[int] = set()

    for i, line in enumerate(lines):
        if in_multiline is not None:
            string_lines.add(i)
            if in_multiline in line:
                pos = 0
                while pos < len(line):
                    idx = line.find(in_multiline, pos)
                    if idx == -1:
                        break
                    backslashes = 0
                    j = idx - 1
                    while j >= 0 and line[j] == "\\":
                        backslashes += 1
                        j -= 1
                    if backslashes % 2 == 0:
                        in_multiline = None
                        break
                    pos = idx + 3
            continue

        pos = 0
        while pos < len(line):
            ch = line[pos]
            if ch == "#":
                break
            if ch in ("r", "b", "f", "u", "R", "B", "F", "U") and pos + 1 < len(line):
                next_ch = line[pos + 1]
                if next_ch in ('"', "'"):
                    pos += 1
                    ch = next_ch
                elif (
                    next_ch in ("r", "b", "f", "R", "B", "F")
                    and pos + 2 < len(line)
                    and line[pos + 2] in ('"', "'")
                ):
                    pos += 2
                    ch = line[pos]
            if ch in ('"', "'"):
                triple = line[pos : pos + 3]
                if triple in ('"""', "'''"):
                    close_idx = line.find(triple, pos + 3)
                    if close_idx == -1:
                        in_multiline = triple
                        break
                    pos = close_idx + 3
                    continue
                end = line.find(ch, pos + 1)
                while end != -1 and end > 0 and line[end - 1] == "\\":
                    end = line.find(ch, end + 1)
                pos = (end + 1) if end != -1 else len(line)
                continue
            pos += 1

    return string_lines


def match_is_in_string(line: str, match_start: int) -> bool:
    """Return True when a regex match location is inside a string/comment."""
    i = 0
    in_string = None
    while i < len(line):
        if i == match_start:
            return in_string is not None
        ch = line[i]
        if in_string is None:
            if ch == "#":
                return True
            triple = line[i : i + 3]
            if triple in ('"""', "'''"):
                in_string = triple
                i += 3
                continue
            if (
                ch in ("r", "b", "f")
                and i + 1 < len(line)
                and line[i + 1] in ('"', "'")
            ):
                i += 1
                ch = line[i]
            if ch in ('"', "'"):
                in_string = ch
                i += 1
                continue
        else:
            if ch == "\\" and i + 1 < len(line):
                i += 2
                continue
            if in_string in ('"""', "'''"):
                if line[i : i + 3] == in_string:
                    in_string = None
                    i += 3
                    continue
            elif ch == in_string:
                in_string = None
                i += 1
                continue
        i += 1
    return in_string is not None


def _walk_except_blocks(lines: list[str]):
    """Yield ``(line_index, except_clause, body_lines)`` for except blocks."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r"except\s*(?:\w|\(|:)", stripped) and stripped != "except:":
            continue
        if not stripped.endswith(":"):
            continue
        indent = len(line) - len(line.lstrip())
        j = i + 1
        body_lines = []
        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()
            if next_stripped == "":
                j += 1
                continue
            if len(next_line) - len(next_line.lstrip()) <= indent:
                break
            body_lines.append(next_stripped)
            j += 1
        yield i, stripped, body_lines


def _is_broad_except(stripped: str) -> bool:
    """Check if except clause catches broadly (bare, Exception, BaseException)."""
    if stripped == "except:":
        return True
    match = re.match(r"except\s+(\w+)", stripped)
    return bool(match and match.group(1) in ("Exception", "BaseException"))


def _detect_empty_except(filepath: str, lines: list[str], smell_counts: dict[str, list]) -> None:
    """Find broad except blocks that just pass or have empty body."""
    for i, stripped, body_lines in _walk_except_blocks(lines):
        if (not body_lines or body_lines == ["pass"]) and _is_broad_except(stripped):
            smell_counts["empty_except"].append(
                {
                    "file": filepath,
                    "line": i + 1,
                    "content": stripped[:100],
                }
            )


def _detect_swallowed_errors(
    filepath: str,
    lines: list[str],
    smell_counts: dict[str, list],
) -> None:
    """Find except blocks that only print/log the error."""
    log_re = r"(?:print|logging\.\w+|logger\.\w+|log\.\w+)\s*\("
    for i, stripped, body_lines in _walk_except_blocks(lines):
        if body_lines and all(re.match(log_re, statement) for statement in body_lines):
            smell_counts["swallowed_error"].append(
                {
                    "file": filepath,
                    "line": i + 1,
                    "content": stripped[:100],
                }
            )


def _read_smell_source_file(
    filepath: str,
    *,
    logger,
) -> tuple[str, list[str]] | None:
    """Load one source file for smell detection."""
    try:
        file_path = (
            Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
        )
        content = file_path.read_text()
        return content, content.splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        log_best_effort_failure(
            logger,
            f"read Python file for smell scan {filepath}",
            exc,
        )
        return None


def _resolve_smell_source_path(filepath: str) -> Path:
    """Resolve a smell-scanner filepath against the active project root."""
    source_path = Path(filepath)
    if source_path.is_absolute():
        return source_path.resolve()
    return (get_project_root() / source_path).resolve()


def _is_dataclass_decorator(decorator: ast.expr) -> bool:
    """Return whether a decorator invokes or refers to ``dataclass``."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (isinstance(target, ast.Name) and target.id == "dataclass") or (
        isinstance(target, ast.Attribute) and target.attr == "dataclass"
    )


def _is_callable_annotation(annotation: ast.expr) -> bool:
    """Return whether an annotation directly names ``Callable``."""
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return (isinstance(target, ast.Name) and target.id == "Callable") or (
        isinstance(target, ast.Attribute) and target.attr == "Callable"
    )


def _top_level_function_names(tree: ast.Module) -> set[str]:
    """Return function names that can be directly imported from a module."""
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _imported_callable_provider_bindings(
    tree: ast.Module,
    *,
    source_path: Path,
    scan_root: Path,
    source_filepaths: dict[Path, str],
    function_names_by_file: dict[str, set[str]],
) -> dict[str, CallableDefaultProvider]:
    """Map direct local-project function imports to their defining files."""
    bindings: dict[str, CallableDefaultProvider] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        target = _resolve_import_target(
            node.module or "",
            node.level,
            source_path.parent,
            scan_root,
        )
        if target is None:
            continue
        target_filepath = source_filepaths.get(target.resolve())
        if target_filepath is None:
            continue
        target_function_names = function_names_by_file[target_filepath]
        for alias in node.names:
            if alias.name == "*" or alias.name not in target_function_names:
                continue
            bindings[alias.asname or alias.name] = (target_filepath, alias.name)
    return bindings


def _collect_callable_default_return_none_providers(
    loaded_files: list[LoadedSmellSource],
    project_path: Path,
) -> frozenset[CallableDefaultProvider]:
    """Find exact provider functions used as typed dataclass callable defaults.

    This deliberately recognizes only direct ``Name`` defaults on top-level
    dataclasses and resolvable local-project imports.  It is evidence of a
    provider contract, not a general exemption for exports or imports.
    """
    parsed_files: dict[str, ast.Module] = {}
    source_filepaths: dict[Path, str] = {}
    for filepath, content, _lines in loaded_files:
        try:
            parsed_files[filepath] = ast.parse(content, filename=filepath)
        except SyntaxError:
            continue
        source_filepaths[_resolve_smell_source_path(filepath)] = filepath

    function_names_by_file = {
        filepath: _top_level_function_names(tree)
        for filepath, tree in parsed_files.items()
    }
    scan_root = _resolve_smell_source_path(str(project_path))
    imported_bindings_by_file = {
        filepath: _imported_callable_provider_bindings(
            tree,
            source_path=_resolve_smell_source_path(filepath),
            scan_root=scan_root,
            source_filepaths=source_filepaths,
            function_names_by_file=function_names_by_file,
        )
        for filepath, tree in parsed_files.items()
    }

    providers: set[CallableDefaultProvider] = set()
    for filepath, tree in parsed_files.items():
        local_function_names = function_names_by_file[filepath]
        imported_bindings = imported_bindings_by_file[filepath]
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef) or not any(
                _is_dataclass_decorator(decorator)
                for decorator in class_node.decorator_list
            ):
                continue
            for field in class_node.body:
                if not (
                    isinstance(field, ast.AnnAssign)
                    and isinstance(field.value, ast.Name)
                    and _is_callable_annotation(field.annotation)
                ):
                    continue
                provider_name = field.value.id
                if provider_name in imported_bindings:
                    providers.add(imported_bindings[provider_name])
                elif provider_name in local_function_names:
                    providers.add((filepath, provider_name))
    return frozenset(providers)


def _scan_file_patterns(
    *,
    filepath: str,
    lines: list[str],
    smell_checks: list[dict],
    smell_counts: dict[str, list[dict]],
) -> None:
    """Run regex-based smell checks for one file."""
    multiline_string_lines = build_string_line_set(lines)
    for check in smell_checks:
        pattern = check.get("pattern")
        if pattern is None:
            continue
        for i, line in enumerate(lines):
            if i in multiline_string_lines:
                continue
            match = re.search(pattern, line)
            if not match or match_is_in_string(line, match.start()):
                continue
            if check["id"] == "hardcoded_url" and re.match(
                r"^[A-Z_][A-Z0-9_]*\s*=",
                line.strip(),
            ):
                continue
            smell_counts[check["id"]].append(
                {
                    "file": filepath,
                    "line": i + 1,
                    "content": line.strip()[:100],
                }
            )


def _run_semantic_detectors(
    *,
    filepath: str,
    content: str,
    lines: list[str],
    project_path: Path,
    smell_counts: dict[str, list[dict]],
    constants_by_key: dict[tuple[str, str], list[tuple[str, int]]],
    return_none_callable_default_providers: frozenset[CallableDefaultProvider],
) -> None:
    """Run semantic smell detectors for one file."""
    _detect_empty_except(filepath, lines, smell_counts)
    _detect_swallowed_errors(filepath, lines, smell_counts)
    detect_ast_smells(
        filepath,
        content,
        smell_counts,
        return_none_callable_default_providers=return_none_callable_default_providers,
    )
    detect_star_import_no_all(filepath, content, project_path, smell_counts)
    detect_vestigial_parameter(filepath, content, lines, smell_counts)
    collect_module_constants(filepath, content, constants_by_key)


def _build_sorted_entries(
    *,
    smell_checks: list[dict],
    smell_counts: dict[str, list[dict]],
) -> list[dict]:
    """Build sorted smell output entries from aggregate counts."""
    severity_order = {"high": 0, "medium": 1, "low": 2}
    entries: list[dict] = []
    for check in smell_checks:
        matches = smell_counts[check["id"]]
        if not matches:
            continue
        entries.append(
            {
                "id": check["id"],
                "label": check["label"],
                "severity": check["severity"],
                "count": len(matches),
                "files": len(set(match["file"] for match in matches)),
                "matches": matches[:50],
            }
        )
    entries.sort(
        key=lambda entry: (severity_order.get(entry["severity"], 9), -entry["count"])
    )
    return entries


def detect_smells_runtime(
    path: Path,
    *,
    smell_checks: list[dict],
    is_test_path_fn,
    logger,
) -> tuple[list[dict], int]:
    """Detect Python code smell patterns. Returns (entries, total_files_checked)."""
    smell_counts: dict[str, list[dict]] = {smell["id"]: [] for smell in smell_checks}
    files = find_py_files(path)
    constants_by_key: dict[tuple[str, str], list[tuple[str, int]]] = {}

    loaded_files: list[LoadedSmellSource] = []
    for filepath in files:
        if is_test_path_fn(filepath):
            continue
        loaded = _read_smell_source_file(filepath, logger=logger)
        if loaded is None:
            continue
        content, lines = loaded
        loaded_files.append((filepath, content, lines))

    return_none_callable_default_providers = (
        _collect_callable_default_return_none_providers(loaded_files, path)
    )
    for filepath, content, lines in loaded_files:
        _scan_file_patterns(
            filepath=filepath,
            lines=lines,
            smell_checks=smell_checks,
            smell_counts=smell_counts,
        )
        _run_semantic_detectors(
            filepath=filepath,
            content=content,
            lines=lines,
            project_path=path,
            smell_counts=smell_counts,
            constants_by_key=constants_by_key,
            return_none_callable_default_providers=(
                return_none_callable_default_providers
            ),
        )

    detect_duplicate_constants(constants_by_key, smell_counts)
    entries = _build_sorted_entries(
        smell_checks=smell_checks,
        smell_counts=smell_counts,
    )
    return entries, len(files)


__all__ = ["detect_smells_runtime"]
