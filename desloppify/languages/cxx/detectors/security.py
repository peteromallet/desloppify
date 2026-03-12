"""C/C++ security detection with clang-tidy/cppcheck normalization."""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from desloppify.base.discovery.file_paths import rel
from desloppify.engine.detectors.security import rules as security_detector_mod
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages._framework.base.types import (
    DetectorCoverageStatus,
    LangSecurityResult,
)
from desloppify.languages._framework.generic_parts.tool_runner import (
    ToolRunResult,
    run_tool_result,
)

logger = logging.getLogger(__name__)

_SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx"})
_HEADER_SUFFIXES = frozenset({".h", ".hpp"})
_CXX_SUFFIXES = _SOURCE_SUFFIXES | _HEADER_SUFFIXES
_UNSAFE_C_STRING_APIS = ("strcpy", "strcat", "sprintf", "vsprintf", "gets", "scanf", "sscanf", "fscanf")
_PROJECT_MARKERS = ("compile_commands.json", "CMakeLists.txt", "Makefile")
_TOOL_PRIORITY = {"clang-tidy": 0, "cppcheck": 1, "regex": 2}
_CLANG_TIDY_BATCH_SIZE = 10
_CPPCHECK_BATCH_SIZE = 25

_COMMAND_INJECTION_RE = re.compile(r"\b(?:std::)?system\s*\(")
_UNSAFE_C_STRING_RE = re.compile(
    r"\b(?:strcpy|strcat|sprintf|vsprintf|gets|scanf|sscanf|fscanf)\s*\("
)
_INSECURE_RANDOM_RE = re.compile(
    r"\b(?:std::)?rand\s*\([^)]*\).*(?:token|password|secret|key|nonce|salt|otp)",
    re.IGNORECASE,
)
_WEAK_HASH_RE = re.compile(r"\b(?:MD5|SHA1)\b", re.IGNORECASE)

_CLANG_TIDY_RE = re.compile(
    r"^(.+?):(\d+):(?:(\d+):)?\s*(warning|error|note):\s*(.+?)(?:\s+\[([^\]]+)\])?\s*$"
)
_CPPCHECK_RE = re.compile(r"^(.+?):(\d+):([^:]+):([^:]+):(.+)$")

_TOOL_IMPACT_TEXT = (
    "C/C++-specific security coverage is reduced; regex fallback can miss findings "
    "that depend on compile flags, include paths, or AST-level semantics."
)
_REMEDIATIONS = {
    "command_injection": "Avoid system(); use explicit process APIs with validated arguments.",
    "unsafe_c_string": (
        "Use bounded APIs or std::string/std::array with explicit size checks."
    ),
    "insecure_random": "Use a cryptographic RNG instead of rand() for secrets or tokens.",
    "weak_crypto_hash": (
        "Use a modern hash or password-hashing algorithm appropriate to the use case."
    ),
}


ToolState = Literal[
    "ok",
    "empty",
    "missing_tool",
    "timeout",
    "error",
    "parse_error",
]


@dataclass(frozen=True)
class CxxToolScanResult:
    """Normalized execution result for one C/C++ security tool."""

    tool: str
    state: ToolState
    entries: list[dict]
    detail: str = ""
    covered_files: tuple[str, ...] = ()

    def is_success(self) -> bool:
        return self.state in {"ok", "empty"}


def _make_security_entry(
    filepath: str,
    line: int,
    content: str,
    rule: security_detector_mod.SecurityRule,
    *,
    source: str,
    check_id: str | None = None,
) -> dict:
    entry = security_detector_mod.make_security_entry(filepath, line, content, rule)
    detail = dict(entry.get("detail") or {})
    detail["source"] = source
    detail["check_id"] = check_id or rule.check_id
    entry["detail"] = detail
    return entry


def _iter_regex_security_entries(filepath: str, content: str) -> list[dict]:
    entries: list[dict] = []
    for line_num, line in enumerate(content.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue

        if _COMMAND_INJECTION_RE.search(line):
            entries.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    security_detector_mod.SecurityRule(
                        check_id="command_injection",
                        summary="Shell command execution may enable command injection",
                        severity="high",
                        confidence="high",
                        remediation=_REMEDIATIONS["command_injection"],
                    ),
                    source="regex",
                )
            )

        if _UNSAFE_C_STRING_RE.search(line):
            entries.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    security_detector_mod.SecurityRule(
                        check_id="unsafe_c_string",
                        summary="Unsafe C string API may cause buffer overflow",
                        severity="high",
                        confidence="high",
                        remediation=_REMEDIATIONS["unsafe_c_string"],
                    ),
                    source="regex",
                )
            )

        if _INSECURE_RANDOM_RE.search(line):
            entries.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    security_detector_mod.SecurityRule(
                        check_id="insecure_random",
                        summary="Insecure random used in a security-sensitive context",
                        severity="medium",
                        confidence="medium",
                        remediation=_REMEDIATIONS["insecure_random"],
                    ),
                    source="regex",
                )
            )

        if _WEAK_HASH_RE.search(line):
            entries.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    security_detector_mod.SecurityRule(
                        check_id="weak_crypto_hash",
                        summary="Weak hash algorithm detected",
                        severity="medium",
                        confidence="medium",
                        remediation=_REMEDIATIONS["weak_crypto_hash"],
                    ),
                    source="regex",
                )
            )

    return entries


def _normalize_tool_path(raw_path: str, scan_root: Path) -> str:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = scan_root / candidate
    return str(candidate.resolve())


def _parse_clang_tidy_output(output: str, scan_path: Path) -> list[dict]:
    entries: list[dict] = []
    for line in output.splitlines():
        match = _CLANG_TIDY_RE.match(line.strip())
        if not match:
            continue
        severity = match.group(4).lower()
        if severity == "note":
            continue
        message = match.group(5).strip()
        check_id = (match.group(6) or "").strip()
        entries.append(
            {
                "file": _normalize_tool_path(match.group(1).strip(), scan_path),
                "line": int(match.group(2)),
                "severity": severity,
                "message": message,
                "check_id": check_id,
                "source": "clang-tidy",
            }
        )
    return entries


def _parse_cppcheck_output(output: str, scan_path: Path) -> list[dict]:
    entries: list[dict] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = _CPPCHECK_RE.match(line)
        if not match:
            continue
        filepath = match.group(1).strip()
        if filepath == "nofile":
            continue
        entries.append(
            {
                "file": _normalize_tool_path(filepath, scan_path),
                "line": int(match.group(2)),
                "severity": match.group(3).strip().lower(),
                "check_id": match.group(4).strip(),
                "message": match.group(5).strip(),
                "source": "cppcheck",
            }
        )
    return entries


def _normalize_kind(check_id: str, message: str) -> str | None:
    check = check_id.lower().strip()
    msg = message.lower().strip()
    text = f"{check} {msg}"

    if check in {"dangerousfunctionsystem", "cert-env33-c"} or re.search(
        r"\bsystem\b", msg
    ):
        return "command_injection"

    if any(api in text for api in _UNSAFE_C_STRING_APIS):
        return "unsafe_c_string"
    if "unsafebufferhandling" in check:
        return "unsafe_c_string"

    if check == "cert-msc30-c" or re.search(r"\brand\b", msg):
        return "insecure_random"

    if re.search(r"\bmd5\b|\bsha-?1\b", text):
        return "weak_crypto_hash"

    return None


def _looks_security_finding(source: str, check_id: str, message: str) -> bool:
    if _normalize_kind(check_id, message) is not None:
        return True

    text = f"{check_id} {message}".lower()
    if source == "clang-tidy":
        return bool(check_id.startswith("cert-") or check_id.startswith("clang-analyzer-security"))

    return any(
        token in text
        for token in (
            "overflow",
            "insecure",
            "unsafe",
            "crypto",
            "hash",
            "command",
            "injection",
            "deserial",
        )
    )


def _normalized_severity(kind: str | None, raw_severity: str) -> str:
    if kind in {"command_injection", "unsafe_c_string"}:
        return "high"
    if kind in {"insecure_random", "weak_crypto_hash"}:
        return "medium"
    if raw_severity in {"error", "critical"}:
        return "high"
    if raw_severity == "warning":
        return "medium"
    return "low"


def _normalized_confidence(source: str, raw_severity: str) -> str:
    if source == "clang-tidy":
        return "high"
    if raw_severity in {"error", "warning"}:
        return "high"
    return "medium"


def _normalize_tool_entry(entry: dict) -> dict | None:
    source = str(entry.get("source", "")).strip()
    check_id = str(entry.get("check_id", "")).strip()
    message = str(entry.get("message", "")).strip()
    filepath = str(entry.get("file", "")).strip()
    line = int(entry.get("line", 0) or 0)
    raw_severity = str(entry.get("severity", "warning")).strip().lower()

    if not filepath or line <= 0 or not message:
        return None
    if not _looks_security_finding(source, check_id, message):
        return None

    kind = _normalize_kind(check_id, message) or check_id or "security_finding"
    severity = _normalized_severity(kind, raw_severity)
    confidence = _normalized_confidence(source, raw_severity)
    remediation = _REMEDIATIONS.get(
        kind,
        "Review the finding in context and replace the unsafe API or pattern with a safer alternative.",
    )
    summary = f"[{check_id}] {message}" if check_id else message
    rel_path = rel(filepath)
    return {
        "file": filepath,
        "name": f"security::{kind}::{rel_path}::{line}",
        "tier": 2,
        "confidence": confidence,
        "summary": summary,
        "detail": {
            "kind": kind,
            "severity": severity,
            "line": line,
            "content": message[:200],
            "remediation": remediation,
            "source": source,
            "check_id": check_id or kind,
        },
    }


def _normalize_tool_entries(entries: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for entry in entries:
        converted = _normalize_tool_entry(entry)
        if converted is not None:
            normalized.append(converted)
    return normalized


def _cxx_files_in_scope(files: list[str], zone_map: FileZoneMap | None) -> list[str]:
    scoped: list[str] = []
    for filepath in files:
        suffix = Path(filepath).suffix.lower()
        if suffix not in _CXX_SUFFIXES:
            continue
        if zone_map is not None and zone_map.get(filepath) in (Zone.GENERATED, Zone.VENDOR):
            continue
        scoped.append(str(Path(filepath).resolve()))
    return scoped


def _scan_root_from_files(files: list[str]) -> Path | None:
    if not files:
        return None
    try:
        parent_paths = [str(Path(filepath).resolve().parent) for filepath in files]
        common = Path(os.path.commonpath(parent_paths)).resolve()
    except (OSError, ValueError):
        return None
    for candidate in (common, *common.parents):
        if any((candidate / marker).exists() for marker in _PROJECT_MARKERS):
            return candidate
    return common


def _relative_tool_args(files: list[str], scan_root: Path) -> str:
    return " ".join(
        shlex.quote(
            str(Path(filepath).resolve().relative_to(scan_root.resolve())).replace("\\", "/")
        )
        for filepath in files
    )


def _tool_result_state(result: ToolRunResult) -> ToolState:
    if result.status == "ok":
        return "ok"
    if result.status == "empty":
        return "empty"
    if result.error_kind == "tool_not_found":
        return "missing_tool"
    if result.error_kind == "tool_timeout":
        return "timeout"
    if result.error_kind == "parser_error":
        return "parse_error"
    return "error"


def _run_clang_tidy_invocation(
    scan_root: Path, source_files: list[str]
 ) -> CxxToolScanResult:
    file_args = _relative_tool_args(source_files, scan_root)
    result = run_tool_result(
        f"clang-tidy -p . --quiet -checks=-*,clang-analyzer-security*,cert-* {file_args}",
        scan_root,
        _parse_clang_tidy_output,
    )
    state = _tool_result_state(result)
    return CxxToolScanResult(
        tool="clang-tidy",
        state=state,
        entries=_normalize_tool_entries(result.entries),
        detail=result.message or result.error_kind or "",
        covered_files=tuple(source_files) if state in {"ok", "empty"} else (),
    )


def _merge_tool_scan_results(tool: str, results: list[CxxToolScanResult]) -> CxxToolScanResult:
    successful = [result for result in results if result.is_success()]
    if successful:
        entries = [entry for result in successful for entry in result.entries]
        covered_files = tuple(
            filepath for result in successful for filepath in result.covered_files
        )
        detail = next((
            result.detail for result in results if not result.is_success() and result.detail
        ), "")
        return CxxToolScanResult(
            tool=tool,
            state="ok" if entries else "empty",
            entries=entries,
            detail=detail,
            covered_files=covered_files,
        )

    first_failure = next((result for result in results if result.detail), results[0])
    return CxxToolScanResult(
        tool=tool,
        state=first_failure.state,
        entries=[],
        detail=first_failure.detail,
        covered_files=(),
    )


def _run_clang_tidy(scan_root: Path, files: list[str]) -> CxxToolScanResult:
    if shutil.which("clang-tidy") is None:
        return CxxToolScanResult(tool="clang-tidy", state="missing_tool", entries=[])

    source_files = [
        filepath for filepath in files if Path(filepath).suffix.lower() in _SOURCE_SUFFIXES
    ]
    if not source_files:
        return CxxToolScanResult(tool="clang-tidy", state="empty", entries=[])

    results: list[CxxToolScanResult] = []
    for idx in range(0, len(source_files), _CLANG_TIDY_BATCH_SIZE):
        batch = source_files[idx : idx + _CLANG_TIDY_BATCH_SIZE]
        batch_result = _run_clang_tidy_invocation(scan_root, batch)
        if batch_result.is_success() or len(batch) == 1:
            results.append(batch_result)
            continue
        results.append(batch_result)
        for filepath in batch:
            results.append(_run_clang_tidy_invocation(scan_root, [filepath]))

    return _merge_tool_scan_results("clang-tidy", results)


def _run_cppcheck_invocation(scan_root: Path, files: list[str]) -> CxxToolScanResult:
    file_args = _relative_tool_args(files, scan_root)
    result = run_tool_result(
        (
            "cppcheck --template='{file}:{line}:{severity}:{id}:{message}' "
            f"--enable=all --quiet {file_args}"
        ),
        scan_root,
        _parse_cppcheck_output,
    )
    state = _tool_result_state(result)
    return CxxToolScanResult(
        tool="cppcheck",
        state=state,
        entries=_normalize_tool_entries(result.entries),
        detail=result.message or result.error_kind or "",
        covered_files=tuple(files) if state in {"ok", "empty"} else (),
    )


def _run_cppcheck(scan_root: Path, files: list[str]) -> CxxToolScanResult:
    if shutil.which("cppcheck") is None:
        return CxxToolScanResult(tool="cppcheck", state="missing_tool", entries=[])

    if not files:
        return CxxToolScanResult(tool="cppcheck", state="empty", entries=[])

    results: list[CxxToolScanResult] = []
    for idx in range(0, len(files), _CPPCHECK_BATCH_SIZE):
        batch = files[idx : idx + _CPPCHECK_BATCH_SIZE]
        batch_result = _run_cppcheck_invocation(scan_root, batch)
        if batch_result.is_success() or len(batch) == 1:
            results.append(batch_result)
            continue
        results.append(batch_result)
        for filepath in batch:
            results.append(_run_cppcheck_invocation(scan_root, [filepath]))

    return _merge_tool_scan_results("cppcheck", results)


def _dedupe_subject(detail: dict) -> str:
    kind = str(detail.get("kind") or "")
    check_id = str(detail.get("check_id") or "")
    content = str(detail.get("content") or "")
    text = f"{check_id} {content}".lower()

    if kind == "command_injection":
        return "system" if "system" in text else (check_id or content or kind)
    if kind == "unsafe_c_string":
        for api in _UNSAFE_C_STRING_APIS:
            if api in text:
                return api
        if "buffer" in text:
            return "buffer"
    if kind == "insecure_random":
        if "rand" in text or "msc30" in text:
            return "rand"
    if kind == "weak_crypto_hash":
        if "md5" in text:
            return "md5"
        if "sha1" in text or "sha-1" in text:
            return "sha1"
    return check_id or content or kind


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    best: dict[tuple[str, str, int, str], dict] = {}
    for entry in entries:
        detail = entry.get("detail") or {}
        kind = str(detail.get("kind") or detail.get("check_id") or entry.get("name", ""))
        file_key = str(entry.get("file", ""))
        line = int(detail.get("line", 0) or 0)
        key = (kind, file_key, line, _dedupe_subject(detail))
        source = str(detail.get("source", "")).strip()
        current = best.get(key)
        if current is None:
            best[key] = entry
            continue
        current_source = str((current.get("detail") or {}).get("source", "")).strip()
        if _TOOL_PRIORITY.get(source, 99) < _TOOL_PRIORITY.get(current_source, 99):
            best[key] = entry

    return sorted(
        best.values(),
        key=lambda item: (
            str(item.get("file", "")),
            int((item.get("detail") or {}).get("line", 0) or 0),
            _TOOL_PRIORITY.get(str((item.get("detail") or {}).get("source", "")), 99),
            str((item.get("detail") or {}).get("kind", "")),
            str((item.get("detail") or {}).get("check_id", "")),
        ),
    )


def _regex_fallback(files: list[str]) -> list[dict]:
    entries: list[dict] = []
    for filepath in files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            logger.debug("Skipping unreadable C/C++ file %s in security detector: %s", filepath, exc)
            continue
        entries.extend(_iter_regex_security_entries(filepath, content))
    return entries


def _fallback_coverage(results: list[CxxToolScanResult]) -> DetectorCoverageStatus:
    tools = "/".join(result.tool for result in results) or "clang-tidy/cppcheck"
    states = {result.state for result in results}
    reason = "missing_dependency"
    if "timeout" in states:
        reason = "timeout"
    elif "parse_error" in states:
        reason = "parse_error"
    elif "error" in states:
        reason = "execution_error"

    if reason == "missing_dependency":
        summary = f"{tools} unavailable — C++ security fell back to regex heuristics."
    else:
        summary = f"{tools} could not complete — C++ security fell back to regex heuristics."

    return DetectorCoverageStatus(
        detector="security",
        status="reduced",
        confidence=0.65,
        summary=summary,
        impact=_TOOL_IMPACT_TEXT,
        remediation=(
            "Install clang-tidy/cppcheck and rerun scan, or verify the tool output manually "
            "if they are already installed."
        ),
        tool=tools,
        reason=reason,
    )


def _scan_root_failure_coverage() -> DetectorCoverageStatus:
    return DetectorCoverageStatus(
        detector="security",
        status="reduced",
        confidence=0.65,
        summary="C++ security fell back to regex heuristics because a common scan root could not be determined.",
        impact=_TOOL_IMPACT_TEXT,
        remediation="Scan files from a single checkout root or rerun the detector on one project tree at a time.",
        tool="clang-tidy/cppcheck",
        reason="execution_error",
    )


def detect_cxx_security(
    files: list[str],
    zone_map: FileZoneMap | None,
 ) -> LangSecurityResult:
    """Detect C/C++ security issues with tool-backed normalization and regex fallback."""
    scoped_files = _cxx_files_in_scope(files, zone_map)
    if not scoped_files:
        return LangSecurityResult(entries=[], files_scanned=0)

    scan_root = _scan_root_from_files(scoped_files)
    if scan_root is None:
        fallback_entries = _dedupe_entries(_regex_fallback(scoped_files))
        return LangSecurityResult(
            entries=fallback_entries,
            files_scanned=len(scoped_files),
            coverage=_scan_root_failure_coverage(),
        )

    tool_results: list[CxxToolScanResult] = []
    if (scan_root / "compile_commands.json").is_file():
        tool_results.append(_run_clang_tidy(scan_root, scoped_files))
    tool_results.append(_run_cppcheck(scan_root, scoped_files))

    tool_entries = [
        entry
        for result in tool_results
        if result.is_success()
        for entry in result.entries
    ]
    covered_files = {
        filepath
        for result in tool_results
        if result.is_success()
        for filepath in result.covered_files
    }
    uncovered_files = [filepath for filepath in scoped_files if filepath not in covered_files]
    if uncovered_files:
        merged_entries = _dedupe_entries(tool_entries + _regex_fallback(uncovered_files))
        return LangSecurityResult(
            entries=merged_entries,
            files_scanned=len(scoped_files),
            coverage=_fallback_coverage(tool_results),
        )

    if any(result.is_success() for result in tool_results):
        return LangSecurityResult(
            entries=_dedupe_entries(tool_entries),
            files_scanned=len(scoped_files),
            coverage=None,
        )

    fallback_entries = _dedupe_entries(_regex_fallback(scoped_files))
    return LangSecurityResult(
        entries=fallback_entries,
        files_scanned=len(scoped_files),
        coverage=_fallback_coverage(tool_results),
    )


__all__ = ["detect_cxx_security"]
