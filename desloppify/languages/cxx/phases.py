"""C/C++ detector phase runners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import tempfile

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
from desloppify.languages._framework.generic_parts.tool_runner import ToolRunResult, run_tool_result
from desloppify.languages.cxx._helpers import build_cxx_dep_graph
from desloppify.languages.cxx.extractors import find_cxx_files
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
_CPPCHECK_CMD_PREFIX = "cppcheck --template='{file}:{line}: {severity}: {id}: {message}' --enable=all --quiet"


def _cppcheck_file_args(files: list[str]) -> str:
    return " ".join(shlex.quote(filepath.replace('\\', '/')) for filepath in files)


def _run_cppcheck_batch(scan_root: Path, files: list[str]):
    return run_tool_result(
        f"{_CPPCHECK_CMD_PREFIX} --language={'c' if all(Path(f).suffix.lower() == '.c' for f in files) else 'c++'} {_cppcheck_file_args(files)}",
        scan_root,
        PARSERS["gnu"],
    )


def _is_unused_function(entry: dict) -> bool:
    fields = entry["message"].split(": ", 2)
    return len(fields) == 3 and fields[1] == "unusedFunction"


def _run_cppcheck_whole_program(scan_root: Path, files: list[str]):
    # A compilation database keeps each file's dialect, including C++ headers,
    # while collecting calls across every batch and per-file retry.
    try:
        with tempfile.TemporaryDirectory(prefix="desloppify-cppcheck-") as temporary:
            database = Path(temporary) / "compile_commands.json"
            database.write_text(json.dumps([
                {"directory": str(scan_root.resolve()), "file": str((scan_root / file).resolve()),
                 "arguments": ["cc", "-x", "c" if Path(file).suffix.lower() == ".c" else "c++",
                               "-c", str((scan_root / file).resolve())]}
                for file in files
            ]), encoding="utf-8")
            return run_tool_result(
                "cppcheck --template='{file}:{line}: {severity}: {id}: {message}' "
                f"--enable=unusedFunction,information --quiet --project={shlex.quote(str(database))}",
                scan_root, PARSERS["gnu"],
            )
    except OSError as error:
        return ToolRunResult(entries=[], status="error", error_kind="tool_io_error", message=str(error))


def phase_cppcheck_issue(
    path: Path,
    lang: LangRuntimeContract,
 ) -> tuple[list[Issue], dict[str, int]]:
    """Run cppcheck in batches with per-file retry on timeout/error."""
    files = find_cxx_files(path)
    if not files:
        return [], {}

    entries: list[dict] = []
    failure_result = None
    # Headers default to C in cppcheck unless the language is specified. In a C/C++ scan, treat header-only
    # analysis as C++ and keep actual C translation units separate so C identifiers are not parsed as C++ keywords.
    c_files = [file for file in files if Path(file).suffix.lower() == ".c"]
    cxx_files = [file for file in files if Path(file).suffix.lower() != ".c"]
    batches = [group[idx : idx + _CPPCHECK_BATCH_SIZE] for group in (c_files, cxx_files)
               for idx in range(0, len(group), _CPPCHECK_BATCH_SIZE)]
    for batch in batches:
        batch_result = _run_cppcheck_batch(path, batch)
        if batch_result.status != "error" or len(batch) == 1:
            entries.extend(batch_result.entries)
            if batch_result.status == "error" and failure_result is None:
                failure_result = batch_result
            continue

        recovered = True
        for filepath in batch:
            single_result = _run_cppcheck_batch(path, [filepath])
            if single_result.status == "error":
                recovered = False
                if failure_result is None:
                    failure_result = single_result
                continue
            entries.extend(single_result.entries)
        if not recovered and failure_result is None:
            failure_result = batch_result

    if any(_is_unused_function(entry) for entry in entries):
        # Batch-local unused claims are unproven. Only a complete-project pass
        # can establish that no other translation unit calls the function.
        entries = [entry for entry in entries if not _is_unused_function(entry)]
        whole = _run_cppcheck_whole_program(path, files)
        configuration_ids = {"missingInclude", "missingIncludeSystem", "syntaxError", "unknownMacro", "preprocessorErrorDirective"}
        incomplete = any(
            len(fields := entry["message"].split(": ", 2)) == 3 and fields[1] in configuration_ids
            for entry in whole.entries
        )
        if whole.status == "error" or incomplete:
            if failure_result is None:
                failure_result = whole if whole.status == "error" else ToolRunResult(
                    entries=[], status="error", error_kind="tool_configuration",
                    message="Whole-program unused-function analysis has configuration/parser notices",
                )
        else:
            entries.extend(entry for entry in whole.entries if _is_unused_function(entry))

    if failure_result is not None:
        _record_tool_failure_coverage(
            lang,
            detector=_CPPCHECK_SMELL_ID,
            label="cppcheck",
            result=failure_result,
        )

    # Analysis notices describe missing configuration or parser limitations, not defects in the scanned code.
    # Preserve the actual diagnostic IDs so this classification does not depend on project-specific wording.
    configuration_ids = {"missingInclude", "missingIncludeSystem", "syntaxError", "unknownMacro", "preprocessorErrorDirective"}
    actionable = []
    analysis_notices = []
    for entry in entries:
        fields = entry["message"].split(": ", 2)
        if fields[0] == "information" or (len(fields) == 3 and fields[1] in configuration_ids):
            analysis_notices.append(entry)
        else:
            actionable.append(entry)
    if analysis_notices:
        _record_tool_failure_coverage(
            lang,
            detector=_CPPCHECK_SMELL_ID,
            label="cppcheck",
            result=ToolRunResult(entries=[], status="error", error_kind="tool_configuration",
                                 message=f"{len(analysis_notices)} analysis configuration/parser notices"),
        )
        for record in [getattr(lang, "detector_coverage", {}).get(_CPPCHECK_SMELL_ID),
                       *getattr(lang, "coverage_warnings", [])]:
            if isinstance(record, dict) and record.get("detector") == _CPPCHECK_SMELL_ID and record.get("reason") == "tool_configuration":
                record["summary"] = "cppcheck analysis reduced by configuration/parser notices"
                record["remediation"] = "Supply the correct build configuration and rerun cppcheck."
        log(f"  cppcheck: {len(analysis_notices)} configuration/parser notices; analysis coverage is reduced.")
    entries = actionable
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
