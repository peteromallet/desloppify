"""Stale @deprecated symbol detection."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.core.signal_patterns import DEPRECATION_MARKER_RE
from desloppify.languages.typescript.detectors.contracts import DetectorResult
from desloppify.utils import (
    c,
    find_ts_files,
    grep_count_files,
    grep_files,
    print_table,
    rel,
    resolve_path,
)

logger = logging.getLogger(__name__)


def detect_deprecated(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Deprecated detector entrypoint."""
    return detect_deprecated_result(path).as_tuple()


def detect_deprecated_result(path: Path) -> DetectorResult[dict[str, Any]]:
    """Find deprecated symbols with explicit population semantics."""
    ts_files = find_ts_files(path)
    hits = grep_files(DEPRECATION_MARKER_RE.pattern, ts_files, flags=re.IGNORECASE)

    entries = []
    seen_symbols = set()  # Deduplicate by file+symbol
    for filepath, lineno, content in hits:
        symbol, kind = _extract_deprecated_symbol(
            filepath,
            lineno,
            content,
            scan_root=path,
        )
        if not symbol:
            continue
        # Deduplicate (same symbol in same file, e.g., multiple @deprecated on interface props)
        key = (filepath, symbol)
        if key in seen_symbols:
            continue
        seen_symbols.add(key)
        importers = (
            _count_importers(symbol, filepath, ts_files=ts_files, scan_root=path)
            if kind == "top-level"
            else -1
        )
        entries.append(
            {
                "file": filepath,
                "line": lineno,
                "symbol": symbol,
                "kind": kind,
                "importers": importers,
            }
        )
    sorted_entries = sorted(entries, key=lambda e: e["importers"])
    return DetectorResult(
        entries=sorted_entries,
        population_kind="deprecated_symbols",
        population_size=len(sorted_entries),
    )


def _extract_deprecated_symbol(
    filepath: str,
    lineno: int,
    content: str,
    *,
    scan_root: Path | None = None,
) -> tuple[str | None, str]:
    """Extract the deprecated symbol name and whether it's a top-level or inline deprecation.

    Returns (symbol_name, kind) where kind is "top-level" or "property".
    """
    try:
        p = _resolve_source_file(filepath, scan_root=scan_root)
        lines = p.read_text().splitlines()
        content_stripped = content.strip()

        # Case 1: Inline @deprecated on a property/field
        # e.g., `/** @deprecated Use X instead */ fieldName?: Type;`
        # or `/** @deprecated */ export const oldThing = ...`
        if "/**" in content_stripped and "*/" in content_stripped:
            # This is a single-line JSDoc. Check what follows on the same or next line
            after_jsdoc = content_stripped.split("*/", 1)[1].strip()
            if after_jsdoc:
                # Property on same line: `/** @deprecated */ someField?: string;`
                m = re.match(r"(\w+)\s*[?:=]", after_jsdoc)
                if m:
                    return m.group(1), "property"
                # Declaration on same line: `/** @deprecated */ export const foo`
                m = re.match(
                    r"(?:export\s+)?(?:const|let|var|function|class|type|interface|enum)\s+(\w+)",
                    after_jsdoc,
                )
                if m:
                    return m.group(1), "top-level"

        # Case 2: @deprecated inside a multi-line JSDoc block — check if it's on a property
        # We need to look ahead to find what this annotates
        for offset in range(1, 8):
            idx = lineno - 1 + offset
            if idx >= len(lines):
                break
            src = lines[idx].strip()
            # Skip empty lines, comment continuations, closing comment
            if not src or src.startswith("*") or src.startswith("//"):
                continue
            # Top-level declaration
            m = re.match(
                r"(?:export\s+)?(?:declare\s+)?(?:const|let|var|function|class|type|interface|enum)\s+(\w+)",
                src,
            )
            if m:
                return m.group(1), "top-level"
            # Property/field: `fieldName?: Type;` or `fieldName: Type;`
            m = re.match(r"(\w+)\s*[?:]", src)
            if m:
                return m.group(1), "property"
            break

        # Case 3: @deprecated as inline comment on same line
        # e.g., `shotImageEntryId?: string; // @deprecated`
        # Check the current line for a preceding field name
        if "//" in content_stripped or "*" in content_stripped:
            # Look at the same line before the @deprecated
            marker_match = re.search(r"@deprecated", content_stripped, re.IGNORECASE)
            line_before = content_stripped
            if marker_match:
                line_before = content_stripped[: marker_match.start()]
            line_before = line_before.strip().rstrip("/*").rstrip("*").strip()
            m = re.search(r"(\w+)\s*[?:]", line_before)
            if m:
                return m.group(1), "property"

    except (OSError, UnicodeDecodeError) as exc:
        log_best_effort_failure(
            logger, f"read deprecated source context {filepath}", exc
        )
    return None, "unknown"


def _resolve_source_file(filepath: str, *, scan_root: Path | None) -> Path:
    if Path(filepath).is_absolute():
        return Path(filepath)
    if scan_root is not None:
        candidate = scan_root / filepath
        if candidate.exists():
            return candidate
    return Path(resolve_path(filepath))


def _count_importers(
    name: str, declaring_file: str, *, ts_files: list[str], scan_root: Path
) -> int:
    if not name:
        return -1
    matching = grep_count_files(name, ts_files, word_boundary=True)
    declaring_resolved = str(
        _resolve_source_file(declaring_file, scan_root=scan_root).resolve()
    )
    count = 0
    for match_file in matching:
        match_resolved = str(_resolve_source_file(match_file, scan_root=scan_root).resolve())
        if match_resolved != declaring_resolved:
            count += 1
    return count


def cmd_deprecated(args: Any) -> None:
    entries, _ = detect_deprecated(Path(args.path))
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return

    if not entries:
        print(c("No @deprecated annotations found.", "green"))
        return

    # Separate top-level and property deprecations
    top_level = [e for e in entries if e["kind"] == "top-level"]
    properties = [e for e in entries if e["kind"] == "property"]

    print(
        c(
            f"\nDeprecated symbols: {len(entries)} ({len(top_level)} top-level, {len(properties)} properties)\n",
            "bold",
        )
    )

    if top_level:
        print(c("Top-level (importable):", "cyan"))
        rows = []
        for e in top_level[: args.top]:
            imp = str(e["importers"]) if e["importers"] >= 0 else "?"
            status = (
                c("safe to remove", "green")
                if e["importers"] == 0
                else f"{imp} importers"
            )
            rows.append([e["symbol"], rel(e["file"]), status])
        print_table(["Symbol", "File", "Status"], rows, [30, 55, 20])
        print()

    if properties:
        print(c("Properties (inline):", "cyan"))
        rows = []
        for e in properties[: args.top]:
            rows.append([e["symbol"], rel(e["file"]), f"line {e['line']}"])
        print_table(["Property", "File", "Line"], rows, [30, 55, 10])
