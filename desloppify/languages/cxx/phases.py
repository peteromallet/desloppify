"""C/C++ detector phase runners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex

from desloppify.base.output.terminal import log
from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine._state.filtering import make_issue
from desloppify.languages._framework.base.shared_phases import (
    run_coupling_phase,
    run_structural_phase,
 )
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages._framework.generic_parts.parsers import PARSERS
from desloppify.languages._framework.generic_parts.tool_factories import _record_tool_failure_coverage
from desloppify.languages._framework.generic_parts.tool_runner import run_tool_result
from desloppify.languages.cxx._helpers import build_cxx_dep_graph
from desloppify.languages.cxx.extractors import CXX_HEADER_EXTENSIONS, find_cxx_files
from desloppify.state_io import Issue

CXX_COMPLEXITY_SIGNALS = [
    ComplexitySignal("includes", r"(?m)^\s*#include\s+", weight=1, threshold=20),
    ComplexitySignal("TODOs", r"(?m)//\s*(?:TODO|FIXME|HACK|XXX)", weight=2, threshold=0),
    ComplexitySignal(
        "types",
        r"(?m)^\s*(?:class|struct|enum)\s+[A-Za-z_]\w*",
        weight=2,
        threshold=6,
    ),
    ComplexitySignal("namespaces", r"(?m)^\s*namespace\s+[A-Za-z_]\w*", weight=1, threshold=4),
]


_CPPCHECK_BATCH_SIZE = 25
_CPPCHECK_SMELL_ID = "cppcheck_issue"
_CPPCHECK_CMD_PREFIX = (
    "cppcheck --template='{file}:{line}: {severity}: {message}' "
    "--enable=all --check-level=exhaustive --inline-suppr "
    "--language=c++ --std=c++17 --suppress=missingIncludeSystem --quiet"
)


def _cppcheck_file_args(files: list[str]) -> str:
    return " ".join(shlex.quote(filepath.replace('\\', '/')) for filepath in files)


def _cppcheck_include_args(files: list[str], extra_dirs: list[str] | None = None) -> str:
    include_dirs = sorted(
        {
            str(Path(filepath.replace('\\', '/')).parent)
            for filepath in files
            if Path(filepath).suffix in CXX_HEADER_EXTENSIONS
        }
    )
    if extra_dirs:
        include_dirs = sorted(set(include_dirs) | set(extra_dirs))
    return " ".join(shlex.quote(f"-I{include_dir}") for include_dir in include_dirs)


def _compile_db_include_dirs(scan_root: Path, files: list[str]) -> list[str]:
    """Return include dirs the project's own compile database records for scanned files.

    C++ projects routinely include headers that live outside the scanned tree
    (vendored or sibling-package sources).  compile_commands.json records the
    real -I paths the project's build uses, so harvesting them lets cppcheck
    resolve those headers instead of emitting missingInclude noise.
    """
    database = scan_root / "compile_commands.json"
    if not database.is_file():
        return []
    try:
        entries = json.loads(database.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []
    wanted = {Path(filepath.replace("\\", "/")).name for filepath in files}
    include_dirs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_file = str(entry.get("file", "")).replace("\\", "/")
        if Path(entry_file).name not in wanted:
            continue
        arguments = entry.get("arguments")
        if isinstance(arguments, list):
            tokens = [str(token) for token in arguments]
        else:
            tokens = shlex.split(str(entry.get("command", "")))
        for idx, token in enumerate(tokens):
            if token == "-I" and idx + 1 < len(tokens):
                include_dirs.add(tokens[idx + 1])
            elif token.startswith("-I") and len(token) > 2:
                include_dirs.add(token[2:])
    return sorted(include_dirs)


def _run_cppcheck_batch(scan_root: Path, files: list[str], include_args: str):
    return run_tool_result(
        f"{_CPPCHECK_CMD_PREFIX} {include_args} {_cppcheck_file_args(files)}",
        scan_root,
        PARSERS["gnu"],
    )


def _is_header_unused_diagnostic(entry: dict) -> bool:
    filepath = str(entry.get("file", ""))
    message = str(entry.get("message", ""))
    return Path(filepath).suffix in CXX_HEADER_EXTENSIONS and " is never used" in message


def _is_information_record(entry: dict) -> bool:
    """Classify cppcheck ``information`` records as non-actionable.

    The information category carries project-level notes (missing include
    paths, checker reports, normalization notices) rather than per-line
    source diagnostics, so they must not surface as findings.
    """
    return str(entry.get("message", "")).startswith("information: ")


def phase_cppcheck_issue(
    path: Path,
    lang: LangRuntimeContract,
 ) -> tuple[list[Issue], dict[str, int]]:
    """Run cppcheck in batches with per-file retry on timeout/error."""
    files = find_cxx_files(path)
    if not files:
        return [], {}

    include_args = _cppcheck_include_args(files, _compile_db_include_dirs(path, files))
    entries: list[dict] = []
    failure_result = None
    for idx in range(0, len(files), _CPPCHECK_BATCH_SIZE):
        batch = files[idx : idx + _CPPCHECK_BATCH_SIZE]
        batch_result = _run_cppcheck_batch(path, batch, include_args)
        if batch_result.status != "error" or len(batch) == 1:
            entries.extend(batch_result.entries)
            if batch_result.status == "error" and failure_result is None:
                failure_result = batch_result
            continue

        recovered = True
        for filepath in batch:
            single_result = _run_cppcheck_batch(path, [filepath], include_args)
            if single_result.status == "error":
                recovered = False
                if failure_result is None:
                    failure_result = single_result
                continue
            entries.extend(single_result.entries)
        if not recovered and failure_result is None:
            failure_result = batch_result

    if failure_result is not None:
        _record_tool_failure_coverage(
            lang,
            detector=_CPPCHECK_SMELL_ID,
            label="cppcheck",
            result=failure_result,
        )

    entries = [
        entry
        for entry in entries
        if not _is_header_unused_diagnostic(entry) and not _is_information_record(entry)
    ]
    if not entries:
        return [], {}

    issues = [
        make_issue(
            _CPPCHECK_SMELL_ID,
            entry["file"],
            f"{_CPPCHECK_SMELL_ID}::{entry['line']}::{hashlib.md5(entry['message'].encode('utf-8'), usedforsecurity=False).hexdigest()[:8]}",
            tier=2,
            confidence="medium",
            summary=entry["message"],
        )
        for entry in entries
    ]
    return issues, {_CPPCHECK_SMELL_ID: len(entries)}


def phase_structural(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Run structural analysis for C/C++ files."""
    return run_structural_phase(
        path,
        lang,
        complexity_signals=CXX_COMPLEXITY_SIGNALS,
        log_fn=log,
    )


def phase_coupling(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Run graph-backed coupling analysis for C/C++ files."""
    return run_coupling_phase(
        path,
        lang,
        build_dep_graph_fn=build_cxx_dep_graph,
        log_fn=log,
    )
