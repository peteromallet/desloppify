"""Tests for Python Bandit adapter zone filtering behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import rel
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, FileZoneMap, Zone
from desloppify.languages.python.detectors import bandit_adapter as adapter_mod


@dataclass
class _StubZoneMap:
    zone: Zone

    def get(self, _path: str) -> Zone:
        return self.zone


class _RelOnlyZoneMap:
    def get(self, path: str) -> Zone:
        return Zone.TEST if path.startswith("desloppify/tests/") else Zone.PRODUCTION


def _sample_result(*, test_id: str = "B108") -> dict[str, object]:
    return {
        "filename": "desloppify/tests/test_file.py",
        "test_id": test_id,
        "issue_severity": "MEDIUM",
        "issue_confidence": "MEDIUM",
        "line_number": 10,
        "issue_text": "hardcoded temp path",
        "test_name": "hardcoded_tmp_directory",
        "code": "x = '/tmp/demo'",
        "more_info": "https://example.test",
    }


def test_to_security_entry_skips_test_zone():
    entry = adapter_mod._to_security_entry(_sample_result(), _StubZoneMap(Zone.TEST))
    assert entry is None


def test_to_security_entry_skips_config_zone():
    entry = adapter_mod._to_security_entry(_sample_result(), _StubZoneMap(Zone.CONFIG))
    assert entry is None


def test_to_security_entry_keeps_production_zone():
    entry = adapter_mod._to_security_entry(
        _sample_result(),
        _StubZoneMap(Zone.PRODUCTION),
    )
    assert isinstance(entry, dict)
    assert entry["name"] == "security::B108::desloppify/tests/test_file.py::10"


def test_to_security_entry_normalizes_absolute_paths_before_zone_lookup():
    result = _sample_result()
    result["filename"] = str(get_project_root() / "desloppify/tests/test_file.py")
    entry = adapter_mod._to_security_entry(result, _RelOnlyZoneMap())
    assert entry is None


def test_to_security_entry_skips_test_zone_with_abs_key_zone_map():
    abs_path = str(get_project_root() / "desloppify/tests/test_file.py")
    zone_map = FileZoneMap([abs_path], COMMON_ZONE_RULES, rel_fn=rel)
    result = _sample_result()
    result["filename"] = abs_path

    entry = adapter_mod._to_security_entry(result, zone_map)
    assert entry is None


def _result_for_file(
    path: Path, *, line_number: int = 1, test_id: str = "B608"
) -> dict[str, object]:
    result = _sample_result(test_id=test_id)
    result["filename"] = str(path)
    result["line_number"] = line_number
    return result


def test_to_security_entry_honors_ruff_noqa_for_matching_code(tmp_path):
    """``# noqa: S608`` suppresses the matching Bandit ``B608`` finding."""
    src = tmp_path / "q.py"
    src.write_text('q = f"SELECT * FROM {t}"  # noqa: S608\n')
    entry = adapter_mod._to_security_entry(
        _result_for_file(src), _StubZoneMap(Zone.PRODUCTION)
    )
    assert entry is None


def test_to_security_entry_honors_bare_ruff_noqa(tmp_path):
    """A bare ``# noqa`` suppresses every check on the line."""
    src = tmp_path / "q.py"
    src.write_text('q = f"SELECT * FROM {t}"  # noqa\n')
    entry = adapter_mod._to_security_entry(
        _result_for_file(src), _StubZoneMap(Zone.PRODUCTION)
    )
    assert entry is None


def test_to_security_entry_ignores_noqa_for_unrelated_code(tmp_path):
    """``# noqa: E501`` does not suppress an unrelated ``B608`` finding."""
    src = tmp_path / "q.py"
    src.write_text('q = f"SELECT * FROM {t}"  # noqa: E501\n')
    entry = adapter_mod._to_security_entry(
        _result_for_file(src), _StubZoneMap(Zone.PRODUCTION)
    )
    assert isinstance(entry, dict)
    assert entry["detail"]["kind"] == "B608"


def test_to_security_entry_reports_when_line_has_no_noqa(tmp_path):
    """A genuinely unsuppressed line is still reported."""
    src = tmp_path / "q.py"
    src.write_text('q = f"SELECT * FROM {t}"\n')
    entry = adapter_mod._to_security_entry(
        _result_for_file(src), _StubZoneMap(Zone.PRODUCTION)
    )
    assert isinstance(entry, dict)


def test_detect_with_bandit_uses_absolute_scan_path(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeCompleted:
        stdout = '{"results": [], "metrics": {}}'

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted()

    monkeypatch.setattr(adapter_mod.subprocess, "run", _fake_run)

    result = adapter_mod.detect_with_bandit(
        Path("."),
        zone_map=None,
        exclude_dirs=["/tmp/demo/.venv"],
    )

    assert result.status.state == "ok"
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert Path(cmd[-1]).is_absolute()
