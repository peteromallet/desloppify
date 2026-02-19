"""Tests for TypeScript detector entrypoint result contracts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.typescript.detectors.contracts import (
    DetectorResult,
)
from desloppify.languages.typescript.detectors.deprecated import (
    detect_deprecated,
    detect_deprecated_result,
)
from desloppify.languages.typescript.detectors.logs import (
    detect_logs,
    detect_logs_result,
)
from desloppify.languages.typescript.detectors.patterns import (
    detect_pattern_anomalies,
    detect_pattern_anomalies_result,
)
from desloppify.languages.typescript.detectors.security import (
    detect_ts_security,
    detect_ts_security_result,
)


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def test_logs_result_contract(tmp_path):
    _write(tmp_path, "a.ts", "console.log('[Tag] hello')\n")
    result = detect_logs_result(tmp_path)
    entries, total = detect_logs(tmp_path)
    assert result.population_kind == "files"
    assert result.entries == entries
    assert result.population_size == total


def test_pattern_result_contract(tmp_path):
    _write(tmp_path, "src/a.ts", "const x = 1;\n")
    _write(tmp_path, "src/b.ts", "const y = 2;\n")
    result = detect_pattern_anomalies_result(tmp_path)
    entries, total = detect_pattern_anomalies(tmp_path)
    assert result.population_kind == "areas"
    assert result.entries == entries
    assert result.population_size == total


def test_deprecated_result_contract(tmp_path):
    _write(
        tmp_path,
        "legacy.ts",
        "/** @deprecated use newOne */ export function oldOne() {}\n",
    )
    result = detect_deprecated_result(tmp_path)
    entries, total = detect_deprecated(tmp_path)
    assert result.population_kind == "deprecated_symbols"
    assert result.entries == entries
    assert result.population_size == total


def test_security_result_contract():
    content = "const out = eval(userInput);\n"
    with patch.object(Path, "read_text", return_value=content):
        result = detect_ts_security_result(["/fake/src/test.ts"], None)
        entries, total = detect_ts_security(["/fake/src/test.ts"], None)
    assert result.population_kind == "files"
    assert result.entries == entries
    assert result.population_size == total


def test_detector_result_tuple_order_and_legacy_adapter():
    entries = [{"id": "a"}, {"id": "b"}]
    result = DetectorResult(
        entries=entries,
        population_kind="files",
        population_size=5,
    )
    tuple_view = result.as_tuple()
    assert tuple_view == (entries, 5)


def test_detector_result_as_tuple_returns_live_entries_alias():
    entries = [{"id": "a"}]
    result = DetectorResult(
        entries=entries,
        population_kind="files",
        population_size=1,
    )
    tuple_entries, _ = result.as_tuple()
    tuple_entries.append({"id": "b"})
    assert result.entries == [{"id": "a"}, {"id": "b"}]
